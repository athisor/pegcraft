"""Fotogramas clave de una escena: aquellos donde cambia el conjunto de dibujos expuestos de los READ (ex scripts/explorar.py,
que tenia el rango 1..115 y la escena PLANO fijos). Solo lectura (sightread.lector: Evaluador.nodos)."""
from sightread.lector import compat as L


def keyframes(xstage, desde=1, hasta=None, patron=None):
    """-> [(fotograma, n_dibujos_expuestos)] en cada cambio. hasta=None: ultimo fotograma de la escena (scene@nbframes)."""
    import re
    if hasta is None:
        hasta = int(L.n_fotogramas(xstage) or 0) or desde
    rx = re.compile(patron, re.I) if patron else None
    prev, cambios = None, []
    for f in range(desde, hasta + 1):
        nodos = L.nodos_evaluados(str(xstage), f)
        d = {n["ruta"]: n["dibujo"] for n in nodos if not n["apagado"] and (rx is None or rx.search(n["ruta"]))}
        if d != prev:
            cambios.append((f, len(d))); prev = d
    return cambios
