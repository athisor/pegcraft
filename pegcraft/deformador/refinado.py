"""refinado.py: variante EXPERIMENTAL del evaluador: proyeccion continua sobre el eje de reposo (en vez del muestreo de 160 puntos por segmento).

bake/deformadores.py elige la muestra mas cercana de la curva de reposo (160 por segmento) y toma su tangente por diferencias finitas.
Aqui, tras esa busqueda gruesa, se refina el parametro t en [t_{j-1}, t_{j+1}] con K submuestras y se evalua el eje de reposo y el de pose
de forma analitica (Bezier y derivada) en el t refinado. Se activa con `with parche():` (cambia D.Deformador SOLO dentro del bloque; no
se escribe nada en bake/). Resultado del spike: <datos de trabajo omitidos>
"""
import math, sys
import numpy as np
sys.dont_write_bytecode = True
from ..bake import deformadores as D

K = 33          # submuestras por celda gruesa (+-1 muestra)
EPS_T = 1e-4    # la derivada en los extremos se evalua un poco dentro (asas de longitud 0 la anulan)


def _arr(segs):
    return np.asarray([[p0, p1, p2, p3] for p0, p1, p2, p3 in segs], float)   # (S, 4, 2)


def _bez(P, t):          # P (n,4,2), t (n,k) -> (n,k,2)
    t = t[..., None]
    return ((1 - t) ** 3) * P[:, None, 0] + 3 * ((1 - t) ** 2) * t * P[:, None, 1] + 3 * (1 - t) * t ** 2 * P[:, None, 2] + t ** 3 * P[:, None, 3]


def _ang(P, t):          # angulo de la tangente (n,k)
    t = np.clip(t, EPS_T, 1 - EPS_T)[..., None]
    d = 3 * ((1 - t) ** 2) * (P[:, None, 1] - P[:, None, 0]) + 6 * (1 - t) * t * (P[:, None, 2] - P[:, None, 1]) + 3 * t ** 2 * (P[:, None, 3] - P[:, None, 2])
    return np.arctan2(d[..., 1], d[..., 0])


def _puntos_fino(self, q):
    if self.sub:
        for d in self.sub:
            q = d.puntos(q)
        return q
    if self.sr.size == 0:
        return self._puntos_orig(q)
    M = D.MUESTRAS
    q = np.asarray(q, float) / self.div
    out = np.empty_like(q)
    for a in range(0, len(q), 2000):
        b = q[a:a + 2000]
        if self.rigido:       # KinematicOutput: transformacion rigida de la PUNTA (t=1 del ultimo tramo) con la tangente analitica
            s = np.full(len(b), len(self.sr) - 1); t = np.ones((len(b), 1))
        else:
            d2 = ((b[:, None, :] - self.Pr[None, :, :]) ** 2).sum(-1)
            i = d2.argmin(1)
            s, j = i // M, i % M
            j0, j1 = np.maximum(j - 1, 0), np.minimum(j + 1, M - 1)
            ts = (j0 / (M - 1))[:, None] + ((j1 - j0) / (M - 1))[:, None] * np.linspace(0, 1, K)[None, :]   # (n,K)
            C = _bez(self.sr[s], ts)                             # (n,K,2)
            k = ((C - b[:, None, :]) ** 2).sum(-1).argmin(1)
            t = ts[np.arange(len(b)), k][:, None]                # (n,1)
        Pr, Pa = self.sr[s], self.sa[s]
        cr = _bez(Pr, t)[:, 0]; ca = _bez(Pa, t)[:, 0]
        da = _ang(Pa, t)[:, 0] - _ang(Pr, t)[:, 0]
        v = b - cr
        co, si = np.cos(da), np.sin(da)
        out[a:a + 2000] = ca + np.stack([co * v[:, 0] - si * v[:, 1], si * v[:, 0] + co * v[:, 1]], 1)
    return out * self.div


class parche:
    """with parche(): ... -> D.Deformador proyecta de forma continua (K submuestras en la celda mas cercana)."""
    def __enter__(self):
        self._init, self._pun = D.Deformador.__init__, D.Deformador.puntos
        init = self._init

        def nuevo_init(s, nodos, A, div, var=None):
            init(s, nodos, A, div, var)
            if s.sub is None:
                gs = [g for g in D.grupos(nodos) if any(n["tipo"] == "CurveModule" for n in g)]
                nn = gs[0] if gs else nodos
                s.sr, s.sa = _arr(D.curva(nn, "rep", A, var)), _arr(D.curva(nn, "act", A, var))
        D.Deformador.__init__ = nuevo_init
        D.Deformador._puntos_orig = self._pun
        D.Deformador.puntos = _puntos_fino
        return self

    def __exit__(self, *a):
        D.Deformador.__init__, D.Deformador.puntos = self._init, self._pun
        if hasattr(D.Deformador, "_puntos_orig"):
            del D.Deformador._puntos_orig
