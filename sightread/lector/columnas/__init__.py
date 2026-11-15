"""Lectura de las columnas de una escena `.xstage` (tipos 0 exposición, 2 trayectoria 3D, 3 función Bézier; 1, 10 y desconocidos opacos).

Procedencia: tipos presentes en escenas reales P16; tipo 0 P18/P30; tipo 3 P17/P31-P35; tipo 2 P19/P34; opacas P36; una columna tipo 2 sin `path3D` (o sin
puntos) existe en escenas reales y se trata como opaca (A3-02); «nunca lanza» es una regla propia de robustez (A3-01, A4-08).

    cols = leer_columnas(escena_xml, metricas)       # perezoso: cada columna se construye al pedirla
    cols["Drawing"].dibujo(5)                        # ColExposicion -> (dibujo, id_elemento) | None
    cols["C_x"].valor(12.5)                          # ColFuncion -> float
    cols["C_pos"].posicion(12)                       # ColTrayectoria3D -> (x, y, z) en campos
Nunca lanza: lo raro se resuelve con el mejor valor y un aviso en `Columna.avisos`.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping

from .base import Columna, Metricas
from .exposicion import ColExposicion
from .funcion import ColFuncion
from .opaca import ColOpaca
from .trayectoria import ColTrayectoria3D

__all__ = ["leer_columnas", "Columna", "ColExposicion", "ColFuncion", "ColTrayectoria3D", "ColOpaca", "Columnas", "Metricas"]


class Columnas(Mapping):
    """Mapping nombre -> Columna, perezoso: guarda los `<column>` y construye cada objeto al pedirlo (queda en caché).
    `avisos`: avisos generales de la escena (nombres repetidos, columnas sin nombre)."""

    def __init__(self, elems: list[ET.Element], metricas: dict | None = None, elementos_validos: set[int] | None = None):
        self.avisos: list[str] = []
        self._metricas, self._avisos_metricas = Metricas.de_dict(metricas)
        self._validos = elementos_validos
        self._elems: dict[str, ET.Element] = {}
        for c in elems:
            n = c.get("name")
            if n is None:
                self.avisos.append("columna sin nombre ignorada")
                continue
            if n in self._elems:
                self.avisos.append(f"nombre de columna repetido (gana la última): {n}")
            self._elems[n] = c
        self._cache: dict[str, Columna] = {}

    def __len__(self) -> int:
        return len(self._elems)

    def __iter__(self):
        return iter(self._elems)

    def __contains__(self, nombre) -> bool:
        return nombre in self._elems

    def __getitem__(self, nombre: str) -> Columna:
        col = self._cache.get(nombre)
        if col is None:
            col = self._cache[nombre] = self._construir(nombre, self._elems[nombre])   # KeyError si no existe (contrato de Mapping)
        return col

    def _construir(self, nombre: str, c: ET.Element) -> Columna:
        try:
            tipo = int(c.get("type"))
        except (TypeError, ValueError):
            tipo = -1
        try:
            if tipo == 0:
                return ColExposicion(nombre, tipo, c, self._validos)      # P18, P30
            if tipo == 3:
                return ColFuncion(nombre, tipo, c)                        # P17, P31-P33
            if tipo == 2:                                                 # P19, P34
                if c.find("path3D") is None:                              # A3-02
                    return ColOpaca(nombre, tipo, c, "columna tipo 2 sin path3D: no se evalúa")
                col = ColTrayectoria3D(nombre, tipo, c, self._metricas)
                for a in self._avisos_metricas:
                    col.aviso(a)
                return col
        except Exception as e:  # noqa: BLE001 - nunca lanza (A3-01, A4-08)
            return ColOpaca(nombre, tipo, c, f"no se pudo construir la columna ({type(e).__name__}: {e})")
        return ColOpaca(nombre, tipo, c)                                  # P36: sonido (1), script (10) y desconocidas


def _columnas_de(escena_xml: ET.Element) -> list[ET.Element]:
    cols = escena_xml if escena_xml.tag == "columns" else escena_xml.find("columns")
    if cols is None:
        cols = escena_xml.find(".//columns")
    if cols is None:
        return []
    directas = [c for c in cols if c.tag == "column"]
    return directas if directas else list(cols.iter("column"))


def leer_columnas(escena_xml: ET.Element, metricas: dict | None = None, elementos_validos=None) -> Columnas:
    """Columnas de una escena. `escena_xml`: el `<scene>` (o un ancestro: se busca `columns`). `metricas`: dict de `Escena.metricas`
    (unitAspectRatioX/Y, numberOfUnitsX/Y/Z; faltantes = 4:3, 24x24x12).
    `elementos_validos` (opcional): ids de `<element>` existentes; un `elementSeq` con otro id se ignora (P30). Si no se da y `escena_xml` es el
    `<project>`/ancestro con `<elements>`, se toman de ahí; si no, no se valida."""
    if elementos_validos is None:
        try:
            ids = {int(e.get("id")) for cont in escena_xml.iter("elements") for e in cont.findall("element") if e.get("id") is not None}
            elementos_validos = ids or None
        except (TypeError, ValueError):
            elementos_validos = None
    else:
        elementos_validos = set(elementos_validos)
    return Columnas(_columnas_de(escena_xml), metricas, elementos_validos)
