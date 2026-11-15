"""Lapiz de grosor variable (tGTB) como poligono relleno (ADR-0014).

# TVG-v1 §3.7: cada llave = t (0 a 1) y por lado (izq, der) el grosor (semiancho); §6: el grosor se interpola linealmente por longitud de arco.
# CENSO-8: el oraculo emite un poligono cerrado (M L Z) con el borde izquierdo, un semicirculo de 8 segmentos en el
# extremo final, el borde derecho de vuelta y otro semicirculo en el inicial. Contorno medido en E5_var2/3.
"""
import math

PASOS_CURVA = 8      # subdivisiones por tramo cubico (aproximacion propia)
SEG_CAP = 8          # segmentos por semicirculo (CENSO-8)


def es_variable(perfil):
    # CENSO-21: el oraculo emite poligono con 3 o mas llaves aunque el grosor sea constante; con 2 llaves iguales, un stroke
    return bool(perfil) and (len(perfil) > 2 or len({(round(k[1][0], 4), round(k[2][0], 4)) for k in perfil}) > 1)


def _muestras(tramos):
    pts = [tramos[0][0]]
    for p0, ctl, p1 in tramos:
        if len(ctl) == 2:
            c1, c2 = ctl
            for i in range(1, PASOS_CURVA + 1):
                u = i / PASOS_CURVA
                a, b, c, d = (1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3
                pts.append((a * p0[0] + b * c1[0] + c * c2[0] + d * p1[0], a * p0[1] + b * c1[1] + c * c2[1] + d * p1[1]))
        else:
            pts.append(p1)
    out = [pts[0]]
    for p in pts[1:]:     # sin puntos repetidos
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-9:
            out.append(p)
    return out


def _grosor(perfil, s, lado):
    ks = sorted(perfil, key=lambda k: k[0])
    if s <= ks[0][0]:
        return ks[0][lado][0]
    for a, b in zip(ks, ks[1:]):
        if s <= b[0]:
            u = (s - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 1.0
            return a[lado][0] + u * (b[lado][0] - a[lado][0])
    return ks[-1][lado][0]


def poligono(tramos, perfil):
    """Puntos (x, y) del contorno cerrado, o None si no se puede (trazo degenerado)."""
    pts = _muestras(tramos)
    if len(pts) < 2:
        return None
    acum = [0.0]
    for a, b in zip(pts, pts[1:]):
        acum.append(acum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = acum[-1]
    dirs = []
    for i in range(len(pts)):
        a, b = pts[max(i - 1, 0)], pts[min(i + 1, len(pts) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.0
        dirs.append((dx / n, dy / n))
    izq, der = [], []
    for p, d, s in zip(pts, dirs, acum):
        t = s / total
        nx, ny = -d[1], d[0]
        wl, wr = _grosor(perfil, t, 1), _grosor(perfil, t, 2)
        izq.append((p[0] + nx * wl, p[1] + ny * wl))
        der.append((p[0] - nx * wr, p[1] - ny * wr))
    out = list(izq)
    for cabo, sentido in ((-1, 1), (0, -1)):
        c, d = pts[cabo], dirs[cabo]
        nx, ny = -d[1], d[0]
        w = (_grosor(perfil, 1.0 if cabo else 0.0, 1) + _grosor(perfil, 1.0 if cabo else 0.0, 2)) / 2
        if cabo == -1:
            arco = [(c[0] + w * (nx * math.cos(k * math.pi / SEG_CAP) + d[0] * math.sin(k * math.pi / SEG_CAP)),
                     c[1] + w * (ny * math.cos(k * math.pi / SEG_CAP) + d[1] * math.sin(k * math.pi / SEG_CAP))) for k in range(1, SEG_CAP)]
            out += arco + list(reversed(der))
        else:
            arco = [(c[0] + w * (-nx * math.cos(k * math.pi / SEG_CAP) - d[0] * math.sin(k * math.pi / SEG_CAP)),
                     c[1] + w * (-ny * math.cos(k * math.pi / SEG_CAP) - d[1] * math.sin(k * math.pi / SEG_CAP))) for k in range(1, SEG_CAP)]
            out += arco
    return out
