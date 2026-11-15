"""escena Harmony (.xstage) -> directorio de plano externo (D-Fmt) usando el horneado existente (pegcraft.bake.hornear).

Layout escrito (salida = DIR):
  DIR/plano/scene.json                       Scene (timing, camera, instancia `escena`, library) + bloque `x-harmony`
  DIR/plano/anim/escena.anim.json            canales (path, attribute, curve Hold) + `extension_channels` + `exposure` (runs, D-Tab)
  DIR/plano/anim/escena.x-harmony.json       lo que el formato externo no modela hoy (capas, cutters, puertos, avisos) preservado tal cual
  DIR/biblioteca/rigs/<id>/definition.json   rig plano (1 peg por rama de READ, matrices MUNDO) + slots
  DIR/biblioteca/rigs/<id>/drawings/*.svg    SVG derivados (cache) + fuentes.json (ruta+hash del .tvg original)
  DIR/LEEME.md
  DIR/_horneado/                             escena_f<N>.json + dibujos/ del horneado (intermedio, se puede borrar)
"""
import json, hashlib, shutil, sys
from pathlib import Path
from . import comun

STD = ("PositionX", "PositionY", "Rotation", "ScaleX", "ScaleY")
LEEME = """# Plano externo generado desde un .xstage (prototipo `python -m pegcraft a-planofmt`)

Origen: {escena}  fotogramas {f0}:{f1}  ({n} cuadros)

## Que contiene (cabe en el formato externo de hoy o con un campo aditivo)
- `plano/scene.json`: timing, camara identidad, UNA instancia `escena` (definicion `{rid}`), referencia a `../biblioteca`.
- `plano/anim/escena.anim.json`: por cada rama de READ un peg `mundo/<ruta>@<puertos>` con matriz MUNDO horneada por cuadro,
  descompuesta en PositionX/Y, Rotation (rad), ScaleX/Y (negativo = espejo), y canales Hold solo donde el valor cambia.
  `exposure`: runs (inicio, largo, dibujo) por peg (D-Tab `exposure_runs`). Todo en CAMPOS de Harmony (4:3), no en px.
- `biblioteca/rigs/{rid}/drawings/*.svg`: SVG derivados del .tvg (cache regenerable); `fuentes.json` da ruta relativa y sha256 del .tvg.

## Que NO cabe y viaja como extension (el formato externo no lo lee ni lo dibuja hoy)
- `extension_channels` (atributos que `Attribute` no tiene): `x:ShearX`, `x:Opacity`, `x:Order` (orden de apilado por cuadro), `x:Z`.
- `escena.x-harmony.json`: capas de arte por rama (underlay/colour/line/overlay), CUTTER + mattes (recorte), puertos de composite,
  razon del orden, avisos. Sin esto el render NO se reproduce (cutters = 0,053 de px_ok medido en PLANO fN).

## Que se pierde (no esta en el horneado, y por tanto tampoco aqui)
- La jerarquia de pegs (se hornea la matriz mundo: animar un brazo ya no mueve a sus hijos), pivotes, expresiones, 3D path/velocidad,
  curvas Bezier originales (solo muestras por cuadro), la camara del .xstage (solo la rejilla px/campo de `x-harmony.camara`),
  Auto-Patch como forma propia, BLEND_MODE/GAUSSIAN/COLOR_OVERRIDE, audio, backdrops, paletas por id, el grafo con grupos.
- Los deformadores (CurveModule/OffsetModule) quedan APLASTADOS en SVG por cuadro (`...__def_...svg`): no hay deformador editable.
- fps: 24 por SUPUESTO (no se leyo del .xstage).
Sin conversion de vuelta a Harmony: el .tvg original no se toca.
"""


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _indice_tvg(esc):
    ix = {}
    for t in (Path(esc) / "elements").glob("*/*.tvg"):
        ix.setdefault(t.stem, t)                       # <elemento>-<dibujo>
        ix.setdefault(f"{t.parent.name}-{t.stem.rsplit('-', 1)[-1]}", t)   # <carpeta>-<dibujo>
    return ix


def _nombres(piezas):
    vistos, out = {}, []
    for p in piezas:
        k = f"{p['id']}@{'.'.join(str(x) for x in p.get('puertos', []))}"
        n = vistos.get(k, 0); vistos[k] = n + 1
        out.append(k if n == 0 else f"{k}#{n}")
    return out


def exportar(xs, f0, f1, salida, rid=None, **kw_hornear):
    from ..bake.hornear import hornear
    xs = str(xs); out = Path(salida); esc = Path(xs).parent
    rid = rid or Path(xs).stem
    work = out / "_horneado"; work.mkdir(parents=True, exist_ok=True)
    frames = list(range(f0, f1 + 1)); J = {}
    for f in frames:
        ruta, _ = hornear(xs, f, str(work), nombre=f"escena_f{f}.json", **kw_hornear)
        J[f] = json.load(open(ruta, encoding="utf-8"))

    # --- series por rama de READ
    P = {}
    for f in frames:
        for k, p in zip(_nombres(J[f]["piezas"]), J[f]["piezas"]):
            P.setdefault(k, {"id": p["id"], "puertos": p.get("puertos", []), "fr": [], "rec": []})
            P[k]["fr"].append(f); P[k]["rec"].append(p)

    dib = {}      # id de dibujo -> archivo svg
    def reg(rel):
        n = Path(rel).name; dib[Path(rel).stem] = n; return Path(rel).stem

    canales, ext, expo, side = [], [], [], {}
    nombres = ["mundo"]
    for k, d in P.items():
        path, fr, rec = ["mundo", k], d["fr"], d["rec"]
        comps = [comun.descomponer(p["matriz_campo"]) for p in rec]
        for a in STD:
            canales.append({"path": path, "attribute": a, "curve": comun.claves_hold(fr, [c[a] for c in comps])})
        if any(c["ShearX"] for c in comps):
            ext.append({"path": path, "attribute": "x:ShearX", "curve": comun.claves_hold(fr, [c["ShearX"] for c in comps])})
        ops = [p["opacidad"] for p in rec]
        if any(o != 1.0 for o in ops):
            ext.append({"path": path, "attribute": "x:Opacity", "curve": comun.claves_hold(fr, ops)})
        ext.append({"path": path, "attribute": "x:Order", "curve": comun.claves_hold(fr, [p["orden"] for p in rec])})
        ext.append({"path": path, "attribute": "x:Z", "curve": comun.claves_hold(fr, [p["z"] for p in rec])})
        ids = [reg(p["dibujo"]) for p in rec]
        expo.append({"path": path, "level": d["id"], "runs": comun.runs(fr, ids)})
        extras = []
        for p in rec:
            e = {kk: p[kk] for kk in ("capas", "recorte", "razon", "orden_lista", "avisos") if kk in p}
            for c in e.get("recorte", []):
                for mm in c.get("mattes", []):
                    if mm.get("dibujo"): reg(mm["dibujo"])
            extras.append(e)
        side[k] = {"id": d["id"], "puertos": d["puertos"], "presente": comun.runs(fr, [True] * len(fr)), "extras": comun.runs(fr, extras)}
        nombres.append(k)

    # --- biblioteca
    lib = out / "biblioteca" / "rigs" / rid; dd = lib / "drawings"; dd.mkdir(parents=True, exist_ok=True)
    tvg = _indice_tvg(esc); fuentes = {}
    for did, arch in sorted(dib.items()):
        src = work / "dibujos" / arch
        if not src.is_file():
            fuentes[did] = {"archivo": arch, "aviso": "svg no encontrado en el horneado"}; continue
        shutil.copyfile(src, dd / arch)
        base, defo = (did.split("__def_", 1) + [None])[:2] if "__def_" in did else (did, None)
        t = tvg.get(base)
        fuentes[did] = {"archivo": arch, "sha256_svg": _sha(src), "derivado_de": base if defo else None, "deformador": defo,
                        "tvg": (str(t.relative_to(esc)).replace("\\", "/") if t else None), "sha256_tvg": (_sha(t) if t else None)}
    json.dump({"escena": xs, "nota": "SVG = cache derivado; el .tvg es la fuente (solo lectura)", "dibujos": fuentes},
              open(lib / "fuentes.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    ident = {"position": [0.0, 0.0], "pivot": [0.0, 0.0], "rotation": 0.0, "scale": [1.0, 1.0], "shear": [0.0, 0.0]}
    nodes = [{"name": "mundo", "transform": ident, "parent": None, "children": list(range(1, len(nombres)))}]
    slots = []
    for i, k in enumerate(nombres[1:], 1):
        nodes.append({"name": k, "transform": ident, "parent": 0, "children": []})
        r0 = P[k]["rec"][0]
        slots.append({"name": k, "parent_peg": i, "z_order": int(r0["orden"]), "visible": True,
                      "attachment": {"VectorShape": {"shape_id": Path(r0["dibujo"]).stem}}})
    json.dump({"id": rid, "version": "1", "rig": {"nodes": nodes}, "slots": slots},
              open(lib / "definition.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    # --- plano
    pl = out / "plano"; (pl / "anim").mkdir(parents=True, exist_ok=True)
    j0 = J[frames[0]]
    escena = {"timing": {"frames": len(frames), "frame_start": f0, "frame_start_global": f0, "fps": 24.0},
              "camera": ident, "background": None,
              "props": [{"name": "escena", "definition_id": rid, "definition_version": "1", "placement": ident, "z": 0.0}],
              "characters": [], "overlays": [], "library": {"path": "../biblioteca"},
              "x-harmony": {"escena": xs, "camara": j0["camara"], "tamano": j0["tamano"], "unidades": "campos Harmony 4:3 (matriz mundo 2x3)",
                            "fps_supuesto": True}}
    json.dump(escena, open(pl / "scene.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump({"channels": canales, "extension_channels": ext, "exposure": expo},
              open(pl / "anim" / "escena.anim.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump({"version": 1, "version_escena_json": j0["version"], "dibujos": dib, "piezas": side,
               "cuadros": {str(f): {"avisos": J[f]["avisos"], "apilado": J[f]["apilado"]} for f in frames}},
              open(pl / "anim" / "escena.x-harmony.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    (out / "LEEME.md").write_text(LEEME.format(escena=xs, f0=f0, f1=f1, n=len(frames), rid=rid), encoding="utf-8")
    return {"plano": str(pl), "biblioteca": str(lib), "pegs": len(nombres) - 1, "dibujos": len(dib), "canales": len(canales),
            "bytes_anim": (pl / "anim" / "escena.anim.json").stat().st_size, "bytes_sidecar": (pl / "anim" / "escena.x-harmony.json").stat().st_size}
