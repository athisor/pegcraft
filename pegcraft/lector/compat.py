"""Adaptador mínimo entre el horneado de pegcraft y el lector : ahorra repetir ``abrir`` + ``Evaluador`` en cada módulo.

Solo da, por ruta de ``.xstage``,
  - ``escena(xs)``            la ``Escena`` (caché de 2 por ruta+mtime, del propio ``abrir``),
  - ``evaluador(xs)``         un ``Evaluador`` (modo de compatibilidad «paridad») que se REUTILIZA mientras la ``Escena`` siga abierta: así sus cachés de
                              especificación y de cadena sirven a los ~120 fotogramas de un horneado,
  - ``nodos_evaluados(xs, f)`` las filas de ``Evaluador.nodos(f)`` de los READ con dibujo (tope 2000, como hacía el horneado),
  - ``dibujos_de_reads(xs)``   ruta normalizada -> (elemento, carpeta) de cada READ (tope 500, como hacía el horneado),
  - ``n_fotogramas(xs)``.
Solo lectura. Un horneado usa un proceso por escena: el ``Evaluador`` guarda estado por fotograma y no es seguro entre hilos.
"""
from __future__ import annotations

from collections import OrderedDict

from .escena import Escena, abrir, xstage_de
from .evaluar import Evaluador
from .resumen import dibujos_de_reads as _dibujos_de_reads

__all__ = ["escena", "evaluador", "nodos_evaluados", "fila_peg", "dibujos_de_reads", "n_fotogramas", "norm", "xstage_de"]

MAX_NODOS = 2000      # tope de READ evaluados por fotograma (el que usaba el horneado)
MAX_READS = 500       # tope de READ con elemento (el que usaba el horneado)

_EVALUADORES: "OrderedDict[tuple[int, str], tuple[Escena, Evaluador]]" = OrderedDict()


def norm(ruta: str) -> str:
    """``G/N`` o ``/G/N`` -> ``Top/G/N`` (las rutas del lector ya llevan ``Top/``)."""
    r = str(ruta).lstrip("/")
    return r if r.startswith("Top/") or r == "Top" else "Top/" + r


def escena(xs) -> Escena:
    return abrir(xs)


def evaluador(xs, modo: str = "paridad") -> Evaluador:
    e = abrir(xs)
    clave = (id(e), modo)
    hit = _EVALUADORES.get(clave)
    if hit is not None and hit[0] is e:           # la Escena se guarda en el valor: su id no se reutiliza mientras esté aquí
        _EVALUADORES.move_to_end(clave)
        return hit[1]
    ev = Evaluador(e, modo=modo)
    _EVALUADORES[clave] = (e, ev)
    while len(_EVALUADORES) > 2:
        _EVALUADORES.popitem(last=False)
    return ev


DECIMALES_PEG = 5     # regla propia: el volcado de PEG se redondea a 5 decimales (A6-02, convención de compatibilidad); ver fila_peg


def nodos_evaluados(xs, fotograma: int, max: int | None = MAX_NODOS) -> list[dict]:
    """READ con dibujo expuesto en ``fotograma``: filas de ``Evaluador.nodos`` (ruta, tipo, padre, apagado, dibujable, matriz, z, dibujo, avisos).
    La ``z`` es la exacta; el apilado la compara con tolerancia (``apilado.TOL_Z``)."""
    return evaluador(xs).nodos(fotograma, tipos=("READ",), solo_con_dibujo=True, max=max)


def fila_peg(xs, peg: str, fotograma: int) -> dict:
    """Canales de un PEG en ``fotograma`` (``Evaluador.volcar_peg``) redondeados a 5 decimales (A6-02: así un PEG de camara
    con 3e-7 de ruido sigue contando como identidad)."""
    fila = evaluador(xs).volcar_peg(peg, fotograma, fotograma)[0]
    return {k: (round(v, DECIMALES_PEG) if isinstance(v, float) else v) for k, v in fila.items()}


def dibujos_de_reads(xs, max: int | None = MAX_READS) -> dict[str, tuple[str | None, str | None]]:
    """{ruta del READ: (nombre del elemento, carpeta en elements\\)}."""
    return {norm(r["ruta"]): (r["elemento"], r["carpeta"]) for r in _dibujos_de_reads(abrir(xs), max=max)}


def n_fotogramas(xs) -> int:
    return abrir(xs).n_fotogramas
