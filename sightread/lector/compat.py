"""Adaptador mínimo entre el horneado de pegcraft y el lector : ahorra repetir ``abrir`` + ``Evaluador`` en cada módulo.

Solo da, por ruta de ``.xstage``,
  - ``escena(xs)``            la ``Escena`` (caché de 2 por ruta+mtime, del propio ``abrir``),
  - ``evaluador(xs)``         un ``Evaluador`` (modo de compatibilidad «paridad») que se REUTILIZA mientras la ``Escena`` siga abierta: así sus cachés de
                              especificación y de cadena sirven a los ~120 fotogramas de un horneado,
  - ``nodos_evaluados(xs, f)`` las filas de ``Evaluador.nodos(f)`` de los READ con dibujo (SIN tope por omisión),
  - ``dibujos_de_reads(xs)``   ruta normalizada -> (elemento, carpeta) de cada READ (SIN tope por omisión),
  - ``n_fotogramas(xs)``.
Solo lectura. Un horneado usa un proceso por escena: el ``Evaluador`` guarda estado por fotograma y no es seguro entre hilos.
"""
from __future__ import annotations

from collections import OrderedDict

from .escena import Escena, abrir, xstage_de
from .evaluar import Evaluador
from .resumen import dibujos_de_reads as _dibujos_de_reads

__all__ = ["escena", "evaluador", "nodos_evaluados", "fila_peg", "dibujos_de_reads", "n_fotogramas", "norm", "xstage_de"]

# Sin topes: el horneado pedía 2000 nodos / 500 READ y las escenas con más de 500 READ perdían piezas EN SILENCIO (plano A, 778 READ:
# 0,257 -> 0,984 al quitarlos; ver docs/PROCEDENCIA.md, A8-01). ``max`` sigue disponible para quien quiera acotar a propósito.
MAX_NODOS: int | None = None
MAX_READS: int | None = None

_EVALUADORES: "OrderedDict[tuple[int, str], tuple[Escena, Evaluador]]" = OrderedDict()


def norm(ruta: str) -> str:
    """``G/N`` o ``/G/N`` -> ``Top/G/N`` (las rutas del lector ya llevan ``Top/``)."""
    r = str(ruta).lstrip("/")
    return r if r.startswith("Top/") or r == "Top" else "Top/" + r


def escena(xs) -> Escena:
    return abrir(xs)


def evaluador(xs, modo: str = "paridad", peg_apagado: str | None = None) -> Evaluador:
    """``peg_apagado``: ``"identidad"`` | ``"cuenta"`` | ``None`` (= el del modo: ``cuenta`` en paridad); ver ``Evaluador`` (A8-02)."""
    e = abrir(xs)
    clave = (id(e), modo, peg_apagado)
    hit = _EVALUADORES.get(clave)
    if hit is not None and hit[0] is e:           # la Escena se guarda en el valor: su id no se reutiliza mientras esté aquí
        _EVALUADORES.move_to_end(clave)
        return hit[1]
    ev = Evaluador(e, modo=modo, peg_apagado=peg_apagado)
    _EVALUADORES[clave] = (e, ev)
    while len(_EVALUADORES) > 4:
        _EVALUADORES.popitem(last=False)
    return ev


DECIMALES_PEG = 5     # regla propia: el volcado de PEG se redondea a 5 decimales (A6-02, convención de compatibilidad); ver fila_peg


def nodos_evaluados(xs, fotograma: int, max: int | None = MAX_NODOS, peg_apagado: str | None = None) -> list[dict]:
    """READ con dibujo expuesto en ``fotograma``: filas de ``Evaluador.nodos`` (ruta, tipo, padre, apagado, dibujable, matriz, z, dibujo, avisos).
    La ``z`` es la exacta; quien apila debe compararla con tolerancia (en pegcraft, ``apilado.TOL_Z``, que no vive aquí).
    ``peg_apagado="identidad"`` aplica la regla medida (el PEG apagado no transforma ni suma Z) sin activar el modo ``harmony``."""
    return evaluador(xs, peg_apagado=peg_apagado).nodos(fotograma, tipos=("READ",), solo_con_dibujo=True, max=max)


def fila_peg(xs, peg: str, fotograma: int, peg_apagado: str | None = None) -> dict:
    """Canales de un PEG en ``fotograma`` (``Evaluador.volcar_peg``) redondeados a 5 decimales (A6-02: así un PEG de camara
    con 3e-7 de ruido sigue contando como identidad). Con ``peg_apagado="identidad"`` un PEG apagado (también el de cámara) da la identidad."""
    fila = evaluador(xs, peg_apagado=peg_apagado).volcar_peg(peg, fotograma, fotograma)[0]
    return {k: (round(v, DECIMALES_PEG) if isinstance(v, float) else v) for k, v in fila.items()}


def dibujos_de_reads(xs, max: int | None = MAX_READS) -> dict[str, tuple[str | None, str | None]]:
    """{ruta del READ: (nombre del elemento, carpeta en elements\\)}."""
    return {norm(r["ruta"]): (r["elemento"], r["carpeta"]) for r in _dibujos_de_reads(abrir(xs), max=max)}


def n_fotogramas(xs) -> int:
    return abrir(xs).n_fotogramas
