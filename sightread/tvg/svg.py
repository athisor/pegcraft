"""Modelo .tvg -> SVG (contrato de salida del ADR-0013 §3).

Solo `svg`, `g`, `path`; comandos M L C Z; un grupo por arte (`underlay`, `colour`, `line`, `overlay`) dentro de
<g transform="matrix(1 0 0 -1 0 0)"> (el eje y de las coordenadas del dibujo apunta hacia arriba).
# TVG-v1 §5 (coordenadas), §6 (como se dibuja).
"""
import math

from . import perfil
from .modelo import ID_DEFECTO, ORDEN_ARTES

VIEWBOX = "-1875 -1875 3750 3750"   # TVG-v1 §5: marco visible de 3 750 u.d. con la camara por defecto


def _n(v):
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _color(paleta, cid):
    """id -> ('#rrggbb', opacidad) o None.  # TVG-v1 §4: el id ...03 se pinta negro opaco"""
    if cid == ID_DEFECTO:
        return "#000000", 1.0
    c = paleta.get(cid)
    if c is None or c["rgba"] is None:    # id fuera de la paleta o textura (no se decodifica)
        return None
    r, g, b, a = c["rgba"]
    return "#%02x%02x%02x" % (r, g, b), a / 255.0


def _tramos(puntos, anclas):
    """Parte un trazo en tramos (p0, [controles], p1) entre anclas consecutivas.  # TVG-v1 §3.4"""
    idx = [i for i, a in enumerate(anclas) if a]
    if len(idx) < 2:     # sin marcas de ancla: se tratan todos como rectas
        idx = list(range(len(puntos)))
    out = []
    for i, j in zip(idx, idx[1:]):
        out.append((puntos[i], puntos[i + 1:j], puntos[j]))
    return out


def _cmd(t):
    p0, ctl, p1 = t
    if len(ctl) == 2:
        return "C %s %s %s %s %s %s" % tuple(_n(v) for q in (ctl[0], ctl[1], p1) for v in q)
    return "L %s %s" % (_n(p1[0]), _n(p1[1]))


def _clave(p):
    return round(p[0] * 64), round(p[1] * 64)    # TVG-v1 §6: extremos cuantizados al 1/64


def _invertir(tramos):
    return [(p1, ctl[::-1], p0) for p0, ctl, p1 in reversed(tramos)]


def _dir_ini(s):
    p0, ctl, p1 = s[0]
    for q in list(ctl) + [p1]:
        if q != p0:
            return q[0] - p0[0], q[1] - p0[1]
    return 1.0, 0.0


def _dir_fin(s):
    p0, ctl, p1 = s[-1]
    for q in list(reversed(ctl)) + [p0]:
        if q != p1:
            return p1[0] - q[0], p1[1] - q[1]
    return 1.0, 0.0


def _giro(a, b):
    """Angulo con signo de a a b (positivo = a la izquierda)."""
    return math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1])


def _bucles(segs):
    """Encadena segmentos (listas de tramos) por extremos coincidentes -> bucles cerrados.  # TVG-v1 §6
    Con varias salidas en un vertice se toma la de giro mas a la izquierda (el color queda a la izquierda: CENSO-15)."""
    por_ini = {}
    for k, s in enumerate(segs):
        por_ini.setdefault(_clave(s[0][0]), []).append(k)
    usado = [False] * len(segs)
    out = []
    for k0 in range(len(segs)):
        if usado[k0]:
            continue
        usado[k0] = True
        bucle = list(segs[k0])
        ini = _clave(bucle[0][0])
        din = _dir_fin(segs[k0])
        while _clave(bucle[-1][2]) != ini:
            cand = [k for k in por_ini.get(_clave(bucle[-1][2]), ()) if not usado[k]]
            if not cand:
                break
            sig = min(cand, key=lambda k: _giro(din, _dir_ini(segs[k]))) if len(cand) > 1 else cand[0]
            usado[sig] = True
            bucle.extend(segs[sig])
            din = _dir_fin(segs[sig])
        if _clave(bucle[-1][2]) == ini:     # CENSO-15: solo se rellenan bucles cerrados
            out.append(bucle)
    return _sin_exterior(out)


def _poli(bucle):
    pts = []
    for p0, ctl, p1 in bucle:
        if len(ctl) == 2:
            c1, c2 = ctl
            for i in range(8):
                u = i / 8
                a, b, c, d = (1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3
                pts.append((a * p0[0] + b * c1[0] + c * c2[0] + d * p1[0], a * p0[1] + b * c1[1] + c * c2[1] + d * p1[1]))
        else:
            pts.append(p0)
    return pts


def _area(pts):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2


def _dentro(p, pts):
    x, y, c = p[0], p[1], False
    for a, b in zip(pts, pts[1:] + pts[:1]):
        if (a[1] > y) != (b[1] > y) and x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
            c = not c
    return c


def _sin_exterior(bucles):
    """Con el color de "izq" recorrido tal cual y el de "der" al reves, el color queda a la DERECHA de cada borde: un bucle horario
    rodea una region rellena; uno antihorario es un hueco si esta dentro de otro horario del mismo color y, si no, es el exterior de la
    region y no se rellena (CENSO-20)."""
    polis = [_poli(b) for b in bucles]
    ar = [_area(p) for p in polis]
    out = []
    for b, p, a in zip(bucles, polis, ar):
        if abs(a) < 1e-9:
            continue
        if a < 0 or any(a2 < 0 and _dentro(((p[0][0] + p[1][0]) / 2, (p[0][1] + p[1][1]) / 2), q) for q, a2 in zip(polis, ar)):
            out.append(b)
    return out


def _d(bucles, cerrar=True):
    partes = []
    for b in bucles:
        if not b:
            continue
        partes.append("M %s %s " % (_n(b[0][0][0]), _n(b[0][0][1])) + " ".join(_cmd(t) for t in b) + (" Z" if cerrar else ""))
    return " ".join(partes)


def _ancho(t):
    """Ancho del lapiz (stroke-width).  # TVG-v1 §6: ancho total = grosor izq + der; grosor 50 -> 100 u.d."""
    e = t["estilo"]
    if t["perfil"]:
        g = [k[1][0] + k[2][0] for k in t["perfil"]]
        return sum(g) / len(g)
    return 2 * e["ancho"]


def _capa(capa, paleta, out):
    rellenos = {}        # id color -> segmentos
    for t in capa["trazos"]:
        e = t["estilo"]
        if len(t["puntos"]) < 2:
            continue
        tr = _tramos(t["puntos"], t["anclas"])
        if e["izq"] == e["der"]:      # mismo color a ambos lados: borde interior, no delimita una region
            continue
        # CENSO-20: con y hacia arriba, el color de "der" (shaderRight) queda geometricamente a la IZQUIERDA del trazo (un circulo
        # antihorario relleno trae su color en "der"). Se recorre igual que el oraculo (izq tal cual, der al reves); el relleno queda a la derecha.
        if e["izq"]:
            rellenos.setdefault(e["izq"], []).append(tr)
        if e["der"]:
            rellenos.setdefault(e["der"], []).append(_invertir(tr))
    for cid, segs in rellenos.items():
        col = _color(paleta, cid)
        if col is None:
            continue
        hexa, op = col
        extra = "" if op >= 1 else ' fill-opacity="%s"' % _n(op)
        d = _d(_bucles(segs))
        if d:
            out.append('<path d="%s" fill="%s" fill-rule="nonzero"%s stroke="none"/>' % (d, hexa, extra))
    for t in capa["trazos"]:
        e = t["estilo"]
        if not e["lapiz"] or e["invisible"] or len(t["puntos"]) < 2:
            continue
        col = _color(paleta, e["lapiz"])
        if col is None:
            continue
        hexa, op = col
        if perfil.es_variable(t["perfil"]) and not t["cerrado"]:
            poli = perfil.poligono(_tramos(t["puntos"], t["anclas"]), t["perfil"])
            if poli:     # ADR-0014: perfil variable = poligono relleno, sin fill-rule
                fo = "" if op >= 1 else ' fill-opacity="%s"' % _n(op)
                out.append('<path d="M %s Z" fill="%s"%s stroke="none"/>' % (" L ".join("%s %s" % (_n(x), _n(y)) for x, y in poli), hexa, fo))
                continue
        extra = "" if op >= 1 else ' stroke-opacity="%s"' % _n(op)
        out.append('<path d="%s" fill="none" stroke="%s"%s stroke-width="%s" stroke-linecap="round" stroke-linejoin="round"/>'
                   % (_d([_tramos(t["puntos"], t["anclas"])], t["cerrado"]), hexa, extra, _n(_ancho(t))))


def a_svg(modelo):
    """modelo de `decodificar` -> texto SVG."""
    paleta = modelo["paleta"]
    grupos = []
    for nombre in ORDEN_ARTES:
        arte = modelo["artes"].get(nombre)
        if not arte:
            continue
        cuerpo = []
        for capa in arte["capas"]:
            _capa(capa, paleta, cuerpo)
        if cuerpo:
            grupos.append('<g id="%s">%s</g>' % (nombre, "".join(cuerpo)))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s"><g transform="matrix(1 0 0 -1 0 0)">%s</g></svg>'
            % (VIEWBOX, "".join(grupos)))
