"""esquema.py: que entra a la deformacion de un READ en un fotograma, como JSON.

Replica, SIN tocar bake/, las llamadas que hace hornear() para armar los deformadores (censo -> segmentos -> pre_matrices -> aspecto/camara):
  spec = {"version": 1, "read": ruta, "fotograma": f, "A": 4/3, "div": 156.25,
          "segmentos": [ {"pegs": [rutas PEG intermedios], "pre": [[a,b,tx],[c,d,ty]] | null,   # campos-Y isotropos, PEG + matriz propia del READ (1er seg.)
                          "nodos": [ {"ruta", "tipo": OffsetModule|CurveModule, "closepath", "cinematico"?,
                                      "reposo": {offset/x, offset/y[, length0, orientation0, length1, orientation1]},
                                      "pose":   {mismas claves} } ... ]  # raiz -> punta
                        } ... ]}                                           # del segmento mas cercano al READ al mas lejano
`reposo` es constante por rig; `pose` y `pre` cambian por cuadro. Solo se guardan los segmentos ACTIVOS (fuera de reposo) como hace hornear.
"""
import os, re, json, sys
import numpy as np
sys.dont_write_bytecode = True

VERSION = 1


def extraer(xs, f, patron="."):
    """{ruta_read: spec} de los READ con algun deformador activo en el fotograma f. Mismo orden de llamadas que bake/hornear.py."""
    from ..bake import deformadores as D, censo as C, matriz_causal as mc
    from sightread.lector import compat as L
    xs = str(xs)
    cen = C.censo(xs, f, patron)
    A = mc.aspecto(L.escena(xs))
    div = mc.camara(xs)["div"]
    segs = {r: D.segmentos(cad) for r, cad in cen.items()}
    segs = {r: sg for r, sg in segs.items() if sg}
    pre = mc.pre_matrices(xs, f, {r: [x["pegs"] for x in sg] for r, sg in segs.items()}) if (segs and D.PRE) else {}
    out = {}
    for r, sg in segs.items():
        ss = []
        for k, s in enumerate(sg):
            nodos = []
            for n in s["nodos"]:
                nd = {"ruta": n["ruta"], "tipo": n["tipo"], "reposo": dict(n["rep"]), "pose": dict(n["act"])}
                if n.get("closepath") is not None:
                    nd["closepath"] = n["closepath"]
                if n.get("cinematico"):
                    nd["cinematico"] = True
                nodos.append(nd)
            m = pre[r][k] if r in pre else None
            ss.append({"pegs": list(s["pegs"]), "pre": None if m is None else np.asarray(m, float)[:2].tolist(), "nodos": nodos})
        out[r] = {"version": VERSION, "read": r, "fotograma": f, "A": A, "div": div, "segmentos": ss}
    return out


def raiz_pose(spec):
    """Parte que cambia por cuadro (pose + pre) en forma compacta: lista plana de floats. Sirve para medir bytes (float32 = 4 B/valor)."""
    v = []
    for s in spec["segmentos"]:
        if s["pre"] is not None:
            v.extend(np.asarray(s["pre"], float).ravel().tolist())
        for n in s["nodos"]:
            v.extend(n["pose"][k] or 0.0 for k in sorted(n["pose"]))
    return v


def raiz_reposo(spec):
    v = []
    for s in spec["segmentos"]:
        for n in s["nodos"]:
            v.extend(n["reposo"][k] or 0.0 for k in sorted(n["reposo"]))
    return v


def piezas_deformadas(escena_json):
    """Del escena.json aplastado de hornear: {ruta_read: (dibujo_deformado_rel, dibujo_reposo_rel)} para piezas y mattes de recorte.
    El nombre aplastado es '<stem>__def_<hoja de la ruta>.svg' (bake/hornear.py); el de reposo, '<stem>.svg'."""
    with open(escena_json, encoding="utf-8") as fh:
        e = json.load(fh)
    res = {}

    def reg(i, d):
        m = re.match(r"^(.*)__def_[^/\\]*\.svg$", d)
        if m:
            res[i] = (d, m.group(1) + ".svg")
    for p in e["piezas"]:
        reg(p["id"], p["dibujo"])
        for c in p.get("recorte", []):
            for mt in c.get("mattes", []):
                reg(mt["id"], mt["dibujo"])
    return res


def guardar(specs, ruta):
    json.dump(specs, open(ruta, "w", encoding="utf-8"), separators=(",", ":"))
