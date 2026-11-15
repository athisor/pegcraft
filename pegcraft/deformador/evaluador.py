"""evaluador.py: deforma los puntos de un SVG en REPOSO con los parametros de un deformador (spec de esquema.py).

Dos fases, para que el costo por cuadro sea solo la segunda:
  Plantilla(svg_texto)      -> parsea los <path d>, subdivide L y C como bake/deformadores._deformar_d (depende solo del dibujo en reposo)
                                y deja todos los puntos en UN arreglo (N, 2) + la estructura de comandos. Una vez por dibujo.
  deformar(plantilla, spec) -> Q = D.puntos(P) en una sola llamada vectorizada; emite el SVG con el mismo formato (%.3f) que el aplastado.
La matematica del eje (Bezier, punto mas cercano, giro de la tangente, composicion padre->hijo, PEG intermedios) se IMPORTA de
bake/deformadores.py (Deformador, DeformadorSeg): aqui solo se separa lo que entra a ella. Lo que SI es nuevo es la separacion
reposo/pose y el tratamiento por lotes. Ver (doc interna omitida)
"""
import re, math, sys
import numpy as np
sys.dont_write_bytecode = True
from ..bake import deformadores as D

_RX_PATH = re.compile(r'(<path[^>]*?\sd=")([^"]*)(")')


def segmentos_de_spec(spec):
    """spec['segmentos'] -> (segs, pres) en la forma que espera D.DeformadorSeg."""
    segs, pres = [], []
    for s in spec["segmentos"]:
        nodos = []
        for n in s["nodos"]:
            d = {"ruta": n.get("ruta"), "tipo": n["tipo"], "act": dict(n["pose"]), "rep": dict(n["reposo"])}
            if n.get("closepath") is not None:
                d["closepath"] = n["closepath"]
            if n.get("cinematico"):
                d["cinematico"] = True
            nodos.append(d)
        segs.append({"pegs": s.get("pegs", []), "nodos": nodos})
        p = s.get("pre")
        pres.append(None if p is None else np.vstack([np.asarray(p, float).reshape(2, 3), [0.0, 0.0, 1.0]]))
    return segs, pres


def construir(spec, var=None):
    """spec -> D.DeformadorSeg (las curvas de reposo y de pose se muestrean aqui: costo por cuadro)."""
    segs, pres = segmentos_de_spec(spec)
    return D.DeformadorSeg(segs, pres, spec["A"], spec["div"], var)


class Plantilla:
    """SVG en reposo ya troceado: P (N,2) puntos sin deformar y la lista de comandos que los agrupa."""
    def __init__(self, svg):
        self.partes, self.paths = [], []     # texto entre paths; por path: lista de operaciones (cmd, k0)
        pts = []
        pos = 0
        for m in _RX_PATH.finditer(svg):
            self.partes.append(svg[pos:m.start(2)])
            pos = m.end(2)
            self.paths.append(self._trocear(m.group(2), pts))
        self.partes.append(svg[pos:])
        self.P = np.asarray(pts, float).reshape(-1, 2)

    @staticmethod
    def _trocear(d, pts):
        tok = D._TOK.findall(d)
        i, ops, cur, ini = 0, [], None, None
        num = lambda k: np.array([float(x) for x in tok[i + 1:i + 1 + k]]).reshape(-1, 2)
        while i < len(tok):
            c = tok[i]
            if c == "M":
                cur = ini = num(2)[0]; i += 3
                ops.append(("M", len(pts), 1)); pts.append(cur)
            elif c == "L":
                p = num(2)[0]; i += 3
                n = max(1, int(math.ceil(np.linalg.norm(p - cur) / D.PASO)))
                sub = cur + (p - cur) * (np.arange(1, n + 1) / n)[:, None]
                ops.append(("L", len(pts), n)); pts.extend(sub)
                cur = p
            elif c == "C":
                p1, p2, p3 = num(6); i += 7
                n = max(1, int(math.ceil((np.linalg.norm(p1 - cur) + np.linalg.norm(p2 - p1) + np.linalg.norm(p3 - p2)) / (2 * D.PASO))))
                ctrl = [cur, p1, p2, p3]
                for k in range(n):
                    sub = D._trozo(ctrl, k / n, (k + 1) / n)
                    ops.append(("C", len(pts), 3)); pts.extend(sub[1:])
                cur = p3
            elif c == "Z":
                ops.append(("Z", 0, 0)); cur = ini; i += 1
            else:
                raise ValueError("comando de path no soportado: " + c)
        return ops

    @property
    def n_puntos(self):
        return len(self.P)

    def emitir(self, Q):
        """Q (N,2) deformados -> SVG (mismo formato que bake/deformadores.deformar_svg)."""
        s = ["%.3f %.3f" % (x, y) for x, y in Q]
        out = []
        for parte, ops in zip(self.partes, self.paths):
            out.append(parte)
            seg = []
            for cmd, k, n in ops:
                if cmd == "M":
                    seg.append("M " + s[k])
                elif cmd == "L":
                    seg.extend("L " + s[k + j] for j in range(n))
                elif cmd == "C":
                    seg.append("C " + s[k] + " " + s[k + 1] + " " + s[k + 2])
                else:
                    seg.append("Z")
            out.append(" ".join(seg))
        out.append(self.partes[-1])
        return "".join(out)


def deformar_puntos(plantilla, spec, var=None):
    """Solo la matematica: (N,2) deformados (campos tvg), sin texto."""
    return construir(spec, var).puntos(plantilla.P)


def deformar(plantilla, spec, var=None):
    """SVG deformado (texto) desde la plantilla en reposo y el spec."""
    return plantilla.emitir(deformar_puntos(plantilla, spec, var))
