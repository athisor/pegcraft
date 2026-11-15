"""Residual del plano: el arbol de origen EXACTO del proyecto Harmony (relacion biunivoca con el .xstage).

Ver (doc interna omitida) (arquitectura, E1/E2/E3/E5/E6) y la seccion «Implementacion del residual (11-11)».

Layout dentro del plano:
  harmony/arbol.json.gz     {formato, version, archivos: {ruta_relativa: documento xmlfiel}}  (.xstage, .aux, .plt, PALETTE_LIST, audio.tbl)
  harmony/manifiesto.json   ruta relativa + bytes + sha256 de CADA archivo del proyecto (.tvg y binarios: solo referencia), sin rutas absolutas
  harmony/mapa_ids.json     id estable (generado, persistente) <-> ruta del nodo/columna/elemento (Harmony enlaza por nombre)

Nada de aqui se calcula con rutas absolutas ni con fechas: mismos bytes -> mismo plano (I2).
"""
import re, json, gzip, hashlib, time
from pathlib import Path
from urllib.parse import quote, unquote
from ..formato.xmlfiel import ida, vuelta, recorrer, attr, poner_attr

ESQUEMA_PLANO = "x-harmony/2"
VERSION_LECTOR = "pegcraft-residual/1"
FORMATO_ARBOL, VERSION_ARBOL = "pegcraft.arbol", 1
REL_ARBOL, REL_MANIFIESTO, REL_MAPA = "harmony/arbol.json.gz", "harmony/manifiesto.json", "harmony/mapa_ids.json"
TEXTO_EXT = (".xstage", ".aux", ".plt")
TEXTO_NOMBRE = ("PALETTE_LIST", "audio.tbl")
SALTAR_DIRS = {"ref"}
_USER = re.compile(rb'(\b(?:username|realUsername)=")[^"]*(")')
_ABS = re.compile(rb'(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s"<>|]*')


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_archivo(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def es_texto(rel):
    n = rel.rsplit("/", 1)[-1]
    return n.endswith(TEXTO_EXT) or n in TEXTO_NOMBRE


def listar_proyecto(raiz):
    """Rutas relativas (con /) de todos los archivos del proyecto, orden determinista; sin `ref/` ni carpetas ocultas."""
    raiz = Path(raiz); out = []
    for p in sorted(raiz.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(raiz).as_posix()
        partes = rel.split("/")
        if partes[0] in SALTAR_DIRS or any(x.startswith((".", "_")) for x in partes[:-1]):
            continue
        out.append(rel)
    return out


def banderas_personales(b):
    return {"usuario": len(_USER.findall(b)), "rutas_absolutas": len(_ABS.findall(b))}


def depurar_bytes(b):
    """Reemplaza username/realUsername y rutas absolutas. SOLO si el autor lo pide (rompe la identidad byte a byte con el original)."""
    b = _USER.sub(rb"\1anonimo\2", b)
    return _ABS.sub(lambda m: b"ruta-depurada/" + re.split(rb"[\\/]", m.group())[-1], b)


def construir(xs, depurar_personal=False):
    """-> (arbol dict, manifiesto dict). Lee TODO el proyecto de la escena `xs` (solo lectura)."""
    raiz = Path(xs).parent
    archivos, docs = [], {}
    personal = False
    for rel in listar_proyecto(raiz):
        p = raiz / rel
        sz = p.stat().st_size
        ent = {"ruta": rel, "bytes": sz, "sha256": sha_archivo(p)}
        if es_texto(rel):
            b = p.read_bytes()
            fl = banderas_personales(b)
            if fl["usuario"] or fl["rutas_absolutas"]:
                ent["personal"] = fl
            if depurar_personal:
                bd = depurar_bytes(b)
                if bd != b:
                    ent["depurado"] = True; ent["sha256_depurado"] = sha_bytes(bd); ent["bytes_depurado"] = len(bd)
                b = bd
            elif ent.get("personal"):
                personal = True
            ent["clase"] = "arbol"
            docs[rel] = ida(b)
        else:
            ent["clase"] = "referencia"        # .tvg, audio, texturas: nunca se copian ni se reescriben (I7)
        archivos.append(ent)
    man = {"esquema": "harmony-manifiesto/1", "version_lector": VERSION_LECTOR, "esquema_plano": ESQUEMA_PLANO,
           "raiz": raiz.name, "escena": Path(xs).name, "contiene_datos_personales": personal, "depurado_personal": bool(depurar_personal),
           "aviso": "el arbol contiene username/realUsername y rutas absolutas de produccion: no versionar ni compartir sin depurar" if personal else None,
           "archivos": archivos}
    return {"formato": FORMATO_ARBOL, "version": VERSION_ARBOL, "archivos": docs}, man


def escribir_json_gz(p, obj):
    b = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    Path(p).write_bytes(gzip.compress(b, 6, mtime=0))
    return len(b)


def leer_json_gz(p):
    return json.loads(gzip.decompress(Path(p).read_bytes()))


# ------------------------------------------------------------------ lecturas del arbol (fuente unica)
def buscar(doc, *tags):
    """Primer elemento cuya ruta de etiquetas termina en `tags` (ruta completa si empieza en la raiz)."""
    n = len(tags)
    for ruta, nodo in recorrer(doc):
        if nodo[0] == tags[-1] and (ruta + (nodo[0],))[-n:] == tags:
            return nodo
    return None


def framerate(doc_xstage):
    n = buscar(doc_xstage, "project", "options", "framerate")
    v = attr(n, "val") if n else None
    return float(v) if v is not None else None


def version_harmony(doc_xstage):
    n = buscar(doc_xstage, "project")
    return {k: attr(n, k) for k in ("version", "build", "creator")} if n else {}


# ------------------------------------------------------------------ rutas de nodo/atributo
_SEG = re.compile(r"^([^\[@]+)(?:\[(\d+)\]|\[@([^=\]]+)=([^\]]*)\])?$")


def _hijos(nodo, tag):
    return [h for h in nodo[2] if isinstance(h, list) and h[0] == tag]


def resolver(doc, ruta):
    """'project/scenes/scene/columns/column[@name=X]/points/pt[3]@y' -> (nodo, atributo|None).
    Segmentos: tag | tag[N] (N-esimo hermano con esa etiqueta, desde 0) | tag[@k=v] (v con %-escapes). Termina opcionalmente en @atributo."""
    ruta, at = re.match(r"^(.*?)(?:@([A-Za-z_][\w:.\-]*))?$", ruta).groups()
    segs = [s for s in ruta.split("/") if s]
    cont = {"nodos": [h for h in doc["nodos"] if isinstance(h, list)]}
    cur = [None, [], cont["nodos"]]
    nodo = cur
    for s in segs:
        m = _SEG.match(s)
        if not m:
            raise KeyError(f"segmento invalido: {s!r}")
        tag, k, an, av = m.groups()
        cand = _hijos(nodo, tag)
        if k is not None:
            if int(k) >= len(cand):
                raise KeyError(f"{s}: solo hay {len(cand)}")
            nodo = cand[int(k)]
        elif an is not None:
            av = unquote(av)
            sel = [c for c in cand if attr(c, an) == av]
            if not sel:
                raise KeyError(f"{s}: no existe")
            nodo = sel[0]
        else:
            if not cand:
                raise KeyError(f"{s}: no existe")
            nodo = cand[0]
    return nodo, (at or None)


# ------------------------------------------------------------------ mapa_ids (E3)
def selectores(hermanos, nombre="name"):
    """Selector estable de cada hermano (lista alineada): `tag[@name=X]` si el nombre es unico entre hermanos de la misma
    etiqueta; si no, `tag[N]` (N-esimo con esa etiqueta). O(n)."""
    cuenta, vistos = {}, {}
    for h in hermanos:
        k = (h[0], attr(h, nombre))
        cuenta[k] = cuenta.get(k, 0) + 1
    out = []
    for h in hermanos:
        nm = attr(h, nombre)
        if nm is not None and cuenta[(h[0], nm)] == 1:
            out.append(f"{h[0]}[@{nombre}={quote(nm, safe='')}]")
        else:
            n = vistos.get(h[0], 0); vistos[h[0]] = n + 1
            out.append(f"{h[0]}[{n}]")
            continue
        vistos[h[0]] = vistos.get(h[0], 0) + 1
    return out


def generar_mapa_ids(doc_xstage, previo=None):
    """Ids estables: se reusan los de `previo` por (tipo, ruta de nombres); los nuevos son secuenciales; los que desaparecen quedan
    como `huerfano` (un renombrado no cambia el id si se reasigna a mano). Regenerable: sin `previo` sale el mismo mapa."""
    previo = previo or {}
    indice = {(e["tipo"], e["ruta"]): i for fam in ("nodos", "columnas", "elementos") for i, e in previo.get(fam, {}).items()}
    sig = int(previo.get("siguiente", 1))
    nuevo = {"esquema": "mapa-ids/1", "nodos": {}, "columnas": {}, "elementos": {}, "avisos": []}
    visto = set()

    def dar(fam, pref, tipo, ruta, extra):
        nonlocal sig
        k = (tipo, ruta)
        if k in visto:
            nuevo["avisos"].append(f"nombre duplicado {tipo}:{ruta}")
            n = 2
            while (tipo, f"{ruta}#{n}") in visto:
                n += 1
            ruta = f"{ruta}#{n}"; k = (tipo, ruta)
        visto.add(k)
        i = indice.get(k)
        if i is None:
            i = f"{pref}{sig:06d}"; sig += 1
        nuevo[fam][i] = {"tipo": tipo, "ruta": ruta, **extra}

    raiz = buscar(doc_xstage, "project")
    if raiz is None:
        return nuevo
    els = _hijos(buscar(doc_xstage, "project", "elements") or [None, [], []], "element")
    for el, s in zip(els, selectores(els)):
        dar("elementos", "e", "elemento", attr(el, "elementName") or attr(el, "id"),
            {"id_harmony": attr(el, "id"), "ruta_arbol": f"project/elements/{s}"})
    scs = _hijos(buscar(doc_xstage, "project", "scenes") or [None, [], []], "scene")
    for sc, ssel in zip(scs, selectores(scs)):
        base = f"project/scenes/{ssel}"
        cols = [h for h in sc[2] if isinstance(h, list) and h[0] == "columns"]
        for cs in cols:
            hs = _hijos(cs, "column")
            for c, s in zip(hs, selectores(hs)):
                dar("columnas", "c", "columna", attr(c, "name") or attr(c, "id"),
                    {"tipo_columna": attr(c, "type"), "id_harmony": attr(c, "id"), "ruta_arbol": f"{base}/columns/{s}"})
        for rg in _hijos(sc, "rootgroup"):
            _grupo(rg, f"{base}/rootgroup", attr(rg, "name") or "Top", dar)
    return {**nuevo, "siguiente": sig,
            "huerfanos": sorted(i for fam in ("nodos", "columnas", "elementos") for i, e in previo.get(fam, {}).items() if (e["tipo"], e["ruta"]) not in visto)}


def _grupo(g, ruta_arbol, ruta, dar):
    for nl in _hijos(g, "nodeslist"):
        hs = [h for h in nl[2] if isinstance(h, list) and h[0] in ("module", "group")]
        for h, s in zip(hs, selectores(hs)):
            nm = attr(h, "name") or "?"
            ra = f"{ruta_arbol}/nodeslist/{s}"
            r = f"{ruta}/{nm}"
            dar("nodos", "n", "grupo" if h[0] == "group" else "modulo", r, {"modulo": attr(h, "type"), "ruta_arbol": ra})
            if h[0] == "group":
                _grupo(h, ra, r, dar)


def resolver_ref(mapa, ref):
    """'n000012/attrs/position/x@val' o 'c000034/points/pt[0]@y' o una ruta del arbol -> ruta del arbol."""
    cab, _, resto = ref.partition("/")
    for fam in ("nodos", "columnas", "elementos"):
        if cab in mapa.get(fam, {}):
            base = mapa[fam][cab]["ruta_arbol"]
            return base + (("/" + resto) if resto and not resto.startswith("@") else resto)
    return ref


# ------------------------------------------------------------------ escritura en el plano
def escribir_harmony(plano_dir, xs, depurar_personal=False):
    """Escribe harmony/{arbol.json.gz, manifiesto.json, mapa_ids.json} bajo plano_dir. Devuelve estadisticas y el bloque `origen`."""
    h = Path(plano_dir) / "harmony"; h.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    arbol, man = construir(xs, depurar_personal)
    nbytes = escribir_json_gz(h / "arbol.json.gz", arbol)
    sha_arbol = sha_archivo(h / "arbol.json.gz")
    dx = arbol["archivos"][man["escena"]]
    previo = None
    if (h / "mapa_ids.json").is_file():
        try:
            previo = json.loads((h / "mapa_ids.json").read_text(encoding="utf-8"))
        except Exception:
            previo = None
    mapa = generar_mapa_ids(dx, previo)
    mapa["sha256_escena"] = dx["sha256"]
    (h / "mapa_ids.json").write_text(json.dumps(mapa, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    man["sha256_arbol"] = sha_arbol
    (h / "manifiesto.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    ent = next(a for a in man["archivos"] if a["ruta"] == man["escena"])
    origen = {"escena": man["escena"], "sha256_escena": ent.get("sha256_depurado", ent["sha256"]), "bytes_escena": ent.get("bytes_depurado", ent["bytes"]),
              "version_harmony": version_harmony(dx), "framerate": {"ref": "project/options/framerate@val", "archivo": man["escena"]},
              "manifiesto": REL_MANIFIESTO}
    residual = {"arbol": REL_ARBOL, "mapa_ids": REL_MAPA, "sha256_arbol": sha_arbol, "formato": f"{FORMATO_ARBOL}/{VERSION_ARBOL}"}
    return {"origen": origen, "residual": residual, "fps": framerate(dx), "archivos": len(man["archivos"]), "en_arbol": len(arbol["archivos"]),
            "bytes_json": nbytes, "bytes_gz": (h / "arbol.json.gz").stat().st_size, "datos_personales": man["contiene_datos_personales"],
            "nodos_mapa": len(mapa["nodos"]), "columnas_mapa": len(mapa["columnas"]), "t_residual": round(time.perf_counter() - t0, 2)}


# ------------------------------------------------------------------ vuelta
def vuelta_plano(plano_dir, salida, editar=None, origen_dir=None):
    """Reconstruye TODOS los archivos del arbol en `salida` y los compara con el manifiesto (sha256).
    editar = [(ref, valor)]: aplica cada edicion al arbol de la escena (por id del mapa o ruta) y exige que cambie solo esa linea."""
    t0 = time.perf_counter()
    h = Path(plano_dir) / "harmony"; salida = Path(salida)
    arbol = leer_json_gz(h / "arbol.json.gz"); man = json.loads((h / "manifiesto.json").read_text(encoding="utf-8"))
    mapa = json.loads((h / "mapa_ids.json").read_text(encoding="utf-8")) if (h / "mapa_ids.json").is_file() else {}
    esperado = {a["ruta"]: a.get("sha256_depurado", a["sha256"]) for a in man["archivos"]}
    originales = {}
    res = {"archivos": 0, "identicos": 0, "distintos": [], "referencias": 0, "referencias_sin_verificar": 0, "cambios": []}
    for rel, doc in arbol["archivos"].items():
        orig = vuelta(doc)
        originales[rel] = orig
    if editar:
        escena = man["escena"]; doc = arbol["archivos"][escena]
        for ref, valor in editar:
            ruta = resolver_ref(mapa, ref)
            nodo, at = resolver(doc, ruta)
            if not at:
                raise SystemExit(f"la edicion {ref!r} debe terminar en @atributo")
            antes = attr(nodo, at)
            if antes is None:
                raise SystemExit(f"{ref!r}: el atributo no existe")
            poner_attr(nodo, at, str(valor))
            res["cambios"].append({"ref": ref, "ruta": ruta, "antes": antes, "despues": str(valor)})
    for rel, doc in arbol["archivos"].items():
        b = vuelta(doc)
        p = salida / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b)
        res["archivos"] += 1
        if not editar:
            if sha_bytes(b) == esperado[rel]:
                res["identicos"] += 1
            else:
                res["distintos"].append(rel)
    if editar:
        a = originales[man["escena"]].split(b"\n"); b = (salida / man["escena"]).read_bytes().split(b"\n")
        dif = [i + 1 for i, (x, y) in enumerate(zip(a, b)) if x != y] if len(a) == len(b) else None
        res["lineas_distintas"] = dif if dif is None or len(dif) < 50 else len(dif)
        res["solo_las_editadas"] = dif is not None and len(dif) <= len(res["cambios"])
        res["distintos_otros_archivos"] = [r for r in arbol["archivos"] if r != man["escena"] and (salida / r).read_bytes() != originales[r]]
    for a in man["archivos"]:
        if a["clase"] != "referencia":
            continue
        res["referencias"] += 1
        if origen_dir and (Path(origen_dir) / a["ruta"]).is_file():
            if sha_archivo(Path(origen_dir) / a["ruta"]) != a["sha256"]:
                res["referencias_sin_verificar"] += 1
        else:
            res["referencias_sin_verificar"] += 1       # I7: aviso, no error
    res["bytes_ok"] = (res["identicos"] == res["archivos"]) if not editar else None
    res["t"] = round(time.perf_counter() - t0, 2)
    return res


# ------------------------------------------------------------------ coherencia modelo <-> arbol
def contradicciones(plano_dir):
    """Lista de contradicciones entre el modelo (sidecar) y el arbol. Vacia = coherente."""
    from .plano import cargar_sidecar
    raw, flat = cargar_sidecar(Path(plano_dir) / "plano" / "anim" / "escena.x-harmony.json")
    out = []
    if raw.get("esquema") != ESQUEMA_PLANO:
        return [f"sidecar {raw.get('esquema')}: sin residual que comparar"]
    h = Path(plano_dir) / "plano" / "harmony"
    arbol_p = h / "arbol.json.gz"
    if not arbol_p.is_file():
        return ["falta harmony/arbol.json.gz"]
    if sha_archivo(arbol_p) != raw["residual"]["sha256_arbol"]:
        out.append("arbol modificado despues de compilar: el modelo es una vista obsoleta (recompilar)")
    arbol = leer_json_gz(arbol_p)
    dx = arbol["archivos"].get(raw["origen"]["escena"])
    if dx is None:
        out.append("la escena de origen no esta en el arbol")
    elif dx["sha256"] != raw["origen"]["sha256_escena"]:
        out.append("sha256 de la escena en el arbol distinto del que vio el compilador")
    return out
