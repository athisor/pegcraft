"""Columnas de trayectoria 3D (`<column type="2">`: `path3D` + `velocity`). Procedencia: P34 (medido en Harmony 24 como caja negra; error 3,4e-5 campos,
que es el redondeo de la z de la matriz) y P35 (orden de los puntos).

Reglas:
- Unidades (P34): en el espacio de matriz 1 campo vale KX = 2·aX/(aY·nY), KY = 2/nY, KZ = KX·nX/nZ (de `<metrics>`; ver `base.Metricas`).
- Curva: spline Hermite cúbica por los puntos de `path3D` con factores tipo Kochanek-Bartels (tension, continuity, bias de cada punto, 0 si se omiten).
  Tangente en un punto interior = w0·d0·(1-t)(1+b)(1+c) + w1·d1·(1-t)(1-b)(1-c) (salida; la entrada cambia el signo de c), con d0,d1 las cuerdas a los
  vecinos, w0 = |d1|/(|d0|+|d1|), w1 = |d0|/(|d0|+|d1|); los largos se miden en espacio de matriz con las tres componentes. Extremos: T0 = 2(P1-P0) - T_entrada(1).
- Recorrido: 50 muestras uniformes en u por tramo; se avanza en línea recta entre muestras. La columna `velocity` (Bézier 1D) da en cada cuadro la fracción
  de la longitud total recorrida, medida en espacio de matriz con los pesos useVeloX/Y/Z (false = esa componente no cuenta).
- Llaves fijas (`lockedInTime`): en el cuadro exacto de una llave manda la llave; desde la última, la última; antes de la primera, la primera. Un punto sin
  `lockedInTime` cuenta para la geometría pero no tiene punto en velocity. `constantZ="true"`: z en escalón con la de la última llave fija.
- Columna sin `<velocity>`: v = 0.

Guardas (A3-01: convención de compatibilidad, no medida en Harmony; A3-02: esos casos existen en escenas reales):
- cero puntos: (0, 0, 0); un punto: constante (sin curva);
- dos cuerdas vecinas nulas a la vez (tres puntos coincidentes): pesos w0 = w1 = 0,5 (la tangente sale 0 de todos modos);
- longitud total nula (puntos coincidentes o `useVelo*` todo en false): la posición es el primer punto.
Velocity entre llaves fijas (A7b-05, medido: c19 y sondas s1-s3): ver `ColTrayectoria3D._entre_llaves` (normalización por tramo en rampa, sin extrapolar ni retroceder,
solo si hay llave de velocity en el cuadro de ambas llaves fijas; si no, fracción global recortada a [0,1]).
Sin resolver: manijas de velocity con fracción fuera de [0,1] (aviso en la columna `velocidad`); velocity que baja de un extremo a otro del tramo; tramos con una sola
llave de velocity; varias llaves de igual valor máximo/mínimo; velocity antes de la primera llave fija o sin llaves fijas (se recorta a [0,1], no medido).
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from bisect import bisect_right

from .base import Columna, Metricas, numero, seguro
from .funcion import ColFuncion

NSEG = 50   # P34: pasos uniformes en u por tramo


def _sub(a, b): return [a[i] - b[i] for i in range(3)]
def _add(a, b): return [a[i] + b[i] for i in range(3)]
def _mul(a, s): return [a[i] * s for i in range(3)]


def _largo(d, W):
    return math.sqrt((d[0] * W[0]) ** 2 + (d[1] * W[1]) ** 2 + (d[2] * W[2]) ** 2)


def _tangentes(P, tcb, W):
    n = len(P)
    sal, ent = [None] * n, [None] * n
    for i in range(1, n - 1):
        t, c, b = tcb[i]
        d0, d1 = _sub(P[i], P[i - 1]), _sub(P[i + 1], P[i])
        l0, l1 = _largo(d0, W), _largo(d1, W)
        s = l0 + l1
        w0, w1 = (0.5, 0.5) if s <= 0.0 else (l1 / s, l0 / s)      # guarda: dos cuerdas nulas -> pesos 0,5
        sal[i] = _add(_mul(d0, (1 - t) * (1 + b) * (1 + c) * w0), _mul(d1, (1 - t) * (1 - b) * (1 - c) * w1))
        ent[i] = _add(_mul(d0, (1 - t) * (1 + b) * (1 - c) * w0), _mul(d1, (1 - t) * (1 - b) * (1 + c) * w1))
    if n == 2:
        sal[0] = ent[1] = _sub(P[1], P[0])
        return sal, ent
    sal[0] = _sub(_mul(_sub(P[1], P[0]), 2), ent[1])
    ent[-1] = _sub(_mul(_sub(P[-1], P[-2]), 2), sal[-2])
    return sal, ent


def _hermite(p0, p1, m0, m1, u):
    u2, u3 = u * u, u * u * u
    h00, h10, h01, h11 = 2 * u3 - 3 * u2 + 1, u3 - 2 * u2 + u, -2 * u3 + 3 * u2, u3 - u2
    return [h00 * p0[i] + h10 * m0[i] + h01 * p1[i] + h11 * m1[i] for i in range(3)]


class Curva:
    """Polilínea de la trayectoria (n >= 2 puntos) con longitud de arco acumulada en espacio de matriz. `uso` = (useVeloX, useVeloY, useVeloZ) como bool."""

    def __init__(self, P, tcb, metricas: Metricas, uso=(True, True, True), nseg: int = NSEG):
        W_tan = [metricas.KX, metricas.KY, metricas.KZ]
        W_arc = [w if u else 0.0 for w, u in zip(W_tan, uso)]
        self.P, self.n, self.nseg = P, len(P), nseg
        self.sal, self.ent = _tangentes(P, tcb, W_tan)
        self.ss, self.pts = [], []
        s, prev = 0.0, None
        for k in range(self.n - 1):
            for j in range(nseg + (1 if k == self.n - 2 else 0)):
                q = _hermite(P[k], P[k + 1], self.sal[k], self.ent[k + 1], j / nseg)
                if prev is not None:
                    s += _largo(_sub(q, prev), W_arc)
                self.ss.append(s)
                self.pts.append(q)
                prev = q
        self.L = s

    def arco_punto(self, i: int) -> float:
        """Longitud de arco (espacio de matriz) desde el inicio hasta el punto de control i."""
        return self.ss[min(max(i, 0), self.n - 1) * self.nseg]

    def en_fraccion(self, v: float):
        """Punto a la fracción v de la longitud total. v fuera de [0,1] se recorta a los extremos (A7b-05/06: Harmony no extrapola ni retrocede)."""
        if self.L <= 0.0:
            return list(self.pts[0])                  # guarda: longitud total nula
        return self.en_arco(min(max(v, 0.0), 1.0) * self.L)

    def en_arco(self, s: float):
        """Punto a la longitud de arco s (recortada a [0, L])."""
        if self.L <= 0.0:
            return list(self.pts[0])
        s = min(max(s, 0.0), self.L)
        j = max(0, min(bisect_right(self.ss, s) - 1, len(self.ss) - 2))
        s0, s1 = self.ss[j], self.ss[j + 1]
        a = 0.0 if s1 == s0 else (s - s0) / (s1 - s0)
        p0, p1 = self.pts[j], self.pts[j + 1]
        return [p0[k] + a * (p1[k] - p0[k]) for k in range(3)]


class ColTrayectoria3D(Columna):
    """Columna tipo 2 con `path3D`. `posicion(f)` -> (x, y, z) en campos; `velocidad` = columna `velocity` como ColFuncion (None si no existe)."""

    def __init__(self, nombre: str, tipo: int, elem: ET.Element, metricas: Metricas | None = None):
        super().__init__(nombre, tipo, elem)
        self.metricas = metricas or Metricas()
        self.velocidad: ColFuncion | None = None
        self.P: list[list[float]] = []
        self.tcb: list[list[float]] = []
        self.locks: list[tuple[float, int]] = []      # (cuadro, índice de punto), ascendente
        self.constante_z = False
        self.curva: Curva | None = None
        try:
            self._construir(elem)
        except Exception as e:  # noqa: BLE001 - nunca lanza
            self.aviso(f"trayectoria: no se pudo leer la columna ({type(e).__name__}: {e})")
            self.curva = None

    def _construir(self, el):
        pe = el.find("path3D")
        if pe is None:
            self.aviso("columna de trayectoria sin path3D")
            return
        at = pe.attrib
        self.constante_z = at.get("constantZ") == "true"
        uso = tuple(at.get("useVelo" + k, "true") == "true" for k in "XYZ")
        locks = []
        for pt in pe.iter("pt"):
            partes = (pt.get("val") or "").split(",")
            if len(partes) != 3:
                self.aviso(f"punto de path3D con {len(partes)} componentes (se completa con 0)")
            v = [numero(partes[i] if i < len(partes) else None, 0.0, self, "val") for i in range(3)]
            self.P.append(v)
            self.tcb.append([numero(pt.get(k), 0.0, self, k) for k in ("tension", "continuity", "bias")])
            lk = pt.get("lockedInTime")
            if lk is not None:
                try:
                    lf = float(lk)
                    if math.isfinite(lf):
                        locks.append((lf, len(self.P) - 1))
                    else:
                        raise ValueError
                except ValueError:
                    self.aviso(f"lockedInTime inválido ignorado: {lk!r}")
        self.locks = sorted(locks)                    # por cuadro (estable): la última llave es la de mayor cuadro
        ve = el.find("velocity")
        if ve is not None:
            self.velocidad = ColFuncion(self.nombre + "/velocity", 3, ve, modo="velocidad")
            for a in self.velocidad.avisos:
                self.aviso("velocity: " + a)
        if len(self.P) >= 2:
            self.curva = Curva(self.P, self.tcb, self.metricas, uso)
            if self.curva.L <= 0.0:
                self.aviso("longitud total nula: la posición es el primer punto")
        elif len(self.P) == 1:
            self.aviso("trayectoria de un solo punto: posición constante")
        else:
            self.aviso("trayectoria sin puntos: (0, 0, 0)")

    @seguro((0.0, 0.0, 0.0))
    def posicion(self, f: float) -> tuple[float, float, float]:
        """(x, y, z) en campos en el fotograma f. (P34)"""
        if not self.P:
            return (0.0, 0.0, 0.0)
        if not math.isfinite(f):
            self.aviso(f"fotograma no finito: {f!r}")
            f = 0.0
        q = None
        for lf, i in self.locks:                      # en el cuadro exacto de una llave fija manda la llave
            if f == lf:
                q = list(self.P[i])
        if q is None and self.locks and f >= self.locks[-1][0]:
            q = list(self.P[self.locks[-1][1]])       # desde la última llave fija: la última
        if q is None:
            if self.curva is None:                    # un solo punto (o curva rota)
                q = list(self.P[0])
            else:
                v = self.velocidad.valor(f) if self.velocidad is not None else 0.0
                q = self._entre_llaves(f, v)
        if self.constante_z:                          # z en escalón con la última llave fija
            zs = [self.P[i][2] for lf, i in self.locks if lf <= f]
            q[2] = zs[-1] if zs else self.P[0][2]
        return (q[0], q[1], q[2])

    def _entre_llaves(self, f: float, v: float):
        """Posición con velocity v en un cuadro sin llave. Entre dos llaves fijas consecutivas (A7b-05, c19 y sondas s1-s3, medido en Harmony): la velocity se
        normaliza por tramo: con vmin/vmax los extremos de las llaves de velocity del tramo, local = 0 hasta la última llave de vmin anterior a vmax,
        (v - vmin)/(vmax - vmin) entre ambas y 1 desde la primera llave de vmax (rampa; no extrapola ni retrocede), y se aplica entre las
        longitudes de arco de los puntos de las dos llaves (c19: 0 -> 1,3 en 7 sube al punto 2; 1,3 -> -0,3 se queda; -0,3 -> 1 sube al final). Solo si la columna velocity tiene un punto (llave) en el cuadro de CADA una de las dos llaves
        fijas (s2, s3, c19); si falta alguno (s1: llaves solo en los extremos) manda la fracción global. Si la velocity coincide con la fracción de cada
        punto es idéntico a la fracción global. Fuera de ese caso (antes de la primera llave o sin llaves): fracción global recortada a [0,1] (no medido)."""
        L = self.locks
        if self.velocidad is not None and len(L) >= 2 and L[0][0] < f < L[-1][0]:
            k = bisect_right([lf for lf, _ in L], f) - 1
            (f0, i0), (f1, i1) = L[k], L[k + 1]
            xs = {p.x for p in self.velocidad.puntos}
            if f0 not in xs or f1 not in xs:           # s1: sin llave de velocity en la llave fija, manda la fracción global
                return self.curva.en_fraccion(v)
            s0, s1 = self.curva.arco_punto(i0), self.curva.arco_punto(i1)
            llaves = sorted((p.x, p.y) for p in self.velocidad.puntos if f0 <= p.x <= f1)
            vmin, vmax = min(y for _, y in llaves), max(y for _, y in llaves)
            if vmax - vmin <= 1e-12:                  # tramo sin recorrido en velocity: no medido; se queda en la llave anterior
                return self.curva.en_arco(s0)
            fmax = next(x for x, y in llaves if y == vmax)                       # primera llave del máximo
            fmin = max((x for x, y in llaves if y == vmin and x <= fmax), default=None)   # última llave del mínimo anterior a él
            if fmin is None:                          # el mínimo viene después del máximo (velocity que baja): no medido
                local = min(max((v - llaves[0][1]) / (llaves[-1][1] - llaves[0][1]), 0.0), 1.0) if llaves[-1][1] != llaves[0][1] else 0.0
            elif f <= fmin:
                local = 0.0
            elif f >= fmax:
                local = 1.0
            else:
                local = min(max((v - vmin) / (vmax - vmin), 0.0), 1.0)
            return self.curva.en_arco(s0 + local * (s1 - s0))
        return self.curva.en_fraccion(v)

    def evaluar(self, f: float):
        return self.posicion(f)

    def fraccion_en_llaves(self) -> list[tuple[float, int, float]]:
        """Para la prueba de coherencia: [(cuadro, índice de punto, error de posición en campos)] de cada llave fija, llevando la fracción `velocity`
        guardada a la curva (sin mirar el atajo de llave fija). Vacío si no hay velocity, curva o longitud."""
        if self.velocidad is None or self.curva is None or self.curva.L <= 1e-12 or not self.velocidad.puntos:
            return []
        out = []
        for lf, i in self.locks:
            q = self.curva.en_fraccion(self.velocidad.valor(lf))
            out.append((lf, i, max(abs(q[k] - self.P[i][k]) for k in range(3))))
        return out
