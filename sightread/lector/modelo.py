"""Modelo de datos de una escena. Solo contenedores; la lógica está en escena.py."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

__all__ = ["Nodo", "Cable", "Backdrop", "Elemento"]


@dataclass(slots=True)
class Nodo:
    """Un módulo o un grupo. ``ruta`` lleva siempre el prefijo ``Top/``."""
    ruta: str
    nombre: str
    tipo: str                      # "GROUP" para <group>
    grupo: str                     # ruta del grupo contenedor ("Top" en la raíz)
    apagado: bool                  # bandera propia options/disabled (P14); ver Escena.apagado_efectivo
    pos: tuple[float, ...]         # "x,y,n" tal cual (P07)
    publish_tab: str | None
    elem: ET.Element


@dataclass(slots=True)
class Cable:
    """Enlace literal del archivo (P09): rutas completas, puertos 0 si faltan."""
    grupo: str
    origen: str
    puerto_origen: int
    destino: str
    puerto_destino: int


@dataclass(slots=True)
class Backdrop:
    grupo: str
    titulo: str
    color: str
    rect: tuple[float, float, float, float]    # x1, y1, x2, y2 (esquina superior izquierda y la inferior derecha)
    nodos: list[str]                            # nodos del grupo cuya posición cae dentro del rectángulo


@dataclass(slots=True)
class Elemento:
    id: int
    nombre: str
    carpeta: str
    dibujos: tuple[str, ...]
