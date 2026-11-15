"""`python -m pegcraft dibujo <entrada> [-o salida.svg] [--json salida.json] [--verificar [--tope N]]`

entrada: un .tvg, un .svg del modelo de dibujo o un .json del modelo. Con --verificar, un .tvg o una carpeta (solo lee):
comprueba la ida y vuelta y escribe el resumen en JSON por la salida estandar (codigo 1 si algo falla).
"""
import json
import sys
from pathlib import Path

from . import modelo as M
from . import svg as S


def main(a):
    if a.verificar:
        from . import verificar as V
        res = V.verificar(a.entrada, a.tope)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["bien"] + res["ilegibles"] == res["dibujos"] else 1
    p = Path(a.entrada)
    ext = p.suffix.lower()
    if ext == ".tvg":
        d = M.desde_tvg(p.read_bytes(), p.name)
    elif ext == ".svg":
        d = S.desde_svg(p.read_text(encoding="utf-8"))
    elif ext == ".json":
        d = json.loads(p.read_text(encoding="utf-8"))
    else:
        sys.exit("entrada: se espera .tvg, .svg o .json")
    errores = M.validar(d)
    if errores:
        sys.exit("el dibujo no esta bien formado:\n  " + "\n  ".join(errores[:20]))
    if a.svg:
        Path(a.svg).write_text(S.a_svg(d), encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    if not a.svg and not a.json:
        trazos = [s for x in d["arts"] for capa in x["layers"] for s in capa["strokes"]]
        print(json.dumps({"version": d["version"], "state": d["state"], "opaque": d["opaque"], "colores": len(d["palette"]),
                          "trazos": {x["name"]: sum(len(capa["strokes"]) for capa in x["layers"]) for x in d["arts"]},
                          "comparten_puntos": sum("geometry_of" in s for s in trazos), "con_perfil": sum("profile" in s for s in trazos)},
                         ensure_ascii=False, indent=1))
    return 0
