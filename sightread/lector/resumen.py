"""Resumen y búsquedas sobre una escena (sin evaluar columnas)."""
from __future__ import annotations

import re
from collections import Counter

from .escena import Escena
from .tipos import RAIZ, TIPO_COMPOSITE, TIPO_GRUPO, TIPO_READ

__all__ = ["resumen", "dibujos_de_reads", "buscar"]


def _descendientes(e: Escena, grupo: str) -> list[str]:
    """Todos los nodos bajo un grupo (cualquier profundidad), en preorden."""
    out: list[str] = []
    pila = list(reversed(e.hijos(grupo)))
    while pila:
        r = pila.pop()
        out.append(r)
        if e.nodos[r].tipo == TIPO_GRUPO:
            pila.extend(reversed(e.hijos(r)))
    return out


def resumen(e: Escena) -> dict:
    """Resumen de la escena: nodos por tipo, grupos de primer nivel, elementos, fotogramas, apagados."""
    por_tipo = Counter(n.tipo for n in e.nodos.values())
    grupos = []
    for r in e.hijos(RAIZ):
        if e.nodos[r].tipo != TIPO_GRUPO:
            continue
        desc = _descendientes(e, r)
        grupos.append({
            "nodos": len(desc),
            "reads": sum(1 for d in desc if e.nodos[d].tipo == TIPO_READ),
            "ruta": r,
        })
    return {
        "escena": str(e.ruta),
        "formato": "harmony_native",
        "nodos": len(e.nodos),
        "por_tipo": dict(sorted(por_tipo.items())),
        "grupos": grupos,
        "elementos": len(e.elementos),
        "columnas_de_dibujo": e.n_columnas_de_dibujo(),
        "fotogramas": e.n_fotogramas,
        "apagados": sum(1 for n in e.nodos.values() if n.apagado),
        # regla de paridad (A2-03): cuenta todo tipo que contenga COMPOSITE (incluye DeformationCompositeModule)
        "composites": sum(c for t, c in por_tipo.items() if TIPO_COMPOSITE in t.upper()),
        "backdrops": len(e.backdrops),
        "avisos": list(e.avisos),
    }


def dibujos_de_reads(e: Escena, max: int | None = None) -> list[dict]:
    """Por cada READ: su columna de dibujo, el elemento al que apunta y los dibujos del elemento (P18, P20)."""
    out: list[dict] = []
    for n in e.nodos.values():
        if n.tipo != TIPO_READ:
            continue
        if max is not None and len(out) >= max:
            break
        ce = e.atributo_elem(n.ruta, "drawing", "element")
        col = ce.get("col") if ce is not None else None
        el = e.elemento_de_columna(col)
        out.append({
            "ruta": n.ruta,
            "tipo": n.tipo,
            "apagado": n.apagado,
            "columna": col,
            "elemento": el.nombre if el else None,
            "carpeta": el.carpeta if el else None,
            "n_dibujos": len(el.dibujos) if el else 0,
            "dibujos": list(el.dibujos) if el else [],
        })
    return out


def buscar(e: Escena, tipos=None, apagados: bool = True, texto: str | None = None,
           max: int | None = None) -> list[dict]:
    """Busca nodos por tipo y/o texto (regex sin distinguir mayúsculas contra nombre y ruta).

    ``apagados=False`` excluye los que tienen la bandera propia de apagado.
    """
    if isinstance(tipos, str):
        tipos = (tipos,)
    tset = set(tipos) if tipos else None
    rx = None
    if texto:
        try:
            rx = re.compile(texto, re.IGNORECASE)
        except re.error:
            rx = re.compile(re.escape(texto), re.IGNORECASE)
    out: list[dict] = []
    for n in e.nodos.values():
        if tset is not None and n.tipo not in tset:
            continue
        if not apagados and n.apagado:
            continue
        if rx is not None and not (rx.search(n.nombre) or rx.search(n.ruta)):
            continue
        out.append({"ruta": n.ruta, "tipo": n.tipo, "entradas": bool(e.puertos_composite(n.ruta))})
        if max is not None and len(out) >= max:
            break
    return out
