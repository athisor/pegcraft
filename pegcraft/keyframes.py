"""Fotogramas clave de una escena: aquellos donde cambia el conjunto de dibujos expuestos de los READ (ex scripts/explorar.py,
que tenia el rango 1..115 y la escena PLANO fijos). Solo lectura (lector_xstage.escena_evaluar)."""
from .bake import apilado


def keyframes(xstage, desde=1, hasta=None, patron=None):
    """-> [(fotograma, n_dibujos_expuestos)] en cada cambio. hasta=None: ultimo fotograma de la escena (escena_resumen)."""
    import re
    X = apilado.X
    if hasta is None:
        r = X.escena_resumen(str(xstage))
        hasta = int(r.get("fotogramas") or r.get("frames") or r.get("n_fotogramas") or 0) or desde
    rx = re.compile(patron, re.I) if patron else None
    prev, cambios = None, []
    for f in range(desde, hasta + 1):
        nodos = X.escena_evaluar(str(xstage), fotograma=f, tipos=["READ"], solo_con_dibujo=True, max=2000)["nodos"]
        d = {n["ruta"]: n["dibujo"] for n in nodos if not n["apagado"] and (rx is None or rx.search(n["ruta"]))}
        if d != prev:
            cambios.append((f, len(d))); prev = d
    return cambios
