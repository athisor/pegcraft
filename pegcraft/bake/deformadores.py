"""deformadores.py: deformadores de curva/envolvente de Harmony (OffsetModule + CurveModule) aplicados a la geometria del SVG de un dibujo.

Modelo (deducido de los atributos del .xstage y MEDIDO contra renders de Harmony en PLANO fN; ver (doc interna omitida):
  cadena  = Offset (punto inicial P0) + Curve, Curve_1, ... (cada uno: una cubica de Bezier que llega a su `offset`)
            P1 = P0 + length0 * u(orientation0);  P2 = P3 - length1 * u(orientation1);  u(a) = (A cos a, sin a)
            `closepath` en el ultimo nodo = envolvente cerrada (el ultimo punto vuelve al inicio = `offset` del Offset).
  reposo  = la misma curva con restingoffset / restlength* / restingorientation*.
  unidades: TODO en campos del .xstage (puntos y asas); las x se multiplican por A (4/3) para pasar al espacio isotropo del
            dibujo (x_tvg / div). MEDIDO: asa con A (hombro IoU 0,9989) contra asa isotropa (0,988).
  deformar un punto q del dibujo: c = punto mas cercano de la curva de REPOSO (segmento i, parametro t); v = q - c;
            q' = C_actual(i, t) + R(angulo tangente actual - angulo tangente reposo) * v
  Fuera de los extremos de una cadena abierta queda la extension rigida del extremo (INFINITE_INFLUENCE).
Cadenas con varios deformadores (hijo bajo padre, p. ej. craneo bajo cuello): grupos() los separa y Deformador los compone (el de reposo se ignora).
No cubre: radios de influencia (transversal/longitudinal), localreferential, orientacion del Offset distinta de 0 con cadenas hijas,
Deformation-Composite, PointConstraint2.
VARIANTE (env PEGCRAFT_DEF_VAR, letras; def. ninguna): 'i' = asa isotropa (sin A en x), peor medido;
                                          'o' = en una envolvente cerrada el inicio/cierre es el `offset` del ultimo Curve y no el del Offset.
"""
import os, re, math, sys
import numpy as np
sys.dont_write_bytecode = True
VAR = os.environ.get("PEGCRAFT_DEF_VAR", "")
MUESTRAS = 160           # por segmento (modo antiguo: busqueda por muestreo + tangente por diferencias finitas)
REFINADO = os.environ.get("PEGCRAFT_DEF_REFINADO", "1") not in ("0", "no", "off")   # 1 = proyeccion continua + tangente analitica (spike deform_param); 'no' = el muestreo de antes
MUESTRAS_GRUESO = int(os.environ.get("PEGCRAFT_DEF_MUESTRAS", "16"))   # por segmento, solo para localizar la celda en modo refinado
MODELO = ("|ref%d" % MUESTRAS_GRUESO) if REFINADO else ""   # sufijo de la clave del almacen: el SVG deformado depende del modelo de proyeccion
K_FINO = 65              # submuestras de la celda gruesa (+-1 muestra) en modo refinado
EPS_T = 1e-4             # la tangente en los extremos se evalua un poco dentro (asas de longitud 0 la anulan)
PASO = 5.0               # unidades tvg: largo maximo de un tramo al subdividir


def _u(grados, A_asa):
    a = math.radians(grados)
    return np.array([A_asa * math.cos(a), math.sin(a)])


def curva(nodos, clave, A, var=None):
    """nodos: [{tipo, act:{...}, rep:{...}, closepath}] de la raiz (Offset) al ultimo Curve. clave: 'act'|'rep'.
    Devuelve lista de segmentos [(P0, P1, P2, P3)] en espacio isotropo (campos-Y)."""
    var = VAR if var is None else var
    Ah = 1.0 if "i" in var else A
    off = [n for n in nodos if n["tipo"] == "OffsetModule"]
    cur = [n for n in nodos if n["tipo"] == "CurveModule"]
    if not cur:
        return []
    pt = lambda n: np.array([A * n[clave]["offset/x"], n[clave]["offset/y"]])
    cerrada = cur[-1].get("closepath") == "true"
    p0 = pt(off[0]) if off else pt(cur[-1])
    if cerrada and "o" in var:
        p0 = pt(cur[-1])
    segs, ini = [], p0
    for i, n in enumerate(cur):
        p3 = pt(n)
        if cerrada and i == len(cur) - 1 and "o" not in var:
            p3 = ini
        v = n[clave]
        p1 = p0 + v["length0"] * _u(v["orientation0"], Ah)
        p2 = p3 - v["length1"] * _u(v["orientation1"], Ah)
        segs.append((p0, p1, p2, p3))
        p0 = p3
    return segs


def _muestras(segs, m=None):
    t = np.linspace(0, 1, m or MUESTRAS)[:, None]
    P, T = [], []
    for p0, p1, p2, p3 in segs:
        c = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3
        d = np.gradient(c, axis=0)
        P.append(c); T.append(np.arctan2(d[:, 1], d[:, 0]))
    return np.concatenate(P), np.concatenate(T)


def _arr(segs):
    return np.asarray([[p0, p1, p2, p3] for p0, p1, p2, p3 in segs], float).reshape(-1, 4, 2)   # (S, 4, 2)


def _bez_lote(P, t):     # P (n,4,2), t (n,k) -> (n,k,2)
    t = t[..., None]
    return ((1 - t) ** 3) * P[:, None, 0] + 3 * ((1 - t) ** 2) * t * P[:, None, 1] + 3 * (1 - t) * t ** 2 * P[:, None, 2] + t ** 3 * P[:, None, 3]


def _ang_lote(P, t):     # angulo de la tangente analitica (n,k)
    t = np.clip(t, EPS_T, 1 - EPS_T)[..., None]
    d = 3 * ((1 - t) ** 2) * (P[:, None, 1] - P[:, None, 0]) + 6 * (1 - t) * t * (P[:, None, 2] - P[:, None, 1]) + 3 * t ** 2 * (P[:, None, 3] - P[:, None, 2])
    return np.arctan2(d[..., 1], d[..., 0])


def grupos(nodos):
    """Parte la cadena (raiz->punta) en deformadores independientes: cada OffsetModule abre uno (Offset + sus Curve). Un grupo
    de varios deformadores aparece cuando el READ hereda la deformacion de un padre (p. ej. craneo bajo el cuello)."""
    gs = []
    for n in nodos:
        if n["tipo"] == "OffsetModule" or not gs:
            gs.append([])
        gs[-1].append(n)
    return gs


ORDEN = os.environ.get("PEGCRAFT_DEF_ORDEN", "hijo")   # 'hijo' = q' = D_padre(D_hijo(q)) (primero el mas cercano al dibujo); 'padre' = al reves


KINEMATIC = os.environ.get("PEGCRAFT_KINEMATIC", "1") not in ("0", "no", "off")   # 1 = detras de un KinematicOutput la deformacion es rigida (la punta)


class Deformador:
    """Un deformador, o varios compuestos si la cadena trae mas de uno (grupos(); el de reposo se ignora en activos())."""
    def __init__(self, nodos, A, div, var=None):
        self.div = div
        gs = [g for g in grupos(nodos) if any(n["tipo"] == "CurveModule" for n in g)]
        if len(gs) > 1:
            gs = gs[::-1] if ORDEN == "hijo" else gs
            self.sub = [Deformador(g, A, div, var) for g in gs]
            return
        self.sub = None
        nodos = gs[0] if gs else nodos
        self.rigido = KINEMATIC and any(n.get("cinematico") for n in nodos)
        sr, sa = curva(nodos, "rep", A, var), curva(nodos, "act", A, var)
        self.refinado = REFINADO and len(sr) > 0
        if self.refinado:
            self.M = max(MUESTRAS_GRUESO, 3)
            self.sr, self.sa = _arr(sr), _arr(sa)
            self.Pr, _ = _muestras(sr, self.M)
        else:
            self.Pr, self.Tr = _muestras(sr)
            self.Pa, self.Ta = _muestras(sa)

    def puntos(self, q):
        """q: (N, 2) en unidades tvg (y arriba). Devuelve (N, 2) deformado."""
        if self.sub:
            for d in self.sub:
                q = d.puntos(q)
            return q
        q = np.asarray(q, float) / self.div
        out = np.empty_like(q)
        if self.refinado:
            return self._puntos_fino(q, out) * self.div
        for a in range(0, len(q), 2000):
            b = q[a:a + 2000]
            d2 = ((b[:, None, :] - self.Pr[None, :, :]) ** 2).sum(-1)
            i = np.full(len(b), len(self.Pr) - 1) if self.rigido else d2.argmin(1)
            v = b - self.Pr[i]
            da = self.Ta[i] - self.Tr[i]
            co, si = np.cos(da), np.sin(da)
            out[a:a + 2000] = self.Pa[i] + np.stack([co * v[:, 0] - si * v[:, 1], si * v[:, 0] + co * v[:, 1]], 1)
        return out * self.div

    def _puntos_fino(self, q, out):
        """Proyeccion continua sobre el eje de reposo: celda gruesa (M muestras/seg) y K_FINO submuestras dentro de +-1 celda; Bezier y
        tangente analiticas en el t refinado. KinematicOutput: la punta (t=1 del ultimo tramo) con su tangente analitica."""
        M = self.M
        for a in range(0, len(q), 2000):
            b = q[a:a + 2000]
            if self.rigido:
                s = np.full(len(b), len(self.sr) - 1); t = np.ones((len(b), 1))
            else:
                i = ((b[:, None, :] - self.Pr[None, :, :]) ** 2).sum(-1).argmin(1)
                s, j = i // M, i % M
                j0, j1 = np.maximum(j - 1, 0), np.minimum(j + 1, M - 1)
                ts = (j0 / (M - 1))[:, None] + ((j1 - j0) / (M - 1))[:, None] * np.linspace(0, 1, K_FINO)[None, :]
                C = _bez_lote(self.sr[s], ts)
                k = ((C - b[:, None, :]) ** 2).sum(-1).argmin(1)
                t = ts[np.arange(len(b)), k][:, None]
            Pr, Pa = self.sr[s], self.sa[s]
            cr, ca = _bez_lote(Pr, t)[:, 0], _bez_lote(Pa, t)[:, 0]
            da = _ang_lote(Pa, t)[:, 0] - _ang_lote(Pr, t)[:, 0]
            v = b - cr
            co, si = np.cos(da), np.sin(da)
            out[a:a + 2000] = ca + np.stack([co * v[:, 0] - si * v[:, 1], si * v[:, 0] + co * v[:, 1]], 1)
        return out


_TOK = re.compile(r"[MLCZ]|-?\d+(?:\.\d+)?(?:e-?\d+)?")


def _deformar_d(d, D):
    tok = _TOK.findall(d)
    i, out, cur, ini = 0, [], None, None
    num = lambda k: np.array([float(x) for x in tok[i + 1:i + 1 + k]]).reshape(-1, 2)
    fmt = lambda P: " ".join("%.3f %.3f" % (x, y) for x, y in P)
    while i < len(tok):
        c = tok[i]
        if c == "M":
            cur = ini = num(2)[0]; i += 3
            out.append("M " + fmt(D.puntos([cur])))
        elif c == "L":
            p = num(2)[0]; i += 3
            n = max(1, int(math.ceil(np.linalg.norm(p - cur) / PASO)))
            pts = cur + (p - cur) * (np.arange(1, n + 1) / n)[:, None]
            out.extend("L " + s for s in _pares(fmt(D.puntos(pts))))
            cur = p
        elif c == "C":
            p1, p2, p3 = num(6); i += 7
            n = max(1, int(math.ceil((np.linalg.norm(p1 - cur) + np.linalg.norm(p2 - p1) + np.linalg.norm(p3 - p2)) / (2 * PASO))))
            ctrl = [cur, p1, p2, p3]
            for k in range(n):                      # de Casteljau: trozo [k/n, (k+1)/n]
                sub = _trozo(ctrl, k / n, (k + 1) / n)
                out.append("C " + fmt(D.puntos(sub[1:])))
            cur = p3
        elif c == "Z":
            out.append("Z"); cur = ini; i += 1
        else:
            raise ValueError("comando de path no soportado: " + c)
    return " ".join(out)


def _pares(s):
    v = s.split(" ")
    return [v[k] + " " + v[k + 1] for k in range(0, len(v), 2)]


def _bez(c, t):
    return (1 - t) ** 3 * c[0] + 3 * (1 - t) ** 2 * t * c[1] + 3 * (1 - t) * t ** 2 * c[2] + t ** 3 * c[3]


def _der(c, t):
    return 3 * (1 - t) ** 2 * (c[1] - c[0]) + 6 * (1 - t) * t * (c[2] - c[1]) + 3 * t ** 2 * (c[3] - c[2])


def _trozo(c, a, b):
    h = (b - a) / 3.0
    pa, pb = _bez(c, a), _bez(c, b)
    return [pa, pa + h * _der(c, a), pb - h * _der(c, b), pb]


def deformar_svg(svg_in, svg_out, D):
    s = open(svg_in, encoding="utf-8").read()
    s = re.sub(r'(<path[^>]*?\sd=")([^"]*)(")', lambda m: m.group(1) + _deformar_d(m.group(2), D) + m.group(3), s)
    open(svg_out, "w", encoding="utf-8").write(s)


PRE = os.environ.get("PEGCRAFT_DEF_PRE", "1") not in ("0", "no", "off")   # 1 = la deformacion actua DESPUES de los PEG que hay entre el READ y ella


def segmentos(cadena, eps=1e-6):
    """Deformadores ACTIVOS de la cadena de un READ (censo.py, del mas cercano al mas lejano) con los PEG que hay antes de cada uno:
    [{"pegs": [rutas de PEG del mas cercano al mas lejano desde el READ o el deformador anterior], "nodos": [Offset, Curve...] (raiz->punta)}].
    Un grupo en reposo es la identidad: se omite y sus PEG pasan al segmento siguiente. Con PEGCRAFT_DEF_PRE=0 no hay PEG antes (comportamiento anterior)."""
    out, acc, grupo = [], [], []

    def cerrar():
        nonlocal acc, grupo
        if grupo:
            g = list(reversed(grupo))
            if max(c.get("delta", 0) for c in g) > eps:
                out.append({"pegs": acc if PRE else [], "nodos": g}); acc = []
            grupo = []
    for c in cadena:
        if c["tipo"] == "PEG":
            cerrar(); acc.append(c["ruta"])
        elif c["tipo"] in ("OffsetModule", "CurveModule"):
            grupo.append(c)
            if c["tipo"] == "OffsetModule":
                cerrar()
        else:
            cerrar()
    cerrar()
    return out


class DeformadorSeg:
    """Deformadores compuestos en el orden de la cadena (del mas cercano al READ al mas lejano); antes de cada uno se aplica la matriz
    `pre` (campos-Y isotropos) de los PEG intermedios: q -> D_k(pre_k q) ... -> D_1(pre_1 q)."""
    def __init__(self, segs, pres, A, div, var=None):
        self.div = div
        self.sub = [(None if pre is None else np.asarray(pre, float), Deformador(sg["nodos"], A, div, var)) for sg, pre in zip(segs, pres)]

    def puntos(self, q):
        q = np.asarray(q, float)
        for pre, d in self.sub:
            if pre is not None:
                c = q / self.div
                q = (c @ pre[:2, :2].T + pre[:2, 2]) * self.div
            q = d.puntos(q)
        return q


def activos(cadena, eps=1e-6):
    """Nodos deformadores de la cadena de un READ (censo.py: del mas cercano al mas lejano) en orden raiz->punta, o [] si estan en reposo."""
    ds = [c for c in cadena if c["tipo"] in ("OffsetModule", "CurveModule")]
    if not ds or max(c.get("delta", 0) for c in ds) <= eps:
        return []
    ds = list(reversed(ds))
    if "PEGCRAFT_DEF_SINGRUPOS" in os.environ:
        return ds
    gs = [g for g in grupos(ds) if max(c.get("delta", 0) for c in g) > eps]   # un deformador en reposo (hijo) es la identidad
    return [n for g in gs for n in g]


# --- Avisos de valores NO modelados (12-11-2026; criterio de (doc interna omitida) asumir el valor modelado y avisar si difiere) ---
# El modelo asume lo que se midio en el banco: CurveModule INFINITE_INFLUENCE, localreferential=false (N/M Curve y N/M Offset del banco),
# OffsetModule con restingorientation 0, una sola cadena de entrada en el DeformationComposite (puerto 0) y KinematicOutput como transformacion rigida
# de la punta. OJO: un nodo recien creado en Harmony trae localreferential=true (escena de referencia, version 3): saldra el aviso. Nunca cambia el resultado.
AVISOS_NO_MODELADO = os.environ.get("PEGCRAFT_AVISOS_DEF", "1") not in ("0", "no", "off")


def avisos_no_modelados(censo, segs, tope=3):
    """censo: {ruta READ: cadena} (censo.py); segs: {ruta READ: segmentos activos} (segmentos()). Devuelve lista de avisos (una linea por categoria) sobre
    los nodos de las cadenas de los READ con deformacion activa que traen valores que el modelo no cubre. [] si todo esta dentro de lo modelado."""
    if not AVISOS_NO_MODELADO:
        return []
    cat = {}

    def nota(clave, nodo):
        cat.setdefault(clave, {})[nodo["ruta"]] = nodo

    activos_ = {}
    for r, sg_ in segs.items():
        for s in sg_:
            for n in s["nodos"]:
                activos_[n["ruta"]] = n
    for n in activos_.values():
        if n["tipo"] == "CurveModule" and n.get("influencetype", "INFINITE_INFLUENCE") != "INFINITE_INFLUENCE":
            nota("CurveModule con influencetype != INFINITE_INFLUENCE (radios de influencia no modelados)", n)
        if n.get("localreferential", "false") != "false":
            nota("%s con localreferential != false (referencial local no modelado; un nodo nuevo de Harmony lo trae en true)" % n["tipo"], n)
        if n["tipo"] == "OffsetModule" and abs(n.get("rep", {}).get("orientation") or 0.0) > 1e-9:
            nota("OffsetModule con restingorientation != 0 (orientacion de reposo del Offset no modelada con cadenas hijas)", n)
    for r in segs:
        for n in censo.get(r, []):
            if n["tipo"] == "DeformationCompositeModule":
                if len(n.get("puertos_usados", [])) > 1:
                    nota("DeformationCompositeModule con mas de un puerto de entrada usado (solo se sigue el puerto 0)", n)
                v = n.get("vals", {})
                if v.get("outputmatrixonly", "false") != "false" or v.get("outputselectedonly", "false") != "false" or v.get("outputkinematicchainselector", "RIGHTMOST") != "RIGHTMOST":
                    nota("DeformationCompositeModule en modo de salida distinto del modelado (outputmatrixonly/outputselectedonly/outputkinematicchainselector=RIGHTMOST)", n)
            elif n["tipo"] == "KinematicOutputModule" and n.get("fuera_de_defecto"):
                nota("KinematicOutputModule con parametros distintos del defecto %s (solo se modela la transformacion rigida de la punta)" % n["fuera_de_defecto"][:3], n)
    out = []
    for clave, nodos in cat.items():
        ej = ", ".join(sorted("/".join(x.split("/")[-2:]) for x in nodos)[:tope])
        out.append(f"deformadores no modelado: {len(nodos)} nodo(s) {clave} [{ej}{', ...' if len(nodos) > tope else ''}]")
    return out
