"""Matriz mundo 2D de cada READ con la regla causal de unidades de Harmony (hornear.py --matriz-causal).

REGLA (MEDIDO en PLANO fN, (doc interna omitida) §8): las posiciones, pivotes y traslaciones del .xstage estan en CAMPOS de
una rejilla con aspecto `options/metrics` unitAspectRatioX:unitAspectRatioY (4:3): un campo en X mide A = 4/3 de un campo en Y. Los
dibujos (.tvg) y los giros viven en un espacio ISOTROPO. Componer giros/espejos con las x "en campos" (como Evaluador.nodos) deja
cada traslacion en x corta por 1/A: de ahi el desfase empirico (3,425 = 10,3054/3 de un nodo de espejo) y el error de cejas y espejos.
  x_iso = A * x_campo ; y_iso = y_campo                       (posicion, pivote, translate del static, offset/pivot del READ)
  PEG:    x' = P + c + R(rot) * K(sesgo) * S(escala) * (x - c)
  Static: x' = T + R * S * x  (inversa si `inverted`)
  cadena: M = lejano * ... * cercano * M_read
La matriz sale en campos-Y isotropos: sirve con la camara `iso` (sx = sy = 44,685 px por campo-Y; div = 155,125 tvg por campo-Y).
Sesgo: K = [[1, tan(sesgo)], [0, 1]] (signo SUPUESTO: ver SIGNO_SESGO). No evalua deformadores ni expresiones.
PointConstraint2 (dos puntos): SI, con la regla medida en PLANO (ver CONSTRAINTS); PEGCRAFT_CONSTRAINTS=0 o constraints=False lo apaga.
Uso: matrices(xstage, fotograma, [rutas Top/...], avisos) -> {ruta: [[a, b, tx], [c, d, ty]]}
CLI: python -I -m pegcraft.bake.matriz_causal <xstage> <fotograma> <regex>   (imprime la matriz causal y la de Evaluador.nodos)
"""
import sys, math, re, os
sys.dont_write_bytecode = True
import numpy as np
from sightread.lector import compat as L   # lector de escenas (paquete sightread/, subtree): Escena y Evaluador
from sightread.lector.resumen import buscar

# SUPUESTO (indicio debil): +1, K = [[1, tan], [0, 1]]. Unico caso (Ceja-P-P_1, 3,76 grados): cizalla residual ECC -0,117 (+1), -0,141 (0),
# -0,171 (-1); el IoU no distingue (0,799 / 0,796 / 0,796). 0 = ignorar el sesgo (como Evaluador.nodos, R4).
SIGNO_SESGO = float(os.environ.get("PEGCRAFT_SIGNO_SESGO", "1"))
ASPECTO = os.environ.get("PEGCRAFT_ASPECTO")                        # diagnostico: fuerza A (p. ej. 1 = sin la regla)


def aspecto(escena):
    """A = unitAspectRatioX / unitAspectRatioY de options/metrics de la `Escena` (4/3 si falta)."""
    if ASPECTO:
        return float(ASPECTO)
    mt = escena.raiz.find("options/metrics")
    try:
        return float(mt.get("unitAspectRatioX")) / float(mt.get("unitAspectRatioY"))
    except Exception:
        return 4.0 / 3.0


# Camara por omision cuando el .xstage NO trae `options/metrics` ni `pixelPerModelUnitForVectorLayers` (escenas armadas por herramienta, p. ej. PLANO:
# 43 KB, `options` solo con resolution/framerate/colorSpace). Antes: AttributeError (`mt` es None). Valores = los de TODAS las escenas del estudio con metrics
# (banco\\*, BG_PLANO, BG_PLANO: numberOfUnitsY=24, pixelPerModelUnitForVectorLayers=0,288) [dato: todas las escenas]. Que Harmony use ESTOS valores al abrir
# una escena sin metrics se comprueba comparando con su render (<datos de trabajo omitidos> <datos de trabajo omitidos>); si no hay `metrics`, se avisa.
UNIDADES_Y_DEFECTO = 24.0
PX_POR_UNIDAD_MODELO_DEFECTO = 0.288


def camara(xstage, ancho=1920, alto=1080, avisos=None):
    """Camara por omision (PEG de camara identidad) deducida de `options` del .xstage, sin ajuste:
    s = alto / numberOfUnitsY px por campo-Y (1080/24 = 45); div = s / pixelPerModelUnitForVectorLayers (45/0,288 = 156,25 tvg por campo-Y).
    MEDIDO en PLANO: el ajuste `iso` (44,685; 155,125) tiene el mismo s/div (0,28806) pero deja a Personaje corrida (-4,5; -3) px, porque
    su traslacion (13,74; -12,32 campos) se multiplica por s. El PEG de la camara se evalua aparte (`camara_peg`, aplicado en hornear.mat); el FOV no (de fabrica, 41,112)."""
    raiz = L.escena(xstage).raiz
    mt = raiz.find("options/metrics")
    pp = raiz.find("options/pixelPerModelUnitForVectorLayers")
    uy = float(mt.get("numberOfUnitsY")) if mt is not None and mt.get("numberOfUnitsY") else None
    ppv = float(pp.get("val")) if pp is not None and pp.get("val") else None
    if uy is None or ppv is None:
        faltan = [n for n, v in (("options/metrics@numberOfUnitsY", uy), ("options/pixelPerModelUnitForVectorLayers@val", ppv)) if v is None]
        msg = f"camara: el .xstage no trae {', '.join(faltan)}; se usa el valor del estudio ({UNIDADES_Y_DEFECTO:g} unidades Y, {PX_POR_UNIDAD_MODELO_DEFECTO} px/unidad modelo)"
        print("AVISO", msg, file=sys.stderr)
        if avisos is not None:
            avisos.append(msg)
        uy = UNIDADES_Y_DEFECTO if uy is None else uy
        ppv = PX_POR_UNIDAD_MODELO_DEFECTO if ppv is None else ppv
    s = alto / uy
    return {"cx": ancho / 2.0, "cy": alto / 2.0, "sx": s, "sy": s, "div": s / ppv}


def camara_peg(xstage, f, avisos=None, tol=1e-9):
    """PEG de la camara (12-11-2026): el que alimenta por cable al nodo CAMERA (por TIPO, no por el nombre «Camera-P»), evaluado en el fotograma f.
    Devuelve None si no hay CAMERA/PEG o si es la identidad (x=y=z=0, escala 1, rot 0): ahi el horneado NO cambia. Si no, un dict con
    ruta, x, y, z, escala, rot, d, d0, A, d_offset, d_unidades. PEGCRAFT_CAMARA_PEG=no lo apaga (devuelve None).
    MEDIDO (<datos de trabajo omitidos>, varios planos EPISODIO): zoom del fondo = d/(d+cz-z) / escala_cam; traslacion de camara multiplicada por ese factor.
    d = CAMERA offset.z (respaldo numberOfUnitsY/2) en el DENOMINADOR; d0 = numberOfUnitsY/2 en el numerador (`escala_camara`). En EPISODIO ambos valen 12.
    Si difieren (PLANO: 9,39) hay zoom de reencuadre d0/offset.z incluso con PEG identidad: se devuelve el dict y se avisa (inferencia). La ROTACION de la camara
    no se aplica (sin caso medido: siempre 0 en un rango de planos); si es != 0 se avisa. Solo evalua el PEG del cable: si cuelga de otros PEG
    o tiene escala x != y se avisa."""
    if os.environ.get("PEGCRAFT_CAMARA_PEG", "").strip().lower() in ("no", "0", "off", "false"):
        return None
    av = avisos if avisos is not None else []
    try:
        esc = L.escena(xstage)
        ev = L.evaluador(xstage)
        cams = [c for c in buscar(esc, tipos=["CAMERA"], apagados=False, max=20) if c.get("entradas")]
        if not cams:
            return None
        if len(cams) > 1:
            av.append(f"camara: {len(cams)} nodos CAMERA con entrada ({', '.join(c['ruta'] for c in cams)}); se usa {cams[0]['ruta']}")
        cam = cams[0]
        vec = esc.vecinos(cam["ruta"], "arriba", 1, True)               # [(ruta, tipo)]
        pegs = [v for v in vec if v[1] == "PEG"]
        if not pegs:
            if vec:
                av.append(f"camara: {cam['ruta']} se alimenta de {vec[0][0]} ({vec[0][1]}), no de un PEG; no se evalua")
            return None
        peg = pegs[0][0]
        padres = esc.vecinos(peg, "arriba", None, True)
        cuelga = [v[0] for v in padres if v[1] == "PEG"]
        fila = L.fila_peg(xstage, peg, f)
    except (Exception, SystemExit) as ex:
        av.append(f"camara: no se pudo leer el PEG de la camara ({type(ex).__name__}: {str(ex)[:120]}); se hornea sin el")
        return None
    x, y, z = fila["posicion.x"], fila["posicion.y"], fila["posicion.z"]
    ex_, ey_ = fila["escala.x"], fila.get("escala.y", fila["escala.x"])
    rot = fila.get("rotacion", 0.0) or 0.0
    if cuelga:
        av.append(f"camara: {peg} cuelga de otros PEG ({', '.join(cuelga)}); solo se evalua el propio")
    if abs(rot) > 1e-6:
        av.append(f"camara: {peg} gira {rot:g} grados; la rotacion de camara NO se aplica (no probada)")
    identidad = abs(x) < tol and abs(y) < tol and abs(z) < tol and abs(ex_ - 1.0) < tol and abs(ey_ - 1.0) < tol
    if not identidad and abs(ex_ - ey_) > 1e-6:
        av.append(f"camara: {peg} tiene escala x={ex_:g} != y={ey_:g}; se usa x (anisotropia de camara no probada)")
    mt = esc.raiz.find("options/metrics")
    try:
        d_un = float(mt.get("numberOfUnitsY")) / 2.0
    except Exception:
        d_un = UNIDADES_Y_DEFECTO / 2.0
    d_off = None
    try:
        v = float(ev.valor(cam["ruta"], "offset.z", f))
        d_off = v if v > 0 else None
    except (Exception, SystemExit):
        d_off = None
    # CAMERA offset.x/y (13-11-2026, correcciones3): desplazamiento del encuadre. PEGCRAFT_CAMARA_OFFSET=no lo apaga. Un valor ilegible cuenta como 0.
    ox = oy = 0.0
    if os.environ.get("PEGCRAFT_CAMARA_OFFSET", "").strip().lower() not in ("no", "0", "off", "false"):
        try:
            ox = float(ev.valor(cam["ruta"], "offset.x", f))
            oy = float(ev.valor(cam["ruta"], "offset.y", f))
        except (Exception, SystemExit):
            ox = oy = 0.0
    hay_offset = abs(ox) > tol or abs(oy) > tol
    if hay_offset:
        av.append(f"camara: CAMERA offset.x/y={ox:g}/{oy:g} desplaza el encuadre (x += cs*offset.x, y += cs*offset.y; inferencia, varios planos validados: PLANO, PLANO); "
                  f"rotacion de camara, offset.z animado, 2 CAMERA y otro FOV no probados con offset")
    d = d_off if d_off is not None else d_un
    reencuadre = d_off is not None and abs(d_off - d_un) > 1e-6
    if reencuadre:
        av.append(f"camara: zoom de reencuadre asumido (inferencia, 1 plano validado: PLANO): CAMERA offset.z={d_off:g} != numberOfUnitsY/2={d_un:g}; "
                  f"escala s = (numberOfUnitsY/2)/(offset.z+cz-z)/cs = zoom {d_un / d_off:.4g} en z=0")
    elif d_off is None and not identidad:
        av.append(f"camara: {cam['ruta']} sin offset.z; d = numberOfUnitsY/2 = {d_un:g}")
    if identidad and not reencuadre and not hay_offset:
        return None   # identidad (salvo rotacion, que no se aplica), offset.z = unidades/2 y offset.x/y = 0: el horneado queda IDENTICO
    return {"ruta": peg, "x": x, "y": y, "z": z, "escala": ex_, "rot": rot, "d": d, "d0": d_un, "A": aspecto(esc), "d_offset": d_off, "d_unidades": d_un, "ox": ox, "oy": oy}


def centro_camara(camp):
    """Traslacion de la camara en campos (cx, cy) que se resta antes de escalar: (A*(x + cs*ox), y + cs*oy), cs = escala de Camera-P, ox/oy = CAMERA offset.x/y.
    Sin offset.x/y (0) es (A*x, y) como antes. MEDIDO en varios planos (PLANO, PLANO): registro ORB residual ~ 0 y px_ok 0,57 -> 0,985 / 0,38 -> 0,987."""
    cs = camp["escala"]
    return camp["A"] * (camp["x"] + cs * camp.get("ox", 0.0)), camp["y"] + cs * camp.get("oy", 0.0)


def escala_camara(camp, z, d_forzado=None):
    """Zoom de la camara sobre una pieza a profundidad z (Z acumulada): s = d0 / (d + cz - z) / cs.
    d0 = numberOfUnitsY/2 (numerador: distancia de referencia del encuadre), d = CAMERA offset.z (denominador: distancia real camara-plano).
    Con offset.z = d0 (todos los planos del banco, 12 = 12) es la formula de antes d/(d+cz-z)/cs; con offset.z != d0 aparece el zoom de reencuadre
    d0/offset.z en z=0 (INFERENCIA, un plano: PLANO). `d_forzado` (PEGCRAFT_PERSP_D) fuerza d y d0 a la vez, como antes; 0 = sin perspectiva."""
    if d_forzado is not None:
        d, d0 = d_forzado, d_forzado
    else:
        d, d0 = camp["d"], camp.get("d0", camp["d"])
    return (d0 / (d + camp["z"] - z) if d else 1.0) / camp["escala"]


def _m(t, A, sesgo=0.0):
    """3x3 isotropa de un eslabon a partir de sus canales (en campos)."""
    sx, sy = t.get("escala.x", 1.0), t.get("escala.y", 1.0)
    ang = math.radians(t.get("rotacion", 0.0))
    co, si = math.cos(ang), math.sin(ang)
    R = np.array([[co, -si], [si, co]])
    K = np.array([[1.0, SIGNO_SESGO * math.tan(math.radians(sesgo))], [0.0, 1.0]])
    lin = R @ K @ np.diag([sx, sy])
    c = np.array([A * t.get("pivote.x", 0.0), t.get("pivote.y", 0.0)])
    P = np.array([A * t.get("posicion.x", 0.0), t.get("posicion.y", 0.0)])
    M = np.eye(3)
    M[:2, :2] = lin
    M[:2, 2] = P + c - lin @ c
    if t.get("invertido"):
        M = np.linalg.inv(M)
    return M


# PointConstraint2 ("Two-Points-Constraint"), MEDIDO en PLANO fN (<datos de trabajo omitidos>): con `active` = 0 en Harmony, su render
# coincide con el horneado sin constraint (0,992); con 50, la mitad del desplazamiento. Regla deducida de los datos (ajuste a +-3 px en 3 zonas):
# en el marco comun de sus dos entradas, A = pivote evaluado de la entrada del puerto 0, B = el de la entrada del puerto 1; A0, B0 = los
# mismos pivotes en reposo (sin la transformacion propia del peg). La salida estira a lo largo del eje A->B por L/L0 y escala la
# perpendicular por (L0/L)^(volumemod/100), lleva A0 a A y gira el eje de u0 a u. `active`/100 interpola con la identidad.
# Solo visto con transformtype=TRANSLATE, primaryport=RIGHT, balance=0, stretchmin/max=0: con otros valores se aplica igual y se avisa.
# El horneado anterior seguia solo el puerto 0 (scene_graph.root_peg) e ignoraba el resto. Bandera: PEGCRAFT_CONSTRAINTS=0 lo apaga.
CONSTRAINTS = os.environ.get("PEGCRAFT_CONSTRAINTS", "1") != "0"
# volumemin/volumemax: defecto 25/200 en todos los PointConstraint2 vistos (defaultValue del xstage). La regla NO los usa (sin clamp): fuera del defecto solo se avisa.
VOLUMEMIN_DEF, VOLUMEMAX_DEF = 25.0, 200.0


def _constraints_pc2(g, ev, A, fotograma, eslabon, avisos):
    """{ruta del PointConstraint2: W (3x3, mundo)} tal que la pieza que cuelga de el (por el puerto 0) pasa de M a W @ M.
    `g` = Escena, `ev` = Evaluador (modo paridad) de la misma escena."""
    out, raros = {}, []
    for pc, n in g.nodos.items():
        if n.tipo != "PointConstraint2":
            continue
        e0, e1 = g.fuente(pc, 0), g.fuente(pc, 1)
        if not (e0 and e1):
            continue
        e0, e1 = e0[0], e1[0]
        a = n.elem.find("attrs")

        def num(r, neutro, pc=pc, a=a):
            x = ev.valor(pc, r, fotograma) if a is not None and a.find(r) is not None else None
            return neutro if x is None else float(x)

        def txt(r, a=a):
            t = a.find(r) if a is not None else None
            return t.get("val") if t is not None else None
        act, vol = num("active", 100.0) / 100.0, num("volumemod", 75.0) / 100.0
        motivos = []
        if (txt("transformtype"), txt("primaryport")) != ("TRANSLATE", "RIGHT"):
            motivos.append(f"transformtype={txt('transformtype')} primaryport={txt('primaryport')}")
        for k, neutro in (("balance", 0.0), ("stretchmin", 0.0), ("stretchmax", 0.0), ("volumemin", VOLUMEMIN_DEF), ("volumemax", VOLUMEMAX_DEF)):
            v = num(k, neutro)
            if abs(v - neutro) > 1e-9:
                motivos.append(f"{k}={v:g}")
        if motivos:
            raros.append(f"{pc} ({', '.join(motivos)})")

        def padre(r):
            M = np.eye(3)
            for p in ev.cadena(r, "nunca"):
                M = eslabon(p) @ M
            return M
        Mp = padre(e0)
        if g.nodos[e0].tipo != "PEG" or g.nodos[e1].tipo != "PEG" or not np.allclose(Mp, padre(e1), atol=1e-6):
            raros.append(f"{pc} (entradas sin padre comun: no se aplica)")
            continue

        def piv(r):
            M = eslabon(r)
            t_el = g.nodos[r].elem.find("attrs/pivot")
            c = np.array([A * float(t_el.find("x").get("val", 0)) if t_el is not None else 0.0,
                          float(t_el.find("y").get("val", 0)) if t_el is not None else 0.0, 1.0])
            return c[:2], (M @ c)[:2], M
        A0, Ac, M0 = piv(e0)
        B0, Bc, _ = piv(e1)
        L0, Lc = np.linalg.norm(B0 - A0), np.linalg.norm(Bc - Ac)
        if L0 < 1e-9 or Lc < 1e-9:
            continue
        u0, u = (B0 - A0) / L0, (Bc - Ac) / Lc
        P0, P1 = np.array([u0, [-u0[1], u0[0]]]).T, np.array([u, [-u[1], u[0]]]).T
        F = np.eye(3)
        F[:2, :2] = P1 @ np.diag([Lc / L0, (L0 / Lc) ** vol]) @ P0.T
        F[:2, 2] = Ac - F[:2, :2] @ A0
        F = np.eye(3) + act * (F - np.eye(3))
        # la cadena ya trae Mp @ M0 (entrada del puerto 0): se cambia por Mp @ F
        out[pc] = Mp @ F @ np.linalg.inv(M0) @ np.linalg.inv(Mp)
    if raros:
        avisos.append(f"PointConstraint2 con parametros no medidos: {raros[:4]}")
    return out


def _m_read(g, ev, A, fotograma, ruta):
    """3x3 propia del READ (offset, escala, giro, pivote y sesgo de sus atributos); identidad si no tiene attrs. `g` = Escena, `ev` = Evaluador."""
    a = g.nodos[ruta].elem.find("attrs")
    if a is None:
        return np.eye(3)

    def v(r, neutro):
        x = ev.valor(ruta, r, fotograma) if a.find(r) is not None else None
        return neutro if not isinstance(x, (int, float)) else x
    s_sep = a.find("scale/separate")
    sep = s_sep is None or s_sep.get("val", "").lower() == "true"       # sin `scale/separate`: ejes separados
    sx, sy = (v("scale/x", 1.0), v("scale/y", 1.0)) if sep else (v("scale/xy", 1.0),) * 2
    rot = v("rotation/anglez", 0.0) if a.find("rotation/anglez") is not None else v("angle", 0.0)
    t = {"posicion.x": v("offset/x", 0.0), "posicion.y": v("offset/y", 0.0), "escala.x": sx, "escala.y": sy, "rotacion": rot,
         "pivote.x": v("pivot/x", 0.0), "pivote.y": v("pivot/y", 0.0)}
    return _m(t, A, v("skew", 0.0))


def pre_matrices(xstage, fotograma, segmentos):
    """Deformadores bajo PEGs: la deformacion actua en el espacio de DESPUES de las transformaciones que hay entre el READ (o el deformador
    anterior) y ella. segmentos = {ruta_read: [[ruta_peg, ...] (del mas cercano al mas lejano), ...]} (uno por deformador activo, del mas cercano al
    mas lejano) -> {ruta_read: [3x3 (campos-Y isotropos) por segmento]}. El primer segmento incluye la matriz propia del READ."""
    g, ev = L.escena(xstage), L.evaluador(xstage)
    A = aspecto(g)
    cache = {}

    def eslabon(p):
        if p not in cache:
            t = ev.canales(p, fotograma)
            cache[p] = _m(t, A, float(t.get("sesgo", 0.0) or 0.0))
        return cache[p]
    out = {}
    for ruta, segs in segmentos.items():
        ms = []
        for k, pegs in enumerate(segs):
            M = _m_read(g, ev, A, fotograma, ruta) if k == 0 else np.eye(3)
            for p in pegs:
                M = eslabon(p) @ M
            ms.append(M)
        out[ruta] = ms
    return out


def matrices(xstage, fotograma, rutas, avisos=None, constraints=None):
    avisos = avisos if avisos is not None else []
    constraints = CONSTRAINTS if constraints is None else constraints
    g, ev = L.escena(xstage), L.evaluador(xstage)
    A = aspecto(g)
    cache, out, con_sesgo, deform = {}, {}, set(), 0

    def eslabon(p):
        if p not in cache:
            t = ev.canales(p, fotograma)
            sg = float(t.get("sesgo", 0.0) or 0.0)
            if abs(sg) > 1e-6:
                con_sesgo.add(p)
            cache[p] = _m(t, A, sg)
        return cache[p]

    PC2 = _constraints_pc2(g, ev, A, fotograma, eslabon, avisos) if constraints else {}
    con_pc2 = 0
    for ruta in rutas:
        if ruta not in g.nodos:
            continue
        M = np.eye(3)
        for p in ev.cadena(ruta, "si_transforma"):           # del mas cercano al mas lejano
            M = eslabon(p) @ M
        if PC2:                                               # constraints del camino por el puerto 0, del mas cercano al mas lejano
            cur, visto, Ws = g.fuente(ruta, 0), set(), []
            while cur is not None and cur[0] not in visto:
                visto.add(cur[0])
                if cur[0] in PC2:
                    Ws.append(PC2[cur[0]])
                cur = g.fuente(cur[0], 0)
            for W in Ws:
                M = W @ M
            con_pc2 += bool(Ws)
        if g.nodos[ruta].tipo == "READ":
            M = M @ _m_read(g, ev, A, fotograma, ruta)
        if any("Module" in g.nodos[s].tipo for s, _ in g.fuentes(ruta, 0)):
            deform += 1
        out[ruta] = [[round(float(x), 6) for x in fila] for fila in M[:2].tolist()]
    avisos.append(f"matriz causal: aspecto de unidad {A:.5f}; sesgo aplicado en {len(con_sesgo)} PEG {sorted(con_sesgo)[:4]}; "
                  f"{deform} READ cuelgan de un deformador (no evaluado); PointConstraint2: {len(PC2)} evaluados, {con_pc2} READ bajo ellos"
                  + ("" if constraints else " (apagado)"))
    return out


if __name__ == "__main__":
    xs, f, rx = sys.argv[1], int(sys.argv[2]), re.compile(sys.argv[3], re.I)
    ev = L.nodos_evaluados(xs, f)
    rutas = [L.norm(n["ruta"]) for n in ev if rx.search(n["ruta"])]
    av = []
    mc = matrices(xs, f, rutas, av)
    for n in ev:
        r = L.norm(n["ruta"])
        if r in mc:
            print(r, "\n  causal ", mc[r], "\n  evaluar", n["matriz"])
    print(av)
