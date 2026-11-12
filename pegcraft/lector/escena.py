"""Escena de Harmony (.xstage): carga, grafo literal y grafo resuelto a través de grupos.

Solo biblioteca estándar. Solo lectura.
Fuentes de los hechos: identificadores de docs/lector/PROCEDENCIA.md, citados en los comentarios.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from pathlib import Path

from .modelo import Backdrop, Cable, Elemento, Nodo
from .tipos import (
    COLUMNA_EXPOSICION,
    METRICAS_POR_OMISION,
    PROFUNDIDAD_MAXIMA,
    RAIZ,
    TIPO_GRUPO,
    TIPO_MULTIPORT_IN,
    TIPO_MULTIPORT_OUT,
)
from .xml import leer_xml

try:  # las columnas son de otro módulo; sin él, un sustituto opaco local
    from .columnas import leer_columnas as _leer_columnas
except ImportError:  # pragma: no cover - depende de la rama
    _leer_columnas = None

__all__ = ["Escena", "abrir", "xstage_de", "limpiar_cache"]


# ---------------------------------------------------------------- sustituto local de columnas

class _ColOpacaLocal:
    """Columna sin evaluar (sustituto mientras no exista el paquete columnas)."""
    __slots__ = ("nombre", "tipo", "elem", "avisos")

    def __init__(self, nombre: str, tipo: int, elem: ET.Element):
        self.nombre, self.tipo, self.elem, self.avisos = nombre, tipo, elem, []


class _ColumnasLocal(Mapping):
    """Mapping perezoso nombre -> columna opaca."""

    def __init__(self, indice: dict[str, ET.Element]):
        self._indice = indice
        self._cache: dict[str, _ColOpacaLocal] = {}

    def __getitem__(self, nombre: str):
        c = self._cache.get(nombre)
        if c is None:
            el = self._indice[nombre]
            try:
                tipo = int(el.get("type"))
            except (TypeError, ValueError):
                tipo = -1
            c = self._cache[nombre] = _ColOpacaLocal(nombre, tipo, el)
        return c

    def __iter__(self) -> Iterator[str]:
        return iter(self._indice)

    def __len__(self) -> int:
        return len(self._indice)


# ---------------------------------------------------------------- utilidades

def xstage_de(ruta) -> Path:
    """Archivo .xstage de ``ruta``: el propio archivo, o el .xstage de una carpeta.

    Si la carpeta tiene varios, el que se llama como la carpeta; si no hay forma de
    elegir, ``ValueError``. Sin ninguno, ``FileNotFoundError``.
    """
    p = Path(ruta)
    if p.is_file():
        return p
    if not p.is_dir():
        raise FileNotFoundError(f"no existe: {p}")
    candidatos = sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() == ".xstage")
    if not candidatos:
        raise FileNotFoundError(f"la carpeta no tiene .xstage: {p}")
    if len(candidatos) == 1:
        return candidatos[0]
    propios = [x for x in candidatos if x.stem.lower() == p.name.lower()]
    if len(propios) == 1:
        return propios[0]
    raise ValueError(f"varios .xstage en {p} y ninguno se llama como la carpeta: {[x.name for x in candidatos]}")


def _num(v, defecto=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return defecto


def _punto(texto: str | None) -> tuple[float, ...] | None:
    if texto is None:
        return None
    try:
        return tuple(float(t) for t in texto.split(","))
    except ValueError:
        return None


_CACHE: "OrderedDict[tuple, Escena]" = OrderedDict()
_CACHE_MAX = 2


def limpiar_cache() -> None:
    _CACHE.clear()


def abrir(ruta) -> "Escena":
    """Abre una escena. Caché de 2 por (ruta resuelta, mtime_ns, tamaño)."""
    xs = xstage_de(ruta).resolve()
    st = xs.stat()
    clave = (str(xs), st.st_mtime_ns, st.st_size)
    e = _CACHE.get(clave)
    if e is not None:
        _CACHE.move_to_end(clave)
        return e
    e = Escena(xs, leer_xml(xs))
    _CACHE[clave] = e
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return e


# ---------------------------------------------------------------- Escena

class Escena:
    """Escena cargada. Construir con ``abrir(ruta)``."""

    def __init__(self, ruta: Path, raiz: ET.Element):
        self.ruta = Path(ruta)
        self.raiz = raiz
        self.avisos: list[str] = []
        self.nodos: dict[str, Nodo] = {}
        self.cables: list[Cable] = []
        self.backdrops: list[Backdrop] = []
        self.elementos: dict[int, Elemento] = {}
        self._columnas = None
        self._col_elem: dict[str, ET.Element] | None = None
        self._ent: dict[str, dict[int, list[tuple[str, int]]]] = {}
        self._sal: dict[str, list[tuple[int, str, int]]] = {}
        self._mpo: dict[str, str] = {}
        self._mpi: dict[str, str] = {}
        self._hijos: dict[str, list[str]] = {}

        esc = raiz.find("scenes/scene")
        if esc is None:
            raise ValueError("el archivo no tiene scenes/scene")
        self.escena_xml = esc
        self._leer_opciones()
        self._leer_elementos()
        rg = esc.find("rootgroup")
        if rg is None:
            self.avisos.append("la escena no tiene rootgroup")
        else:
            if rg.get("name") not in (None, RAIZ):
                self.avisos.append(f"rootgroup se llama {rg.get('name')!r}; las rutas usan {RAIZ!r}")
            self._grupo(rg, RAIZ)

    # ------------------------------------------------------------ carga

    def _leer_opciones(self) -> None:
        r = self.raiz
        m = r.find("options/metrics")
        self.metricas_texto: dict[str, str] = dict(m.attrib) if m is not None else {}
        self.metricas: dict[str, float] = {}
        if m is None:
            self.avisos.append("sin options/metrics: métricas por omisión")
        for k, v in METRICAS_POR_OMISION.items():
            x = _num(self.metricas_texto.get(k))
            if x is None:
                if m is not None:
                    self.avisos.append(f"options/metrics sin {k}: se usa {v:g}")
                x = v
            self.metricas[k] = x
        for k, t in self.metricas_texto.items():
            if k not in self.metricas:
                x = _num(t)
                if x is not None:
                    self.metricas[k] = x
        fr = r.find("options/framerate")
        self.fps: float | None = _num(fr.get("val")) if fr is not None else None
        pp = r.find("options/pixelPerModelUnitForVectorLayers")
        self.pixel_por_unidad: float | None = _num(pp.get("val")) if pp is not None else None
        nb = _num(self.escena_xml.get("nbframes")) if hasattr(self, "escena_xml") else None
        # P04: el nº de fotogramas es scene@nbframes
        self.n_fotogramas: int = int(nb) if nb is not None else 0
        if nb is None:
            self.avisos.append("scene sin nbframes")

    def _leer_elementos(self) -> None:
        for el in self.raiz.findall("elements/element"):
            try:
                i = int(el.get("id"))
            except (TypeError, ValueError):
                self.avisos.append("element sin id numérico")
                continue
            dib = tuple(d.get("name") or "" for d in el.findall("drawings/dwg"))   # P20
            self.elementos[i] = Elemento(i, el.get("elementName") or "", el.get("elementFolder") or "", dib)

    def _grupo(self, g: ET.Element, ruta: str) -> None:
        hijos: list[str] = []
        self._hijos[ruta] = hijos
        nl = g.find("nodeslist")
        if nl is not None:
            for ch in nl:
                if ch.tag not in ("module", "group"):
                    continue
                nombre = ch.get("name") or ""
                r = f"{ruta}/{nombre}"
                if r in self.nodos:
                    self.avisos.append(f"nodo repetido: {r}")
                    continue
                dis = ch.find("options/disabled")
                apagado = dis is not None and dis.get("val") == "true"      # P14
                pos = _punto(ch.get("pos"))
                if pos is None:
                    pos = (0.0, 0.0, 0.0)
                    self.avisos.append(f"pos ilegible en {r}")
                es_grupo = ch.tag == "group"                                # P08
                tipo = TIPO_GRUPO if es_grupo else (ch.get("type") or "")
                self.nodos[r] = Nodo(r, nombre, tipo, ruta, apagado, pos, ch.get("publishUnderTab"), ch)
                hijos.append(r)
                if tipo == TIPO_MULTIPORT_OUT:                              # P12: por tipo
                    self._mpo.setdefault(ruta, r)
                elif tipo == TIPO_MULTIPORT_IN:
                    self._mpi.setdefault(ruta, r)
                if es_grupo:
                    self._grupo(ch, r)
        ll = g.find("linkedlist")
        if ll is not None:
            for lk in ll:
                if lk.tag != "link":
                    continue
                try:                                                        # P09
                    pi = int(lk.get("inport", 0))
                    po = int(lk.get("outport", 0))
                except ValueError:
                    pi = po = 0
                    self.avisos.append(f"puerto ilegible en un cable de {ruta}")
                o, d = f"{ruta}/{lk.get('out')}", f"{ruta}/{lk.get('in')}"
                self.cables.append(Cable(ruta, o, po, d, pi))
                self._ent.setdefault(d, {}).setdefault(pi, []).append((o, po))
                self._sal.setdefault(o, []).append((po, d, pi))
        bd = g.find("backdrops")
        if bd is not None:
            for b in bd.findall("backdrop"):
                self.backdrops.append(self._backdrop(b, ruta, hijos))

    def _backdrop(self, b: ET.Element, grupo: str, hijos: list[str]) -> Backdrop:
        tl = _punto(b.get("topLeft")) or (0.0, 0.0)
        br = _punto(b.get("bottomRight")) or (0.0, 0.0)
        fondo = b.find("background")
        titulo = b.find("title")
        rect = (tl[0], tl[1], br[0], br[1])
        dentro = [
            r for r in hijos
            if rect[0] <= self.nodos[r].pos[0] <= rect[2] and rect[1] <= self.nodos[r].pos[1] <= rect[3]
        ]
        return Backdrop(
            grupo,
            titulo.get("text", "") if titulo is not None else "",
            fondo.get("color", "") if fondo is not None else "",
            rect,
            dentro,
        )

    # ------------------------------------------------------------ columnas

    @property
    def columnas(self) -> Mapping:
        """Columnas por nombre (perezosas). Las construye el módulo ``columnas``; sin él, opacas."""
        if self._columnas is None:
            if _leer_columnas is not None:
                self._columnas = _leer_columnas(self.escena_xml, self.metricas, elementos_validos=set(self.elementos))   # P30
            else:
                self._columnas = _ColumnasLocal(self._indice_columnas())
        return self._columnas

    def _indice_columnas(self) -> dict[str, ET.Element]:
        if self._col_elem is None:
            self._col_elem = {c.get("name"): c for c in self.escena_xml.iterfind("columns/column") if c.get("name")}
        return self._col_elem

    def elemento_de_columna(self, nombre: str | None) -> Elemento | None:
        """Elemento al que apunta una columna de exposición (``elementSeq@id``, P18)."""
        if not nombre:
            return None
        c = self._indice_columnas().get(nombre)
        if c is None or c.get("type") != COLUMNA_EXPOSICION:
            return None
        s = c.find("elementSeq")
        if s is None:
            return None
        try:
            return self.elementos.get(int(s.get("id")))
        except (TypeError, ValueError):
            return None

    def n_columnas_de_dibujo(self) -> int:
        """Columnas de exposición (tipo 0) que traen al menos un ``elementSeq`` (una vacía no cuenta),
        sin construir columnas."""
        return sum(
            1 for c in self._indice_columnas().values()
            if c.get("type") == COLUMNA_EXPOSICION and c.find("elementSeq") is not None
        )

    # ------------------------------------------------------------ rutas y atributos

    def ruta_norm(self, ruta: str) -> str:
        """Normaliza ``Top/G/N``, ``/G/N`` o ``G/N`` a la forma con ``Top/``."""
        s = str(ruta).strip().replace("\\", "/").lstrip("/")
        if s in self.nodos:
            return s
        if f"{RAIZ}/{s}" in self.nodos:
            return f"{RAIZ}/{s}"
        return s if (s == RAIZ or s.startswith(RAIZ + "/")) else f"{RAIZ}/{s}"

    def atributo_elem(self, ruta, *claves) -> ET.Element | None:
        n = self.nodos.get(self.ruta_norm(ruta))
        if n is None or not claves:
            return None
        a = n.elem.find("attrs")
        if a is None:
            return None
        return a.find("/".join(str(c).strip("/") for c in claves))

    def atributo(self, ruta, *claves) -> str | None:
        """Valor ``val`` crudo de ``attrs/k1/k2/...`` (P52)."""
        e = self.atributo_elem(ruta, *claves)
        return None if e is None else e.get("val")

    # ------------------------------------------------------------ grafo literal

    def entradas(self, ruta) -> dict[int, tuple[str, int]]:
        """Cables literales que llegan a ``ruta``: puerto_in -> (origen, puerto_out). Si un puerto
        tiene varios cables, el primero del archivo."""
        d = self._ent.get(self.ruta_norm(ruta), {})
        return {p: v[0] for p, v in sorted(d.items())}

    def puertos_composite(self, ruta) -> list[int]:
        """Puertos de entrada con cable, ascendente."""
        return sorted(self._ent.get(self.ruta_norm(ruta), {}))

    # ------------------------------------------------------------ grafo resuelto

    def _aviso_una_vez(self, texto: str) -> None:
        if texto not in self.avisos:
            self.avisos.append(texto)

    def _fuentes(self, ruta: str, puerto: int, prof: int) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for s, sp in self._ent.get(ruta, {}).get(puerto, ()):
            out.extend(self._origen(s, sp, prof))
        return out

    def _origen(self, s: str, sp: int, prof: int) -> list[tuple[str, int]]:
        if prof > PROFUNDIDAD_MAXIMA:
            self._aviso_una_vez("resolución de cables cortada por profundidad (¿ciclo?)")
            return []
        n = self.nodos.get(s)
        if n is None:
            self._aviso_una_vez(f"cable desde un nodo inexistente: {s}")
            return []
        if n.tipo == TIPO_GRUPO:
            # P11: la salida k de un grupo es la fuente de la entrada k de su MULTIPORT_OUT
            m = self._mpo.get(s)
            if m is None:
                return [(s, sp)]
            return self._fuentes(m, sp, prof + 1) or [(s, sp)]
        if n.tipo == TIPO_MULTIPORT_IN:
            # P11: lo que sale de MULTIPORT_IN es lo que entra al grupo por ese puerto
            return self._fuentes(n.grupo, sp, prof + 1)
        return [(s, sp)]

    def fuentes(self, ruta, puerto: int = 0) -> list[tuple[str, int]]:
        """Fuentes de la entrada ``puerto`` de ``ruta``, resueltas a través de grupos (P11).
        Si la salida k de un grupo no tiene fuente interior, devuelve ``(grupo, k)``."""
        return self._fuentes(self.ruta_norm(ruta), puerto, 0)

    def fuente(self, ruta, puerto: int = 0) -> tuple[str, int] | None:
        f = self.fuentes(ruta, puerto)
        return f[0] if f else None

    def _destinos(self, d: str, pin: int, prof: int) -> list[tuple[str, int]]:
        """Expande un destino literal (d, pin) a través de grupos hacia aguas abajo."""
        if prof > PROFUNDIDAD_MAXIMA:
            self._aviso_una_vez("resolución de cables cortada por profundidad (¿ciclo?)")
            return []
        n = self.nodos.get(d)
        if n is None:
            return [(d, pin)]
        if n.tipo == TIPO_GRUPO:
            m = self._mpi.get(d)
            if m is None:
                return [(d, pin)]
            res: list[tuple[str, int]] = []
            for po, dd, dp in self._sal.get(m, ()):
                if po == pin:
                    res.extend(self._destinos(dd, dp, prof + 1))
            return res or [(d, pin)]
        if n.tipo == TIPO_MULTIPORT_OUT:
            res = []
            for po, dd, dp in self._sal.get(n.grupo, ()):
                if po == pin:
                    res.extend(self._destinos(dd, dp, prof + 1))
            return res or [(d, pin)]
        return [(d, pin)]

    def salidas(self, ruta) -> list[tuple[int, str, int]]:
        """Consumidores de ``ruta`` resueltos a través de grupos: (puerto_out, destino, puerto_in)."""
        r = self.ruta_norm(ruta)
        out: list[tuple[int, str, int]] = []
        for po, d, pi in self._sal.get(r, ()):
            for dd, dp in self._destinos(d, pi, 0):
                out.append((po, dd, dp))
        return out

    def vecinos(self, ruta, sentido: str = "arriba", profundidad: int | None = 1,
                cruzar_grupos: bool = True) -> list[tuple[str, str]]:
        """Vecinos (ruta, tipo) en anchura. ``sentido``: "arriba" (fuentes) o "abajo" (consumidores).
        ``profundidad=None`` recorre todo. Con ``cruzar_grupos=False`` se siguen los cables literales."""
        if sentido not in ("arriba", "abajo"):
            raise ValueError("sentido debe ser 'arriba' o 'abajo'")
        ini = self.ruta_norm(ruta)
        visto = {ini}
        res: list[tuple[str, str]] = []
        frontera = [ini]
        nivel = 0
        while frontera and (profundidad is None or nivel < profundidad):
            nivel += 1
            sig: list[str] = []
            for r in frontera:
                for v in self._adyacentes(r, sentido, cruzar_grupos):
                    if v in visto:
                        continue
                    visto.add(v)
                    n = self.nodos.get(v)
                    res.append((v, n.tipo if n is not None else ""))
                    sig.append(v)
            frontera = sig
        return res

    def _adyacentes(self, r: str, sentido: str, cruzar: bool) -> list[str]:
        if sentido == "arriba":
            if cruzar:
                return [s for p in sorted(self._ent.get(r, {})) for s, _ in self._fuentes(r, p, 0)]
            return [s for p in sorted(self._ent.get(r, {})) for s, _ in self._ent[r][p]]
        if cruzar:
            return [d for _, d, _ in self.salidas(r)]
        return [d for _, d, _ in self._sal.get(r, ())]

    def apagado_efectivo(self, ruta) -> bool:
        """Apagado propio o de algún grupo ancestro (la herencia en Harmony no está medida: P15)."""
        n = self.nodos.get(self.ruta_norm(ruta))
        while n is not None:
            if n.apagado:
                return True
            n = self.nodos.get(n.grupo)
        return False

    def salidas_literales(self, ruta) -> list[tuple[int, str, int]]:
        """Cables literales que salen de ``ruta``."""
        return list(self._sal.get(self.ruta_norm(ruta), ()))

    def hijos(self, grupo: str) -> list[str]:
        """Rutas de los hijos directos de un grupo, en orden de documento."""
        return list(self._hijos.get(self.ruta_norm(grupo) if grupo != RAIZ else RAIZ, ()))
