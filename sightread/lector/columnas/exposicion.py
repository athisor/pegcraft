"""Columnas de exposición de dibujos (`<column type="0">`: `elementSeq` / `heldSeq`).

Procedencia: P30 (medido en Harmony 24 como caja negra, 8 560 celdas sin diferencias). La columna es una REJILLA de celdas por fotograma; cada celda es
clave (K) o sostenida (H) y lleva (dibujo, elemento). Cada trozo de `exposures` (separado por comas) se escribe en la rejilla EN EL ORDEN DEL ARCHIVO.
Un archivo sin solapes da el resultado obvio: el dibujo de cada cuadro nombrado y nada en los demás (sin mantener hasta la entrada siguiente, sin dibujo
antes de la primera ni después de la última, sin corte en el número de fotogramas de la escena).

    col.dibujo(5)  -> ("2", 3) = (nombre del dibujo, id de elemento)  o  None
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from .base import Columna, MAX_EXPANSION, seguro

_TOKEN = re.compile(r"(\d+)(?:-(\d+))?")
CLAVE, SOST = "K", "H"


def parse_exposures(texto: str | None) -> list[tuple[int, int]]:
    """'1-4,7,9-10' -> [(1,4),(7,7),(9,10)]. Cada trozo se valida por separado y el inválido se ignora (solo dígitos: sin espacios, signo ni decimales).
    Si b<a vale solo a. (P30)"""
    res = []
    for tok in (texto or "").split(","):
        m = _TOKEN.fullmatch(tok)
        if not m:
            continue
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) is not None else a
        res.append((a, b if b >= a else a))
    return res


def _escribir(rej: dict, a: int, b: int, val, eid) -> None:
    """Escribe a-b con (val, eid) (P30): el cuadro a pasa a clave si no lo era (si ya lo era se respeta); a+1..b quedan sostenidos y la escritura se
    DETIENE si aparece una clave; si llegó hasta b se borran los sostenidos consecutivos que seguían a b."""
    if rej.get(a, (None,))[0] != CLAVE:
        rej[a] = (CLAVE, val, eid)
    for f in range(a + 1, b + 1):
        if rej.get(f, (None,))[0] == CLAVE:
            return
        rej[f] = (SOST, val, eid)
    f = b + 1
    while rej.get(f, (None,))[0] == SOST:
        del rej[f]
        f += 1


class ColExposicion(Columna):
    """Columna tipo 0. `elementos_validos`: ids de `<element>` que existen (None = no se valida)."""

    def __init__(self, nombre: str, tipo: int, elem: ET.Element, elementos_validos: set[int] | None = None):
        super().__init__(nombre, tipo, elem)
        self._rej: dict[int, tuple] = {}
        try:
            self._rej = self._construir(elem, elementos_validos)
        except Exception as e:  # noqa: BLE001 - nunca lanza
            self.aviso(f"exposición: no se pudo leer la columna ({type(e).__name__}: {e})")

    def _construir(self, el, validos):
        id_col = None
        try:
            id_col = int(el.get("id")) if el.get("id") not in (None, "") else None
        except ValueError:
            self.aviso(f"id de columna no numérico: {el.get('id')!r}")
        rej: dict[int, tuple] = {}
        for h in el:
            if h.tag not in ("elementSeq", "heldSeq"):
                continue
            if h.tag == "elementSeq":
                val = h.get("val")
                try:
                    eid = int(h.get("id")) if h.get("id") not in (None, "") else id_col
                except ValueError:
                    self.aviso(f"elementSeq con id no numérico ignorado: {h.get('id')!r}")
                    continue
                if val is None or val == "" or eid is None:
                    continue
                if validos is not None and eid not in validos:
                    self.aviso(f"elementSeq con elemento inexistente ignorado (id {eid})")
                    continue
            else:
                val, eid = None, None
            for a, b in parse_exposures(h.get("exposures")):
                if b - a >= MAX_EXPANSION:
                    self.aviso(f"exposición demasiado larga ignorada ({a}-{b})")
                    continue
                _escribir(rej, a, b, val, eid)
        return rej

    @seguro(None)
    def dibujo(self, f: float) -> tuple[str, int] | None:
        """Dibujo expuesto en el fotograma f: (nombre, id de elemento) o None. Los sostenidos de `heldSeq` no llevan dibujo."""
        if not math.isfinite(f):
            self.aviso(f"fotograma no finito: {f!r}")
            return None
        c = self._rej.get(math.floor(f))
        return (c[1], c[2]) if c is not None and c[1] is not None else None

    @seguro({"dibujo": None, "vacia": True, "sostenida": True})
    def celda(self, f: int) -> dict:
        """Estado de la celda: `vacia` = no hay celda; `sostenida` = es sostenida (sin celda, también si falta la celda anterior). (P30)"""
        f = math.floor(f)
        c = self._rej.get(f)
        sost = ((f - 1) not in self._rej) if c is None else c[0] == SOST
        return {"dibujo": self.dibujo(f), "vacia": c is None, "sostenida": sost}

    def evaluar(self, f: float):
        return self.dibujo(f)
