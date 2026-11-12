"""escena.py: escena.json con los SVG deformados REGENERADOS desde (SVG en reposo + parametros), y su costo.

Parte de un escena.json ya horneado (bake/hornear.py, que fija piezas, apilado, matrices y recortes) y cambia solo los dibujos
deformados: en vez de leer `dibujos/<stem>__def_<hoja>.svg` (aplastado), toma `dibujos/<stem>.svg` (reposo) + spec y deforma.
"""
import json, time, sys, hashlib
from pathlib import Path
sys.dont_write_bytecode = True
from . import evaluador as EV, esquema as ES


def armar(base_json, specs, salida, var=None, plantillas=None, ajustar=None):
    """base_json: escena.json aplastado. specs: {ruta: spec}. salida: carpeta. ajustar(spec)->spec opcional (ablaciones).
    plantillas: dict reutilizable {ruta_svg_reposo: Plantilla} (la fase de parseo se paga una vez por dibujo).
    Devuelve (ruta escena.json, info) con tiempos: t_plantilla (parseo, una vez), t_deformar (puntos), t_emitir (texto)."""
    base_json = Path(base_json); base = base_json.parent; out = Path(salida); (out / "dibujos").mkdir(parents=True, exist_ok=True)
    e = json.load(open(base_json, encoding="utf-8"))
    plantillas = {} if plantillas is None else plantillas
    mapa = ES.piezas_deformadas(base_json)
    info = {"piezas_deformadas": 0, "puntos": 0, "t_plantilla": 0.0, "t_deformar": 0.0, "t_emitir": 0.0, "bytes_param": 0, "por_pieza": {}}
    hechos = {}

    def resolver(i, d):
        if i in mapa and i in specs:
            if i in hechos:
                return hechos[i]
            rep = str(base / mapa[i][1])
            if rep not in plantillas:
                t0 = time.perf_counter()
                plantillas[rep] = EV.Plantilla(open(rep, encoding="utf-8").read())
                info["t_plantilla"] += time.perf_counter() - t0
            sp = specs[i] if ajustar is None else ajustar(specs[i])
            t0 = time.perf_counter()
            Q = EV.deformar_puntos(plantillas[rep], sp, var)
            t1 = time.perf_counter()
            svg = plantillas[rep].emitir(Q)
            t2 = time.perf_counter()
            dest = out / "dibujos" / Path(mapa[i][0]).name
            dest.write_text(svg, encoding="utf-8")
            info["piezas_deformadas"] += 1; info["puntos"] += plantillas[rep].n_puntos
            info["t_deformar"] += t1 - t0; info["t_emitir"] += t2 - t1
            info["por_pieza"][i] = {"puntos": plantillas[rep].n_puntos, "t_deformar_ms": round((t1 - t0) * 1000, 2), "bytes_svg_def": len(svg.encode("utf-8"))}
            hechos[i] = str(dest)
            return hechos[i]
        return str((base / d).resolve())

    for p in e["piezas"]:
        p["dibujo"] = resolver(p["id"], p["dibujo"])
        for c in p.get("recorte", []):
            for mt in c.get("mattes", []):
                mt["dibujo"] = resolver(mt["id"], mt["dibujo"])
    ruta = out / "escena.json"
    json.dump(e, open(ruta, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return str(ruta), info


def hash_archivo(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
