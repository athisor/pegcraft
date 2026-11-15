"""Modelo de dibujo v1, forma JSON (un dict de Python). Especificacion: docs/formato/modelo-de-dibujo.md

dibujo = {"version": 1, "state": "derived"|"adopted"|"new", "units": {"name": str, "y": "up"},
          "source": {"kind": str, "sha256": str, "path": str}            (opcional)
          "opaque": [str],                                               lo que el origen trae y no se descifro
          "palette": {id: {"name", "palette", "kind": "solid"|"gradient"|"texture", "rgba": [r, g, b, a]|None}},
          "gradients": {id: [[a, b, c, d, e, f], ...]},                  matrices de los rellenos no solidos
          "arts": [{"name": "underlay"|"colour"|"line"|"overlay", "layers": [{"strokes": [trazo]}]}]}   siempre las cuatro, en ese orden
trazo  = {"id": str, "points": [[x, y, es_ancla]] | "geometry_of": id, "closed": bool,
          "line": id_color, "width": semiancho, "profile": {"knots": [[t, izq, der]], "interp": str, "raw": [[8 numeros]]},
          "fill_left": id_color, "fill_right": id_color, "invisible": True}
Los campos opcionales se omiten cuando no aplican. `fill_left` / `fill_right` son los lados GEOMETRICOS al recorrer el trazo en el orden de
sus puntos con el eje y hacia arriba: un contorno antihorario lleva su relleno en `fill_left`.
"""
import hashlib
import json

VERSION = 1
ARTS = ("underlay", "colour", "line", "overlay")
STATES = ("derived", "adopted", "new")
INTERP = ("linear", "catmull-rom", "x-harmony")
_KIND = {"solido": "solid", "degradado": "gradient", "textura": "texture"}
_TIPO = {v: k for k, v in _KIND.items()}
_CONOCIDOS = (b"TPAL", b"TVCI", b"CREA", b"AUIF")     # bloques del contenedor que no son arte y no se marcan como opacos


def desde_lector(m, origen=None, bloques=()):
    """Modelo de `sightread.tvg.decodificar` -> dibujo. `bloques` = etiquetas de bloques del contenedor que el lector no interpreta."""
    palette = {}
    for cid, c in m.get("paleta", {}).items():
        palette[cid] = {"name": c.get("nombre", ""), "palette": c.get("paleta", ""), "kind": _KIND.get(c.get("tipo", "solido"), "solid"),
                        "rgba": list(c["rgba"]) if c.get("rgba") is not None else None}
    arts = []
    for ai, nombre in enumerate(ARTS):
        capas = (m.get("artes", {}).get(nombre) or {}).get("capas", [])
        duenos, layers = {}, []          # id() de la lista de puntos -> id del trazo que la trae (el lector comparte la MISMA lista)
        for ci, capa in enumerate(capas):
            strokes = []
            for ti, t in enumerate(capa["trazos"]):
                e, sid = t["estilo"], "a%d-c%d-t%d" % (ai, ci, ti)
                s = {"id": sid}
                clave = id(t["puntos"])
                if t.get("ref") is not None and clave in duenos:
                    s["geometry_of"] = duenos[clave]
                else:
                    duenos.setdefault(clave, sid)
                    s["points"] = [[x, y, bool(a)] for (x, y), a in zip(t["puntos"], t["anclas"])]
                s["closed"] = bool(t["cerrado"])
                if e.get("lapiz") is not None:
                    s["line"], s["width"] = e["lapiz"], e["ancho"]
                if t.get("perfil"):
                    s["profile"] = {"knots": [[k[0], k[1][0], k[2][0]] for k in t["perfil"]], "interp": "x-harmony",
                                    "raw": [list(k[1][1:]) + list(k[2][1:]) for k in t["perfil"]]}
                if e.get("der"):          # el "der" del origen queda geometricamente a la izquierda (y hacia arriba)
                    s["fill_left"] = e["der"]
                if e.get("izq"):
                    s["fill_right"] = e["izq"]
                if e.get("invisible"):
                    s["invisible"] = True
                strokes.append(s)
            layers.append({"strokes": strokes})
        arts.append({"name": nombre, "layers": layers})
    avisos = " ".join(m.get("avisos", []))
    opaque = {"block:" + b for b in bloques}
    if "capa de texto" in avisos:
        opaque.add("text")
    if "tGTB" in avisos:
        opaque.add("profile-undecoded")
    if "paleta" in avisos:
        opaque.add("palette-undecoded")
    if any(c["kind"] == "texture" for c in palette.values()):
        opaque.add("texture-fill")
    d = {"version": VERSION, "state": "derived", "units": {"name": "x-harmony", "y": "up"}, "opaque": sorted(opaque), "palette": palette,
         "gradients": {cid: [list(x) for x in ms] for cid, ms in m.get("tgco", {}).items() if palette.get(cid, {}).get("kind") != "solid"},
         "arts": arts}
    if origen:
        d["source"] = dict(origen)
    return d


def desde_tvg(datos, ruta=None):
    """bytes de un .tvg -> dibujo, con `source` (huella sha256) y los bloques no interpretados en `opaque`."""
    from sightread.tvg import contenedor, decodificar
    from sightread.tvg.modelo import ARTES
    datos = bytes(datos)
    m = decodificar(datos)
    extra = sorted({etq.decode("latin1") for etq, _modo, _carga in contenedor.abrir(datos)["bloques"]
                    if etq.upper() not in ARTES and etq not in _CONOCIDOS})
    origen = {"kind": "tvg", "sha256": hashlib.sha256(datos).hexdigest()}
    if ruta:
        origen["path"] = str(ruta).replace("\\", "/")
    return desde_lector(m, origen, extra)


def a_modelo_lector(d):
    """dibujo -> modelo con la forma del de `sightread.tvg.decodificar` (para dibujarlo con `sightread.tvg.a_svg`). Inversa de `desde_lector`."""
    paleta = {cid: {"nombre": c["name"], "rgba": tuple(c["rgba"]) if c.get("rgba") is not None else None, "paleta": c["palette"],
                    "tipo": _TIPO[c["kind"]]} for cid, c in d["palette"].items()}
    artes = {}
    for a in d["arts"]:
        geo, capas = {}, []
        for capa in a["layers"]:
            trazos = []
            for s in capa["strokes"]:
                if "geometry_of" in s:
                    (puntos, anclas), ref = geo[s["geometry_of"]], 0
                else:
                    puntos, anclas, ref = [(p[0], p[1]) for p in s["points"]], [bool(p[2]) for p in s["points"]], None
                    geo[s["id"]] = (puntos, anclas)
                pf, perfil = s.get("profile"), None
                if pf:
                    raw = pf.get("raw") or [[0.0] * 8] * len(pf["knots"])
                    perfil = [(k[0], (k[1], *r[:4]), (k[2], *r[4:])) for k, r in zip(pf["knots"], raw)]
                trazos.append({"puntos": puntos, "anclas": anclas, "cerrado": bool(s["closed"]), "perfil": perfil, "ref": ref,
                               "estilo": {"der": s.get("fill_left"), "izq": s.get("fill_right"), "lapiz": s.get("line"),
                                          "ancho": s.get("width", 0.0), "invisible": bool(s.get("invisible"))}})
            capas.append({"trazos": trazos})
        if capas:
            artes[a["name"]] = {"capas": capas}
    return {"disp": None, "paleta": paleta, "artes": artes, "avisos": [],
            "tgco": {cid: [tuple(x) for x in ms] for cid, ms in d.get("gradients", {}).items()}}


def nucleo(d):
    """Lo que el dibujo dice del arte (sin origen, estado ni opacos): para comparar idas y vueltas por el modelo del lector."""
    return {"palette": d["palette"], "gradients": d.get("gradients", {}), "arts": d["arts"]}


def canonico(o):
    """Texto JSON canonico (claves ordenadas) para comparar dos dibujos."""
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validar(d):
    """Errores de forma de un dibujo (lista de textos; vacia = bien formado). No comprueba que los colores existan en una paleta."""
    err = []
    if d.get("version") != VERSION:
        err.append("version %r (se espera %d)" % (d.get("version"), VERSION))
    if d.get("state") not in STATES:
        err.append("state %r" % (d.get("state"),))
    if [a.get("name") for a in d.get("arts", [])] != list(ARTS):
        err.append("arts debe traer underlay, colour, line, overlay en ese orden")
        return err
    vistos = set()
    for a in d["arts"]:
        con_puntos = {}
        for capa in a.get("layers", []):
            for s in capa.get("strokes", []):
                sid = s.get("id")
                if not isinstance(sid, str) or not sid:
                    err.append("trazo sin id")
                    continue
                if sid in vistos:
                    err.append("id repetido: " + sid)
                vistos.add(sid)
                if ("points" in s) == ("geometry_of" in s):
                    err.append(sid + ": debe traer points o geometry_of (uno solo)")
                    continue
                if "geometry_of" in s:
                    pts = con_puntos.get(s["geometry_of"])
                    if pts is None:
                        err.append("%s: geometry_of %r no es un trazo anterior con puntos del mismo arte" % (sid, s["geometry_of"]))
                        continue
                else:
                    pts = s["points"]
                    if any(len(p) != 3 or not _num(p[0]) or not _num(p[1]) or not isinstance(p[2], bool) for p in pts):
                        err.append(sid + ": cada punto es [x, y, es_ancla]")
                        continue
                    con_puntos[sid] = pts
                cerrado = len(pts) > 1 and pts[0][:2] == pts[-1][:2]
                if s.get("closed") is not cerrado:
                    err.append(sid + ": closed no coincide con sus puntos (primer punto == ultimo)")
                if "line" in s and not _num(s.get("width")):
                    err.append(sid + ": line sin width")
                for k in ("line", "fill_left", "fill_right"):
                    if k in s and not isinstance(s[k], str):
                        err.append("%s: %s debe ser un id de color (texto)" % (sid, k))
                pf = s.get("profile")
                if pf is not None:
                    nudos = pf.get("knots") or []
                    if not nudos or any(len(k) != 3 or not all(_num(v) for v in k) for k in nudos):
                        err.append(sid + ": profile.knots = [[t, izq, der], ...]")
                    if pf.get("interp") not in INTERP:
                        err.append("%s: profile.interp %r" % (sid, pf.get("interp")))
                    if "raw" in pf and (len(pf["raw"]) != len(nudos) or any(len(r) != 8 for r in pf["raw"])):
                        err.append(sid + ": profile.raw = 8 numeros por nudo")
    return err
