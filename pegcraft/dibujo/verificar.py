"""Comprobacion de ida y vuelta del modelo de dibujo sobre archivos .tvg (solo los lee).

Por cada dibujo:
  validar      el dibujo esta bien formado
  json         dibujo -> modelo del lector -> dibujo : igual
  svg          dibujo -> SVG -> dibujo : igual
  apariencia   la apariencia resuelta del SVG nuevo es, caracter a caracter, la que `sightread.tvg.a_svg` da para el .tvg
"""
import os
import random

from . import modelo as M
from . import svg as S


def uno(datos, ruta=None):
    """bytes de un .tvg -> (fallos: [str], cifras: dict)."""
    from sightread.tvg import a_svg as resolver, decodificar
    d = M.desde_tvg(datos, ruta)
    fallos = []
    if M.validar(d):
        fallos.append("validar")
    m2 = M.a_modelo_lector(d)
    if M.canonico(M.nucleo(M.desde_lector(m2))) != M.canonico(M.nucleo(d)):
        fallos.append("json")
    texto = S.a_svg(d)
    if M.canonico(S.desde_svg(texto)) != M.canonico(d):
        fallos.append("svg")
    viejo = resolver(decodificar(bytes(datos)))
    if resolver(m2) != viejo:
        fallos.append("apariencia")
    trazos = [s for a in d["arts"] for capa in a["layers"] for s in capa["strokes"]]
    return fallos, {"trazos": len(trazos), "comparten_puntos": sum("geometry_of" in s for s in trazos),
                    "con_perfil": sum("profile" in s for s in trazos), "invisibles": sum(bool(s.get("invisible")) for s in trazos),
                    "puntos_fuera_de_patron": texto.count(S.PREFIJO + ":points="), "f64": int(S.PREFIJO + ':precision="f64"' in texto),
                    "bytes_svg_antes": len(viejo), "bytes_svg_ahora": len(texto), "opacos": d["opaque"]}


def rutas_de(entrada, tope=0, semilla=7):
    if os.path.isfile(entrada):
        return [entrada]
    rutas = [os.path.join(d, f) for d, _ds, fs in os.walk(entrada) for f in fs if f.lower().endswith(".tvg")]
    if tope and len(rutas) > tope:
        rutas = random.Random(semilla).sample(rutas, tope)
    return rutas


def verificar(entrada, tope=0):
    """Archivo .tvg o carpeta -> resumen {dibujos, bien, fallos: {clase: n}, ilegibles, cifras sumadas, opacos: {que: n}, ejemplos}."""
    from sightread.tvg import TvgIlegible
    res = {"dibujos": 0, "bien": 0, "ilegibles": 0, "fallos": {}, "opacos": {}, "ejemplos": {}}
    suma = {}
    for ruta in rutas_de(entrada, tope):
        with open(ruta, "rb") as fh:
            datos = fh.read()
        res["dibujos"] += 1
        try:
            fallos, c = uno(datos)
        except TvgIlegible:
            res["ilegibles"] += 1
            continue
        except Exception as e:      # un fallo del modelo no debe cortar el lote: se cuenta y se sigue
            fallos, c = ["error: " + type(e).__name__], {}
        for k, v in c.items():
            if isinstance(v, int):
                suma[k] = suma.get(k, 0) + v
        for o in c.get("opacos", []):
            res["opacos"][o] = res["opacos"].get(o, 0) + 1
        if not fallos:
            res["bien"] += 1
        for f in fallos:
            res["fallos"][f] = res["fallos"].get(f, 0) + 1
            res["ejemplos"].setdefault(f, [])
            if len(res["ejemplos"][f]) < 3:
                res["ejemplos"][f].append(ruta)
    res.update(suma)
    return res
