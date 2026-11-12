"""Columnas de función Bézier escalar (`<column type="3">`) y la columna `velocity` anidada de una trayectoria 3D.

Regla medida contra Harmony 24 como caja negra (error máximo 2,5e-4 en ~250 casos, incluidas 8 columnas de validación ciega de 5 a 7 puntos irregulares):
1. (P35) Un `<pt x="11,21">` vale para cada cuadro de la lista (mismos atributos) y `x="21-26"` es un rango. Los puntos se ordenan por x (el archivo no los guarda en orden).
   (P33) La `y` es `yLocal` si existe; si no, `y`.
2. (P31) Las manijas son las RELATIVAS lhx, lhy, rhx, rhy (ausente = 0). Harmony no lee las absolutas lx, ly, rx, ry al cargar: las rehace al guardar.
3. (P32) Alineación, solo en puntos interiores y solo con continuity="straight" o "smooth" (corner = ausente: manijas libres):
   d = norm(rh - lh); lh' = -|lh|·d; rh' = |rh|·d (cada manija conserva su largo).
4. (P32) Recorte por tramo de largo L: lim(c) = ((2L - c) + sqrt(c(4L - 3c)))/2 es el mayor |dx| que deja x(t) monótona; el límite de cada manija se calcula con
   c = min(|dx| CRUDO (guardado, antes de alinear) de la manija del otro extremo, L). Si |dx| lo supera, la manija se escala hacia abajo conservando su dirección.
5. (P31) Cada tramo es una cúbica de Bézier en (cuadro, valor): se resuelve x(t) = f y se toma y(t). constSeg="true" mantiene el valor de la llave hasta la siguiente.
   Antes de la primera llave y después de la última el valor es constante.

Modo `velocidad` (columna `velocity` de una trayectoria, P34): las manijas relativas son FRACCIONES del tramo vecino, recortadas a [0,1]:
rx = x + rhx·(x_sig - x), ry = y + rhy·(y_sig - y), lx = x - lhx·(x - x_ant), ly = y - lhy·(y - y_ant); sin alineación ni recorte por tramo.

Sin resolver (aviso en `avisos`): manijas escalares con dx de signo invertido (P32) y fracciones de velocity fuera de [0,1] (P34; error medido 0,24).
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from bisect import bisect_right
from dataclasses import dataclass

from .base import Columna, expandir_x, numero, seguro


@dataclass(slots=True)
class Punto:
    x: float
    y: float
    cs: bool = False                      # constSeg: valor constante hasta el punto siguiente
    continuidad: str = "corner"
    lraw: tuple = (0.0, 0.0)              # manijas relativas guardadas (antes de alinear)
    rraw: tuple = (0.0, 0.0)
    lx: float = 0.0                       # manijas absolutas (cuadro, valor) ya completadas
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0


def _alinear(lh, rh):
    """Dirección común d = rh - lh; cada manija conserva su largo. Si d = 0 no cambia nada. (P32)"""
    dx, dy = rh[0] - lh[0], rh[1] - lh[1]
    n = math.hypot(dx, dy)
    if n == 0:
        return lh, rh
    ux, uy = dx / n, dy / n
    ll, lr = math.hypot(*lh), math.hypot(*rh)
    return (-ll * ux, -ll * uy), (lr * ux, lr * uy)


def _limite(L, c):
    return ((2 * L - c) + math.sqrt(max(0.0, c * (4 * L - 3 * c)))) / 2


def _recortar(L, r, l, r_crudo, l_crudo):
    lim_r = _limite(L, min(abs(l_crudo[0]), L))
    lim_l = _limite(L, min(abs(r_crudo[0]), L))
    if abs(r[0]) > lim_r:
        k = lim_r / abs(r[0])
        r = (r[0] * k, r[1] * k)
    if abs(l[0]) > lim_l:
        k = lim_l / abs(l[0])
        l = (l[0] * k, l[1] * k)
    return r, l


def _bez(c, t):
    u = 1 - t
    return u * u * u * c[0] + 3 * u * u * t * c[1] + 3 * u * t * t * c[2] + t * t * t * c[3]


def _resolver(X, Y, f):
    """Resuelve x(t) = f por bisección y devuelve y(t)."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        t = (lo + hi) / 2
        lo, hi = (t, hi) if _bez(X, t) < f else (lo, t)
    return _bez(Y, (lo + hi) / 2)


class ColFuncion(Columna):
    """Columna tipo 3 (o la `velocity` de una trayectoria, con modo="velocidad"). `valor(f)` nunca lanza."""

    def __init__(self, nombre: str, tipo: int, elem: ET.Element, modo: str = "escalar"):
        super().__init__(nombre, tipo, elem)
        self.modo = modo
        self.exacto = True
        self._pts: list[Punto] = []
        self._xs: list[float] = []
        self._tramos: list[tuple | None] = []
        try:
            self._construir(elem)
        except Exception as e:  # noqa: BLE001 - nunca lanza
            self.exacto = False
            self.aviso(f"función: no se pudo leer la columna ({type(e).__name__}: {e})")
            self._pts, self._xs, self._tramos = [], [], []

    @property
    def puntos(self) -> list[Punto]:
        return self._pts

    # -- construcción ---------------------------------------------------------------------------------------------
    def _leer_puntos(self, el):
        vel = self.modo == "velocidad"
        pts, frac = [], []
        for pt in el.iter("pt"):
            a = pt.attrib
            if "x" not in a:
                self.aviso("punto sin x ignorado")
                continue
            xs = expandir_x(a["x"], self)
            if "yLocal" in a:                                                   # P33: yLocal manda sobre y
                y = numero(a["yLocal"], 0.0, self, "yLocal")
            else:
                y = numero(a.get("y"), 0.0, self, "y")
            cs = a.get("constSeg") == "true"
            lraw = (numero(a.get("lhx"), 0.0, self, "lhx"), numero(a.get("lhy"), 0.0, self, "lhy"))
            rraw = (numero(a.get("rhx"), 0.0, self, "rhx"), numero(a.get("rhy"), 0.0, self, "rhy"))
            fr = (any(k in a for k in ("lhx", "lhy")), any(k in a for k in ("rhx", "rhy")))
            cont = a.get("continuity", "corner")
            for x in xs:
                pts.append(Punto(x, y, cs, cont, lraw, rraw, x, y, x, y))
                frac.append(fr)
        orden = sorted(range(len(pts)), key=lambda i: pts[i].x)                # P35: ordenar por x (estable)
        pts = [pts[i] for i in orden]
        frac = [frac[i] for i in orden]
        return pts, frac, vel

    def _construir(self, el):
        pts, frac, vel = self._leer_puntos(el)
        n = len(pts)
        if vel:
            cl = lambda v: min(max(v, 0.0), 1.0)                                # noqa: E731
            for i, p in enumerate(pts):
                tiene_l, tiene_r = frac[i]
                for v in (p.lraw[0], p.lraw[1], p.rraw[0], p.rraw[1]):
                    if v < 0.0 or v > 1.0:
                        self.exacto = False
                        self.aviso("manijas de velocity con fracción fuera de [0,1]: se recortan; sin verificar contra Harmony (P34)")
                        break
                if i + 1 < n and tiene_r:
                    sg = pts[i + 1]
                    p.rx = p.x + cl(p.rraw[0]) * (sg.x - p.x)
                    p.ry = p.y + cl(p.rraw[1]) * (sg.y - p.y)
                if i > 0 and tiene_l:
                    an = pts[i - 1]
                    p.lx = p.x - cl(p.lraw[0]) * (p.x - an.x)
                    p.ly = p.y - cl(p.lraw[1]) * (p.y - an.y)
        else:
            for i, p in enumerate(pts):
                lh, rh = p.lraw, p.rraw
                if p.continuidad in ("straight", "smooth") and 0 < i < n - 1:
                    lh, rh = _alinear(lh, rh)
                p.lx, p.ly, p.rx, p.ry = p.x + lh[0], p.y + lh[1], p.x + rh[0], p.y + rh[1]
                if rh[0] < 0 or lh[0] > 0:
                    self.exacto = False
            if not self.exacto:
                self.aviso("manijas con dx de signo invertido: sin verificar contra Harmony (P32)")
        tramos: list[tuple | None] = []
        for a, b in zip(pts, pts[1:]):
            L = b.x - a.x
            if a.cs or L <= 0:
                tramos.append(None)
                continue
            r, l = (a.rx - a.x, a.ry - a.y), (b.lx - b.x, b.ly - b.y)
            if not vel:
                r, l = _recortar(L, r, l, a.rraw, b.lraw)                       # P32
            tramos.append(((a.x, a.x + r[0], b.x + l[0], b.x), (a.y, a.y + r[1], b.y + l[1], b.y)))
        self._pts, self._xs, self._tramos = pts, [p.x for p in pts], tramos

    # -- evaluación -----------------------------------------------------------------------------------------------
    @seguro(0.0)
    def valor(self, f: float) -> float:
        """Valor en el fotograma f. Sin puntos: 0. Antes del primer punto y después del último, el valor del extremo. (P31)"""
        if not self._pts:
            return 0.0
        if not math.isfinite(f):
            self.aviso(f"fotograma no finito: {f!r}")
            return self._pts[0].y
        if f <= self._xs[0]:
            return self._pts[0].y
        if f >= self._xs[-1]:
            return self._pts[-1].y
        i = bisect_right(self._xs, f) - 1
        t = self._tramos[i]
        return self._pts[i].y if t is None else _resolver(t[0], t[1], f)

    def evaluar(self, f: float):
        return self.valor(f)
