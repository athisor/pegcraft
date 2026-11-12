"""Evaluación de una escena en un fotograma: canales, cadena de transformadores, Z, matriz y dibujo (reglas R1-R12 y modos: ver docs/PROCEDENCIA.md).

    ev =Evaluador(abrir(ruta))                    # modo "paridad" (por omisión)
    ev.nodos(12)                                   # READ con dibujo: ruta, tipo, padre, apagado, dibujable, matriz, z, dibujo, avisos
    ev.canales("Top/G/Peg", 12)                    # escala.x, rotacion, pivote.x, posicion.x ...
    ev.cadena("Top/G/Dibujo")                      # transformadores, del más cercano al más lejano

Modos:
  - "paridad" (nombre histórico del modo de compatibilidad, por omisión; el que consume el horneado de pegcraft): convenciones explícitas que Harmony
    no sigue (A4-01, A4-05): el sesgo no se aplica a la matriz (R4), un PEG apagado cuenta en la cadena y suma su Z (R7), y la ``matriz`` está en campos
    componiendo directamente, sin compensar el aspecto (anisótropa; A7b-02). Son convenciones, no medidas (docs/PROCEDENCIA.md).
  - "harmony": medido en Harmony sobre escenas sintéticas (A4-01..A4-05): PEG apagado = identidad, sesgo K(θ)=[[1,sin θ],[0,cos θ]] en orden R·K·S,
    matriz compuesta en espacio de matriz y devuelta en campos con F = D⁻¹·M·D.

Hechos: R1 P21/P33; R3 P21-P24; R4 P41; R5-R7 P42, P44-P46; R9 P48; R10 P49; R11 P18/P20/P30. Solo biblioteca estándar. Solo lectura.
"""
from __future__ import annotations

import math
from typing import Any

from .dibujos import DibujoRef, dibujo_de
from .tipos import RAIZ

__all__ = ["Evaluador"]

# R5: se cruzan sin transformar
TRANSPARENTES = frozenset({
    "CurveModule", "OffsetModule", "AutoPatchModule", "GROUP", "MULTIPORT_IN", "MULTIPORT_OUT", "PointConstraint2", "TransformationSwitch",
})
TRANSFORMADORES = frozenset({"PEG", "StaticConstraint"})
_CORTE = "corte"
_I = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))


def _mul(a, b):
    """Producto de matrices afines 2x3 (a·b)."""
    return ((a[0][0] * b[0][0] + a[0][1] * b[1][0], a[0][0] * b[0][1] + a[0][1] * b[1][1], a[0][0] * b[0][2] + a[0][1] * b[1][2] + a[0][2]),
            (a[1][0] * b[0][0] + a[1][1] * b[1][0], a[1][0] * b[0][1] + a[1][1] * b[1][1], a[1][0] * b[0][2] + a[1][1] * b[1][2] + a[1][2]))


def _num(t):
    try:
        v = float(t)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


class _Fuente:
    """Origen del valor de un atributo: columna (R1), o constante (val, si no defaultValue, si no el defecto)."""
    __slots__ = ("col", "nombre", "k", "tray")

    def __init__(self, col, nombre, k, tray=False):
        self.col, self.nombre, self.k, self.tray = col, nombre, k, tray

    def valor(self, f):
        if self.col is None:
            return self.k
        try:
            v = self.col.valor(f)
        except Exception:  # noqa: BLE001 - nunca lanza
            return self.k
        return self.k if v is None else v


class _Spec:
    """Fuentes de los canales de un nodo transformador o READ (se construye una vez)."""
    __slots__ = ("tipo", "pos", "tray", "esc", "rot", "sesgo", "piv", "pos_col", "esc_col")

    def __init__(self):
        self.tipo = ""
        self.pos = (None, None, None)       # _Fuente x, y, z
        self.tray = None                    # columna de trayectoria 3D, si la posición va por ella
        self.esc = (None, None)
        self.rot = None
        self.sesgo = None
        self.piv = (None, None)
        self.pos_col = ""
        self.esc_col = ""


class Evaluador:
    """Evalúa los nodos de una ``Escena``. ``modo``: "paridad" (compatibilidad, por omisión) o "harmony" (medido)."""

    def __init__(self, escena, modo: str = "paridad"):
        if modo not in ("paridad", "harmony"):
            raise ValueError("modo debe ser 'paridad' o 'harmony'")
        self.e = escena
        self.modo = modo
        self.avisos: list[str] = []
        self._spec: dict[str, _Spec] = {}
        self._arr: dict[str, tuple[str, str | None]] = {}
        self._f: float | None = None
        self._cc: dict[str, dict] = {}
        self._loc: dict[str, tuple] = {}
        self._mun: dict[str, tuple] = {}
        self._K = self._konstantes()

    # ------------------------------------------------------------ utilidades
    def _konstantes(self):
        m = self.e.metricas
        aX, aY = m.get("unitAspectRatioX", 4.0), m.get("unitAspectRatioY", 3.0)
        nX, nY, nZ = m.get("numberOfUnitsX", 24.0), m.get("numberOfUnitsY", 24.0), m.get("numberOfUnitsZ", 12.0)
        try:
            kx = 2 * aX / (aY * nY)
            return (kx, 2 / nY, kx * nX / nZ)        # P34: campos -> espacio de matriz
        except ZeroDivisionError:
            return (1 / 9, 1 / 12, 2 / 9)

    def _aviso(self, t):
        if t not in self.avisos:
            self.avisos.append(t)

    def _r(self, ruta):
        return self.e.ruta_norm(ruta)

    def _marco(self, f):
        if self._f != f:
            self._f = f
            self._cc, self._loc, self._mun = {}, {}, {}

    def _fuente(self, ruta, camino, defecto):
        el = self.e.atributo_elem(ruta, *camino.split("/"))
        if el is None:
            return _Fuente(None, "", defecto)
        k = _num(el.get("val"))
        if k is None:
            k = _num(el.get("defaultValue"))
        if k is None:
            k = defecto
        nombre = el.get("col")
        if nombre:
            try:
                col = self.e.columnas[nombre]
            except KeyError:
                col = None
            if col is not None and hasattr(col, "valor"):          # R1: columna si existe
                return _Fuente(col, nombre, k)
        return _Fuente(None, "", k)

    def _especificacion(self, ruta) -> _Spec:
        s = self._spec.get(ruta)
        if s is not None:
            return s
        s = self._spec[ruta] = _Spec()
        n = self.e.nodos.get(ruta)
        tipo = n.tipo if n is not None else ""
        s.tipo = tipo
        F = lambda c, d: self._fuente(ruta, c, d)  # noqa: E731
        bool_ = lambda c: (self.e.atributo(ruta, c) == "true")  # noqa: E731
        if tipo == "StaticConstraint":
            s.pos = (F("translate/x", 0.0), F("translate/y", 0.0), F("translate/z", 0.0))
            s.esc = (F("scale/x", 1.0), F("scale/y", 1.0))
            s.rot = F("rotate/anglez", 0.0)
            s.sesgo = _Fuente(None, "", 0.0)
            s.piv = (_Fuente(None, "", 0.0), _Fuente(None, "", 0.0))
            return s
        pre = "offset" if tipo == "READ" else "position"
        s.pos = (F(pre + "/x", 0.0), F(pre + "/y", 0.0), F(pre + "/z", 0.0))
        el3 = self.e.atributo_elem(ruta, pre, "attr3dpath")
        if el3 is not None and el3.get("col") and not bool_(pre + "/separate"):       # R3
            try:
                col = self.e.columnas[el3.get("col")]
            except KeyError:
                col = None
            if col is not None and hasattr(col, "posicion"):
                s.tray, s.pos_col = col, el3.get("col")
        if bool_("scale/separate"):                                                   # R3
            s.esc = (F("scale/x", 1.0), F("scale/y", 1.0))
        else:
            xy = F("scale/xy", 1.0)
            s.esc = (xy, xy)
        s.rot = F("rotation/anglez", 0.0)
        if s.rot.col is None and self.e.atributo_elem(ruta, "rotation", "anglez") is None:
            s.rot = F("angle", 0.0)
        s.sesgo = F("skew", 0.0)
        s.piv = (F("pivot/x", 0.0), F("pivot/y", 0.0))
        return s

    # ------------------------------------------------------------ canales
    def _canales(self, ruta, f) -> dict:
        self._marco(f)
        c = self._cc.get(ruta)
        if c is not None:
            return c
        s = self._especificacion(ruta)
        pre = "offset" if s.tipo == "READ" else "posicion"
        cols: dict[str, str] = {}
        if s.tray is not None:
            try:
                p = s.tray.posicion(f)
            except Exception:  # noqa: BLE001
                p = (0.0, 0.0, 0.0)
            px, py, pz = p
            for k in "xyz":
                cols[f"{pre}.{k}"] = s.pos_col + " (3D path)"
        else:
            px, py, pz = (q.valor(f) for q in s.pos)
            for k, q in zip("xyz", s.pos):
                if q.col is not None:
                    cols[f"{pre}.{k}"] = q.nombre
        sx, sy = s.esc[0].valor(f), s.esc[1].valor(f)
        for k, q in zip("xy", s.esc):
            if q.col is not None:
                cols[f"escala.{k}"] = q.nombre
        rot = s.rot.valor(f)
        if s.rot.col is not None:
            cols["rotacion"] = s.rot.nombre
        sk = s.sesgo.valor(f)
        if s.sesgo.col is not None:
            cols["sesgo"] = s.sesgo.nombre
        ox, oy = s.piv[0].valor(f), s.piv[1].valor(f)
        c = {"escala.x": sx, "escala.y": sy, "rotacion": rot, "sesgo": sk,
             f"{pre}.x": px, f"{pre}.y": py, f"{pre}.z": pz}
        if s.tipo != "StaticConstraint":
            c["pivote.x"], c["pivote.y"] = ox, oy
            for k, q in zip("xy", s.piv):
                if q.col is not None:
                    cols[f"pivote.{k}"] = q.nombre
        c["columnas"] = cols
        self._cc[ruta] = c
        return c

    def canales(self, ruta, f) -> dict:
        """Canales del nodo en ``f`` (R3): ``escala.x|y``, ``rotacion``, ``sesgo``, ``pivote.x|y`` (no en StaticConstraint), ``posicion.x|y|z``
        (``offset.x|y|z`` en un READ) y ``columnas`` (canal -> columna usada)."""
        c = self._canales(self._r(ruta), f)
        return {k: (dict(v) if k == "columnas" else v) for k, v in c.items()}

    def valor(self, ruta, atributo: str, f) -> float | str | None:
        """Valor de un atributo (``"offset.z"``, ``"offset/z"``, ``"opacity"``): columna si la hay, si no ``val``, si no ``defaultValue`` (R1).
        ``None`` si el nodo o el atributo no existen; ``str`` si no es numérico."""
        r = self._r(ruta)
        alias = {"rotacion": "rotation/anglez", "sesgo": "skew"}
        camino = alias.get(atributo, atributo).replace(".", "/").strip("/")
        el = self.e.atributo_elem(r, *camino.split("/"))
        if el is None:
            return None
        nombre = el.get("col")
        if nombre:
            try:
                col = self.e.columnas[nombre]
            except KeyError:
                col = None
            if col is not None and hasattr(col, "valor"):
                try:
                    v = col.valor(f)
                    if v is not None:
                        return v
                except Exception:  # noqa: BLE001
                    pass
        t = el.get("val")
        if t is None:
            t = el.get("defaultValue")
        if t is None:
            return None
        v = _num(t)
        return t if v is None else v

    # ------------------------------------------------------------ cadena
    def _arriba(self, ruta) -> tuple[str, str | None]:
        """Siguiente transformador aguas arriba por el puerto 0 resuelto: ("ok", ruta|None) o ("corte", motivo) (R5)."""
        a = self._arr.get(ruta)
        if a is not None:
            return a
        vistos = {ruta}
        res: tuple[str, str | None] = ("ok", None)
        act = self.e.fuente(ruta, 0)
        while act:
            r = act[0]
            if r in vistos:
                self._aviso(f"ciclo en la cadena de {ruta}")
                res = (_CORTE, r)
                break
            vistos.add(r)
            n = self.e.nodos.get(r)
            t = n.tipo if n is not None else ""
            if t in TRANSFORMADORES:
                res = ("ok", r)
                break
            if t == "READ" or t == "COMPOSITE":
                res = (_CORTE, r)
                break
            act = self.e.fuente(r, 0)                 # transparentes y desconocidos: se cruzan
        self._arr[ruta] = res
        return res

    def cadena(self, ruta, propio: str = "si_transforma") -> tuple[str, ...]:
        """Transformadores aguas arriba (PEG, StaticConstraint), del más cercano al más lejano. ``propio="si_transforma"``: el nodo va primero
        si es un transformador; ``"nunca"``: nunca. Si la cadena llega a un READ o COMPOSITE se corta (R5) y se devuelve lo reunido."""
        if propio not in ("nunca", "si_transforma"):
            raise ValueError("propio debe ser 'nunca' o 'si_transforma'")
        r = self._r(ruta)
        out: list[str] = []
        n = self.e.nodos.get(r)
        if propio == "si_transforma" and n is not None and n.tipo in TRANSFORMADORES:
            out.append(r)
        act = r
        vistos = {r}
        while True:
            est, sig = self._arriba(act)
            if est != "ok" or sig is None or sig in vistos:      # un ciclo corta la cadena
                break
            vistos.add(sig)
            out.append(sig)
            act = sig
        return tuple(out)

    def _cortada(self, ruta) -> bool:
        act = ruta
        while True:
            est, sig = self._arriba(act)
            if est == _CORTE:
                return True
            if sig is None:
                return False
            act = sig

    # ------------------------------------------------------------ matriz y Z
    def _apagado_transforma(self, ruta) -> bool:
        n = self.e.nodos.get(ruta)
        return n is not None and n.apagado and n.tipo == "PEG" and self.modo == "harmony"     # A4-01 (A7b-03)

    def _local(self, ruta, f):
        """(matriz local, z local, sesgo no nulo) en el espacio del modo."""
        self._marco(f)
        t = self._loc.get(ruta)
        if t is not None:
            return t
        n = self.e.nodos.get(ruta)
        tipo = n.tipo if n is not None else ""
        if tipo not in ("PEG", "StaticConstraint", "READ"):
            t = (_I, 0.0, False)
        elif self._apagado_transforma(ruta):
            t = (_I, 0.0, False)
        else:
            c = self._canales(ruta, f)
            pre = "offset" if tipo == "READ" else "posicion"          # el READ aplica su propia transformación (R6; A4-03)
            px, py, pz = c[f"{pre}.x"], c[f"{pre}.y"], c[f"{pre}.z"]
            sx, sy, th = c["escala.x"], c["escala.y"], math.radians(c["rotacion"])
            sk = c["sesgo"]
            hay_sesgo = abs(sk) > 1e-9
            vx, vy = c.get("pivote.x", 0.0), c.get("pivote.y", 0.0)
            co, si = math.cos(th), math.sin(th)
            # lineal = R·S (paridad: R4 ignora el sesgo, P41) o R·K·S (harmony, A4-05)
            if self.modo == "harmony" and hay_sesgo:
                ks = math.radians(sk)
                k00, k01, k11 = 1.0, math.sin(ks), math.cos(ks)
                a00, a01, a10, a11 = co, co * k01 - si * k11, si, si * k01 + co * k11
            else:
                a00, a01, a10, a11 = co, -si, si, co
            L = ((a00 * sx, a01 * sy), (a10 * sx, a11 * sy))
            if self.modo == "harmony":                    # A4-02: posición, offset y pivote se escalan por K antes de componer
                kx, ky, _ = self._K
                px, py, vx, vy = px * kx, py * ky, vx * kx, vy * ky
            tx = px + vx - (L[0][0] * vx + L[0][1] * vy)
            ty = py + vy - (L[1][0] * vx + L[1][1] * vy)
            t = (((L[0][0], L[0][1], tx), (L[1][0], L[1][1], ty)), pz, hay_sesgo)
        self._loc[ruta] = t
        return t

    def _mundo(self, ruta, f):
        """(matriz mundo, z, hay_sesgo) o ``None`` si la cadena se corta (R5, R7)."""
        self._marco(f)
        if ruta in self._mun:
            return self._mun[ruta]
        # iterativo hacia arriba para no recursar en cadenas largas
        pila = []
        act = ruta
        base = None
        corte = False
        while True:
            if act in self._mun:
                base = self._mun[act]
                break
            pila.append(act)
            est, sig = self._arriba(act)
            if est == _CORTE:
                # R5 (paridad, P42/P43; sin medir en Harmony): la cadena termina en el READ/COMPOSITE (no lo cruza). Solo un nodo sin ningún transformador
                # propio ni aguas arriba (un READ cuya entrada es un COMPOSITE/READ) queda sin matriz.
                n = self.e.nodos.get(act)
                if n is None or n.tipo not in TRANSFORMADORES:
                    corte = True
                else:
                    base = (_I, 0.0, False)
                break
            if sig is None or sig in pila:                       # fin de la cadena, o ciclo (se corta)
                base = (_I, 0.0, False)
                break
            act = sig
        for r in reversed(pila):
            if corte or base is None:
                self._mun[r] = None
                base = None
                continue
            m, z, sk = self._local(r, f)
            base = (_mul(base[0], m), base[1] + z, base[2] or sk)
            self._mun[r] = base
        return self._mun[ruta]

    def _a_campos(self, m):
        """Matriz de espacio de matriz a campos: F = D⁻¹·M·D (A4-02, A7b-01); en paridad ya está en campos."""
        if self.modo != "harmony":
            return m
        kx, ky, _ = self._K
        return ((m[0][0], m[0][1] * ky / kx, m[0][2] / kx), (m[1][0] * kx / ky, m[1][1], m[1][2] / ky))

    def _fila(self, ruta, f, dibujo_str) -> dict:
        n = self.e.nodos[ruta]
        w = self._mundo(ruta, f)
        avisos: list[str] = []
        if w is None:
            matriz, z = None, 0.0
        else:
            m, z, sk = w
            matriz = [list(x) for x in self._a_campos(m)]
            if sk and self.modo == "paridad":
                avisos.append("sesgo en la cadena: no se considera en la matriz (R4)")
        return {"ruta": ruta, "tipo": n.tipo, "padre": None if n.grupo == RAIZ else n.grupo[len(RAIZ) + 1:], "apagado": bool(n.apagado),
                "dibujable": not self.e.apagado_efectivo(ruta),   # A4-04, A7b-04
                "matriz": matriz, "z": z, "dibujo": dibujo_str, "avisos": avisos}

    def nodos(self, f, tipos=("READ",), solo_con_dibujo: bool = True, max: int | None = None) -> list[dict]:
        """Nodos de los ``tipos`` dados en el fotograma ``f``, en orden de documento (R10). Cada fila: ``ruta, tipo, padre`` (R9), ``apagado``
        (bandera propia, R8), ``dibujable`` (= no ``apagado_efectivo``), ``matriz`` (2x3 en campos o ``None`` si la cadena se corta), ``z`` (R7),
        ``dibujo`` (nombre del dibujo de un READ o ``None``) y ``avisos``. ``solo_con_dibujo`` omite los READ sin dibujo."""
        tipos = {tipos} if isinstance(tipos, str) else set(tipos)
        out: list[dict] = []
        for ruta, n in self.e.nodos.items():
            if n.tipo not in tipos:
                continue
            d = None
            if n.tipo == "READ":
                ref = dibujo_de(self.e, ruta, f)
                if ref is not None:
                    d = ref.dibujo
                elif solo_con_dibujo:
                    continue
            out.append(self._fila(ruta, f, d))
            if max is not None and len(out) >= max:
                break
        return out

    # ------------------------------------------------------------ volcado y dibujo
    def volcar_peg(self, ruta, desde, hasta) -> list[dict]:
        """Posición, escala y rotación de un PEG en cada fotograma de ``desde`` a ``hasta`` (inclusive)."""
        r = self._r(ruta)
        out = []
        for f in range(int(desde), int(hasta) + 1):
            c = self._canales(r, f)
            out.append({"f": f, "posicion.x": c["posicion.x"], "posicion.y": c["posicion.y"], "posicion.z": c["posicion.z"],
                        "escala.x": c["escala.x"], "escala.y": c["escala.y"], "rotacion": c["rotacion"]})
        return out

    def dibujo(self, ruta, f) -> DibujoRef | None:
        """Dibujo del READ en ``f`` (R11)."""
        return dibujo_de(self.e, self._r(ruta), f)
