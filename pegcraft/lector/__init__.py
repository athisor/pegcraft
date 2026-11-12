"""Lector de escenas Harmony (.xstage) de sala limpia.

Núcleo: ``abrir``, ``Escena``, modelo y resumen. La evaluación (``Evaluador``) se exporta si existe.
Procedencia de cada regla: ``docs/lector/PROCEDENCIA.md``.
"""
from __future__ import annotations

from .escena import Escena, abrir, xstage_de
from .modelo import Backdrop, Cable, Elemento, Nodo
from .resumen import buscar, dibujos_de_reads, resumen

__all__ = [
    "Escena", "abrir", "xstage_de", "Nodo", "Cable", "Backdrop", "Elemento",
    "resumen", "dibujos_de_reads", "buscar",
]

try:  # evaluación
    from .evaluar import Evaluador  # noqa: F401
    __all__.append("Evaluador")
except ImportError:
    pass

try:
    from .dibujos import DibujoRef  # noqa: F401
    __all__.append("DibujoRef")
except ImportError:
    pass
