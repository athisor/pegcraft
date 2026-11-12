"""Columnas sin evaluación: sonido (tipo 1), script (tipo 10) y cualquier tipo desconocido. Se conservan con su nombre, tipo y elemento XML.
Procedencia: los tipos 1 (sonido) y 10 (script / controlador) existen en escenas reales y no se evalúan (P36); una columna tipo 2 sin trayectoria también
queda opaca (A3-02)."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from .base import Columna

TIPOS_CONOCIDOS_OPACOS = {1: "sonido", 10: "script"}


class ColOpaca(Columna):
    """Columna que el lector no evalúa. `evaluar(f)` devuelve None."""

    def __init__(self, nombre: str, tipo: int, elem: ET.Element, motivo: str | None = None):
        super().__init__(nombre, tipo, elem)
        if motivo:
            self.aviso(motivo)
        elif tipo not in TIPOS_CONOCIDOS_OPACOS:
            self.aviso(f"tipo de columna desconocido: {tipo}")
