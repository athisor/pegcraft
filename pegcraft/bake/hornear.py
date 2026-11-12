"""Horneado de UN fotograma de una escena Harmony a <salida>/<nombre> (escena.json v2) + <salida>/dibujos/*.svg.

Unifica scripts/hornear.py y <datos de trabajo omitidos> Valores por omision = la mejor combinacion validada (PLANO fN):
conectores si, matriz_causal si (camara `metricas`), deformadores si, carpeta real, opacidad leer.
Para reproducir estados anteriores: conectores=no / matriz_causal=no (+ desfase) / deformadores=no. Ver (doc interna omitida)
Esquema escena.json: (doc interna omitida) §4 y (doc interna omitida)
"""
import sys, json, re
import numpy as np
import time as _time
from pathlib import Path
from . import apilado
from .. import config as _config
from ..lector import compat as L
from ..compilar import almacen as _alm
from .. import rutas as _rutas

CAMARAS = {
    "supuesta": {"cx": 960.0, "cy": 540.0, "sx": 60.0, "sy": 45.06},   # SUPUESTO: calibrado en PLANO
    "anisotropa": {"cx": 1095.0, "cy": 540.0, "sx": 52.921875, "sy": 44.685, "div": 155.125},   # ajuste del spike
    # MEDIDO (diag2, fondo solo): ECC afin contra Harmony da escala 1,0000/1,0001 y t<0,13 px => isotropa
    "iso": {"cx": 960.0, "cy": 540.0, "sx": 44.685, "sy": 44.685, "div": 155.125},
}


import os as _os
# Perspectiva: distancia camara-plano z=0 en unidades de Z. MEDIDO 12-11-2026 en PLANO (barrido d=6..32, optimo agudo en 12 = numberOfUnitsY/2): px_ok 0,83 -> 0,98.
# Por omision d = numberOfUnitsY/2 de la camara de la escena; PEGCRAFT_PERSP_D=0 la apaga, un numero fuerza d.
PERSP_ENV = _os.environ.get("PEGCRAFT_PERSP_D")


def convertir_tvg(tvg, esc, svg, gradientes=True):
    """.tvg -> SVG con el lector `pegcraft.tvg` (el lector .xstage no interviene). Con `gradientes` los rellenos Gradient salen como
    <linearGradient>/<radialGradient>. Devuelve (error, info): `error` es None si convirtio o el texto del error si no pudo (`TvgIlegible` en formas
    que no lee, p. ej. un .tvg «forma F=6»: el horneado omite SOLO esa pieza y avisa TVG_ILEGIBLE); `info` es el resultado de
    bake/gradientes.convertir o None. Si falla solo el post-proceso de gradientes se reintenta sin el."""
    from . import gradientes as _gr
    from ..tvg import TvgIlegible
    info = None
    try:
        try:
            info = _gr.convertir(str(tvg), str(esc), str(svg), con_gradientes=gradientes)
        except TvgIlegible:
            raise
        except Exception as ex:
            if not gradientes:
                raise
            info = {"gradientes": [], "avisos": [f"gradientes {Path(svg).name}: {ex}"]}
            _gr.convertir(str(tvg), str(esc), str(svg), con_gradientes=False)
        return None, info
    except Exception as ex:
        try:
            Path(svg).unlink()
        except OSError:
            pass
        return f"{type(ex).__name__}: {str(ex)[:160]}", None


def hornear(xs, f, salida, nombre="escena.json", excluir=None, grupo=None, conectores=True, exp="", z="global",
            apilado_modo="puertos", recortadas="omitir", camara=None, desfase=None, desfase_grupo="Top/Personaje/", carpeta="real",
            opacidad="leer", matriz_causal=True, deformadores=True, gradientes=True, glow_suma=True):
    """Hornea y devuelve (ruta del json, dict resumen). `desfase` = 'dx_sin_espejo,dx_espejo' en campos (DIAGNOSTICO) para las piezas
    cuya ruta empieza con `desfase_grupo`."""
    excluir = _config.EXCLUIR if excluir is None else excluir     # regex de rutas que no se dibujan; vacia = ninguna (PEGCRAFT_EXCLUIR)
    xs = str(xs); out = Path(salida); excl = re.compile(excluir, re.I) if excluir else None; esc = Path(xs).parent
    camara = camara or ("metricas" if matriz_causal else "iso")
    if matriz_causal or camara == "metricas":
        from . import matriz_causal as mc
    CAM = mc.camara(xs) if camara == "metricas" else CAMARAS[camara]

    elem = L.dibujos_de_reads(xs)
    ev = L.nodos_evaluados(xs, f)
    evd = {apilado.norm(n["ruta"]): (i, n) for i, n in enumerate(ev)}
    (out / "dibujos").mkdir(parents=True, exist_ok=True)
    avisos_glob = []; GRADS = {}; _ILEGIBLES = {}
    CAUSAL = mc.matrices(xs, f, list(evd), avisos_glob) if matriz_causal else None

    PERSP_D = float(PERSP_ENV) if PERSP_ENV not in (None, "") else (1080.0 / CAM["sy"]) / 2.0
    # PEG de la CAMARA (el que alimenta al nodo CAMERA, por tipo): None si no hay o es identidad -> el horneado queda IDENTICO. PEGCRAFT_CAMARA_PEG=no lo apaga.
    _av_cam = []
    CAMP = mc.camara_peg(xs, f, _av_cam) if matriz_causal else None
    for _a in _av_cam:
        print("AVISO " + _a, file=sys.stderr)
    avisos_glob.extend(_av_cam)
    CENSO, DEFORMADAS, ASPECTO_U = {}, {}, 4.0 / 3.0
    SEGS, PRES, POST = {}, {}, {}
    if deformadores:
        from . import deformadores as D, censo as _censo
        CENSO = _censo.censo(xs, f, re.escape(grupo) if grupo else ".")
        if not matriz_causal:
            from . import matriz_causal as mc
        ASPECTO_U = mc.aspecto(L.escena(xs))
        avisos_glob.append("deformadores: modelo de bake/deformadores.py (punto mas cercano de la curva de reposo); usar con matriz_causal")
        SEGS = {r: D.segmentos(cad) for r, cad in CENSO.items()}
        SEGS = {r: sg for r, sg in SEGS.items() if sg}
        _nm = D.avisos_no_modelados(CENSO, SEGS)   # valores que el modelo no cubre: solo avisos (escena.json y stderr), el render no cambia
        avisos_glob.extend(_nm)
        for _a in _nm:
            print("AVISO " + _a, file=sys.stderr)
        PRES, POST = {}, {}
        if SEGS and D.PRE:
            # la deformacion actua tras los PEG que hay entre el READ y ella: el SVG se deforma ya en ese espacio y la pieza conserva solo la matriz de DESPUES
            _pre = mc.pre_matrices(xs, f, {r: [x["pegs"] for x in sg] for r, sg in SEGS.items()})
            for r, ms in _pre.items():
                tot = np.eye(3)
                for M in ms:
                    tot = M @ tot
                PRES[r] = [M.tolist() for M in ms]
                POST[r] = np.linalg.inv(tot)

    if CAMP is not None:
        avisos_glob.append(f"camara: {CAMP['ruta']} x={CAMP['x']:g} y={CAMP['y']:g} z={CAMP['z']:g} escala={CAMP['escala']:g} d={CAMP['d']:g} aplicada a todas las piezas")
    meta = {"conectores": conectores, "matriz_causal": bool(matriz_causal), "deformadores": bool(deformadores), "gradientes": bool(gradientes)}
    if glow_suma:
        meta["glow_suma"] = True   # solo cambia el escena.json de planos con GLOW aditivo (hoy PLANO); glow_suma=False = estado anterior
    if conectores:
        e = {k: True for k in exp.split(",") if k and not k.startswith("apagar=")}
        for k in exp.split(","):
            if k.startswith("apagar="):
                e["apagar"] = k[7:].split("+")
        ap_r = apilado.orden_apilado_conectores(xs, f, evaluados=ev, exp=e, z_modo=z)
        secuencia = ap_r["orden"]
        meta.update(exp=exp, z=z, raiz=ap_r["raiz"], cortados_visibility=ap_r["cortados_visibility"], avisos=ap_r["avisos"])
        for _a in ap_r.get("efectos_avisos", []):   # BLEND_MODE / GLOW activos no modelados: solo avisos, el render no cambia
            print("AVISO " + _a, file=sys.stderr); avisos_glob.append(_a)
    elif apilado_modo == "puertos":
        ap_r = apilado.orden_apilado(xs, f, evaluados=ev)
        secuencia = ap_r["orden"]
        meta.update(modo=apilado_modo, recortadas=recortadas, raiz=ap_r["raiz"], excluidas=ap_r["excluidas"], mattes=ap_r["mattes"], avisos=ap_r["avisos"])
    else:
        secuencia = sorted(({"id": k, "z": n["z"], "recorrido": i, "razon": "lista", "puertos": [], "recorte": []}
                            for k, (i, n) in evd.items() if not n["apagado"]), key=lambda r: (r["z"], r["recorrido"]))
        meta.update(modo=apilado_modo, recortadas=recortadas)

    def mat(ruta):
        """Matriz mundo 2x3 en campos (causal si matriz_causal). `desfase` = DIAGNOSTICO, no es una correccion causal."""
        mt = evd[ruta][1]["matriz"]
        if CAUSAL is not None and ruta in CAUSAL:
            mt = CAUSAL[ruta]
        if ruta in POST:
            M3 = np.vstack([np.asarray(mt, float), [0.0, 0.0, 1.0]]) @ POST[ruta]
            mt = [[float(x) for x in fila] for fila in M3[:2].tolist()]
        if CAMP is not None and ruta in evd:
            # Camera-P (MEDIDO 12-11-2026, varios planos EPISODIO): zoom total s = d0 / (d + cz - z) / escala_cam (d0 = numberOfUnitsY/2, d = CAMERA offset.z; iguales salvo reencuadre); la traslacion de la camara (A*cx, cy) en campos
            # se resta ANTES de escalar: t' = s * (t - c). PEGCRAFT_PERSP_D=0 (sin perspectiva) deja solo 1/escala; un numero fuerza d.
            z_ = float(evd[ruta][1].get("z") or 0.0)
            st = mc.escala_camara(CAMP, z_, None if PERSP_ENV in (None, "") else float(PERSP_ENV))
            cx_, cy_ = mc.centro_camara(CAMP)   # (A*x, y) + cs*(A*offset.x, offset.y) de CAMERA
            mt = [[mt[0][0] * st, mt[0][1] * st, (mt[0][2] - cx_) * st], [mt[1][0] * st, mt[1][1] * st, (mt[1][2] - cy_) * st]]
        elif PERSP_D and ruta in evd:
            # perspectiva de la camara: un PEG con Z acumulada > 0 se acerca; escala alrededor del eje de la camara (origen en campos): s = d / (d - z)
            sp = PERSP_D / (PERSP_D - float(evd[ruta][1].get("z") or 0.0))
            mt = [[x * sp for x in fila] for fila in mt]
        if not desfase or not ruta.startswith(desfase_grupo):
            return mt
        d0, d1 = (float(v) for v in desfase.split(","))
        det = mt[0][0] * mt[1][1] - mt[0][1] * mt[1][0]
        return [[mt[0][0], mt[0][1], mt[0][2] + (d0 if det > 0 else d1)], mt[1]]

    def _opacidad(ruta):
        """MEDIDO (diag3): el atributo `opacity` del READ (0-100, def. 100) es la capa semitransparente."""
        if opacidad == "ignorar":
            return 1.0
        try:
            return float(L.evaluador(xs).valor(ruta, "opacity", f)) / 100.0
        except Exception as ex:
            avisos_glob.append(f"opacidad no leida {ruta}: {ex}"); return 1.0

    def dibujo(ruta):
        """Ruta relativa del SVG del dibujo expuesto (lo convierte si falta) o None con aviso. La carpeta del elemento puede no
        llamarse como el elemento (Personaje_Pelo1_1 -> elements\\Personaje_Pelo1.66)."""
        el = elem.get(ruta)
        if not el or not el[0] or ruta not in evd:
            avisos_glob.append(f"sin elemento: {ruta}"); return None
        n = evd[ruta][1]
        carp = el[1] if (carpeta == "real" and el[1]) else el[0]
        tvg = esc / "elements" / carp / f"{el[0]}-{n['dibujo']}.tvg"
        if not tvg.is_file():     # el .xstage puede nombrar otra capitalizacion que el disco (Linux)
            _t = _rutas.buscar(esc, "elements", carp, f"{el[0]}-{n['dibujo']}.tvg")
            if _t is None or not _t.is_file():
                avisos_glob.append(f"sin tvg {tvg.name} ({ruta})"); return None
            tvg = _t
        svg = out / "dibujos" / (f"{el[0]}-{n['dibujo']}.svg" if carp == el[0] else f"{carp}-{n['dibujo']}.svg")
        if tvg.name in _ILEGIBLES:   # ya fallo en este cuadro: misma pieza omitida sin volver a leerlo
            avisos_glob.append(f"TVG_ILEGIBLE {tvg.name} ({ruta}): {_ILEGIBLES[tvg.name]}; pieza omitida"); return None
        clave_b = None
        if not svg.exists():
            # ALMACEN DE ACTIVOS (compilar/almacen.py): mismo SVG, clave por contenido; la salida de este horneado no cambia
            clave_b = _alm.clave_base(tvg, esc, gradientes) if _alm.ACTIVO else None
            if clave_b and _alm.traer(clave_b, svg):
                pass
            else:
                _t0 = _time.perf_counter()
                _err, r_g = convertir_tvg(tvg, esc, svg, gradientes)
                if _err:
                    _ILEGIBLES[tvg.name] = _err
                    avisos_glob.append(f"TVG_ILEGIBLE {tvg.name} ({ruta}): {_err}; pieza omitida"); return None
                if gradientes and r_g:   # rellenos Gradient como <linearGradient> (bake/gradientes.py); sin ellos, el SVG base del lector .tvg
                    if r_g["gradientes"]:
                        GRADS[svg.name] = [g["nombre"] for g in r_g["gradientes"]]
                    avisos_glob.extend(f"{svg.name}: {a_}" for a_ in r_g["avisos"])
                _alm.STATS["t_convertir"] += _time.perf_counter() - _t0
                if clave_b:
                    _alm.guardar(clave_b, svg)
        elif _alm.ACTIVO:
            clave_b = _alm.clave_base(tvg, esc, gradientes)
        if clave_b:
            _alm.registrar(svg.name, clave_b, tvg=tvg)
        if deformadores:
            segs = SEGS.get(ruta)
            nodos = [segs, PRES.get(ruta)] if segs else None
            if nodos:
                svg_d = out / "dibujos" / f"{svg.stem}__def_{ruta.split('/')[-1]}{D.VAR and '_' + D.VAR}.svg"
                if ruta not in DEFORMADAS:
                    clave_d = _alm.clave_deformado(clave_b, nodos, ASPECTO_U, CAM["div"], D.VAR + D.MODELO) if clave_b else None
                    if clave_d and _alm.traer(clave_d, svg_d, deformado=True):
                        pass
                    else:
                        _t0 = _time.perf_counter()
                        D.deformar_svg(str(svg), str(svg_d), D.DeformadorSeg(segs, PRES.get(ruta) or [None] * len(segs), ASPECTO_U, CAM["div"]))
                        _alm.STATS["t_deformar"] += _time.perf_counter() - _t0
                        if clave_d:
                            _alm.guardar(clave_d, svg_d)
                    DEFORMADAS[ruta] = len(segs)
                    if clave_d:
                        _alm.registrar(svg_d.name, clave_d, clave_b, tvg=tvg)
                return f"dibujos/{svg_d.name}"
        return f"dibujos/{svg.name}"

    piezas = []; omitidas = 0
    for s in secuencia:
        ruta = s["id"]
        i, n = evd[ruta]
        if n["apagado"] or (excl and excl.search(ruta)) or (grupo and not ruta.startswith(grupo)):
            continue
        if not conectores and s["recorte"] and recortadas == "omitir":
            omitidas += 1; continue
        d = dibujo(ruta)
        if not d:
            continue
        p = {"id": ruta, "orden": len(piezas), "orden_lista": i, "z": s["z"], "razon": s["razon"], "puertos": s["puertos"]}
        if conectores:
            rec = []
            for c in s["recorte"]:
                ms = []
                for mm in c["mattes"]:
                    if mm["id"] in evd and not evd[mm["id"]][1]["apagado"]:
                        dm = dibujo(mm["id"])
                        if dm:
                            ms.append({"id": mm["id"], "dibujo": dm, "matriz_campo": mat(mm["id"]), "capas": mm["capas"],
                                       **({"blur": mm["blur"]} if mm.get("blur") else {})})
                rec.append({"nodo": c["nodo"], "invertido": c["invertido"], "mattes": ms})
            p.update(capas=s["capas"], recorte=rec)
        else:
            p["recorte"] = s["recorte"]
        p.update(dibujo=d, matriz_campo=mat(ruta), opacidad=_opacidad(ruta), avisos=n["avisos"])
        if glow_suma and s.get("glow"):
            p["mezcla"] = "suma"
            if s.get("glow_gain", 1.0) != 1.0:
                p["ganancia"] = s["glow_gain"]
            # rama READ -> ... -> GLOW: el crate la suma por canal (doc interna omitida), GLOW)
        piezas.append(p)
    meta["omitidas_por_recorte"] = omitidas
    meta["n_deformadas"] = len(DEFORMADAS)
    if gradientes:
        meta["dibujos_con_gradiente"] = GRADS
    ruta_json = out / nombre
    with open(ruta_json, "w", encoding="utf-8") as fh:
        json.dump({"version": 2 if conectores else 1, "escena": xs, "fotograma": f, "camara": CAM, "tamano": [1920, 1080],
                   "avisos": avisos_glob, "apilado": meta, "piezas": piezas}, fh, indent=1, ensure_ascii=False)
    resumen = {"json": str(ruta_json), "piezas": len(piezas), "con_recorte": sum(1 for p in piezas if p.get("recorte")),
               "omitidas": omitidas, "deformadas": len(DEFORMADAS), "avisos": len(avisos_glob)}
    return str(ruta_json), resumen
