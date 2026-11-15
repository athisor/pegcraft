"""Log COMPARTIBLE: lo que un tercero puede mandarnos sin revelar su escena.

`<base>_compartible.json` lleva solo: categoria, clave (tipo de nodo, atributo, tipo de columna, modo de mezcla, tipo de excepcion...), cuantos hallazgos
(`n`) y en cuantas escenas (`escenas`), mas la version de pegcraft/sightread y la de Harmony que guardo cada escena (si el .xstage la trae). NUNCA lleva rutas,
nombres de escena, nodo, columna o elemento, ni el texto de una excepcion (el tipo si). Dos defensas:
  1. las claves de las categorias de texto libre pierden lo entrecomillado, y el mensaje de una excepcion no entra a ninguna clave (solo su tipo);
  2. cada clave se depura contra los nombres propios de la escena (`sensibles`: carpetas, archivo, nodos, columnas, elementos), que se reemplazan por `<nombre>`.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path

FORMATO = "pegcraft-compartible-1"
# categorias cuya clave sale de un aviso de texto libre: se les quita lo entrecomillado (valores sacados del archivo)
_LIBRES = frozenset({"escena_aviso", "columna_aviso", "aviso_otro", "plt_no_reconocido", "paleta_faltante", "apilado_aviso"})
_RX_COMILLAS = re.compile(r"'[^']*'|\"[^\"]*\"")
_RX_RUTA_O_UNIDAD = re.compile(r"[A-Za-z]:[\\/]|\\\\")


def versiones() -> dict:
    import sightread
    import pegcraft
    return {"pegcraft": getattr(pegcraft, "__version__", None), "sightread": getattr(sightread, "__version__", None)}


def depurar(categoria: str, clave: str, sensibles) -> str:
    """Clave segura para compartir."""
    from ..bake.apilado import TIPOS_MODELADOS
    t = str(clave)
    if categoria in _LIBRES:
        t = _RX_COMILLAS.sub("<texto>", t)
    toks = sorted({s for s in sensibles if len(s) >= 3 and not s.isdigit() and s not in TIPOS_MODELADOS}, key=len, reverse=True)
    if toks:
        rx = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(s) for s in toks) + r")(?![\w])")
        t = rx.sub("<nombre>", t)
    if _RX_RUTA_O_UNIDAD.search(t):
        t = _RX_RUTA_O_UNIDAD.sub("<ruta>", t)
    return t


class Compartible:
    """Acumula, escena a escena, los conteos por (categoria, clave segura)."""

    def __init__(self, entradas_n: int = 0):
        self.h: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])   # (cat, clave) -> [n, escenas]
        self.escenas = 0
        self.con_hallazgos = 0
        self.harmony: dict[str, int] = defaultdict(int)

    def agregar(self, info: dict, hallazgos: list[dict]) -> None:
        self.escenas += 1
        if info.get("harmony"):
            self.harmony[str(info["harmony"])] += 1
        if hallazgos:
            self.con_hallazgos += 1
        sens = info.get("sensibles") or []
        vistos = set()
        for h in hallazgos:
            k = (h["categoria"], depurar(h["categoria"], h["clave"], sens))
            self.h[k][0] += int(h.get("n", 1))
            if k not in vistos:
                vistos.add(k); self.h[k][1] += 1

    def a_dict(self) -> dict:
        filas = [{"categoria": c, "clave": k, "n": v[0], "escenas": v[1]} for (c, k), v in self.h.items()]
        filas.sort(key=lambda x: (-x["escenas"], -x["n"], x["categoria"], x["clave"]))
        return {"formato": FORMATO, **versiones(), "harmony": dict(sorted(self.harmony.items())),
                "escenas": self.escenas, "escenas_con_hallazgos": self.con_hallazgos, "hallazgos": filas}

    def escribir(self, ruta: Path) -> None:
        tmp = ruta.with_name(ruta.name + ".tmp")
        tmp.write_text(json.dumps(self.a_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, ruta)
