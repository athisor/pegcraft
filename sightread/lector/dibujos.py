"""Dibujo visible de un READ en un fotograma (R11).

Cadena de resolución: ``attrs/drawing/element@col`` -> columna de exposición -> (nombre del dibujo, id de elemento)
-> ``<element>`` por id (P18, P20, P30). Solo biblioteca estándar; solo lectura.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DibujoRef", "dibujo_de"]


@dataclass(slots=True, frozen=True)
class DibujoRef:
    """Dibujo expuesto: ``ruta_relativa`` = ``elements/<carpeta>/<carpeta>-<dibujo>.tvg``."""
    elemento_id: int
    elemento: str
    carpeta: str
    dibujo: str
    ruta_relativa: str


def dibujo_de(escena, ruta, f) -> DibujoRef | None:
    """Dibujo del READ ``ruta`` en el fotograma ``f``; ``None`` si no hay columna, celda vacía o elemento inexistente."""
    el = escena.atributo_elem(ruta, "drawing", "element")
    if el is None:
        return None
    nombre_col = el.get("col")
    if not nombre_col:
        return None
    try:
        col = escena.columnas[nombre_col]
    except KeyError:
        return None
    fn = getattr(col, "dibujo", None)
    if fn is None:
        return None
    r = fn(f)
    if not r:
        return None
    dib, eid = r
    elem = escena.elementos.get(eid)
    if elem is None:
        return None
    carpeta = elem.carpeta or elem.nombre
    return DibujoRef(int(eid), elem.nombre, carpeta, str(dib), f"elements/{carpeta}/{carpeta}-{dib}.tvg")
