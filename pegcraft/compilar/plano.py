"""PLANO nativo: escritor (compilar) y lector (render-plano). Esquema y limites: (doc interna omitida)

Layout (un plano es un directorio, D-Fmt):
  plano/scene.json                         Scene externa minima + bloque `x-harmony` (camara, tamano, escena de origen)
  plano/anim/escena.tensores.safetensors   keys, key_interp, channel_offsets, exposure_runs, exposure_offsets, baked (F32 [F, P*12])
                                           + extensiones: exacto (F64 [F, P*8]), extras_idx (I32 [F, P]), cuadro_idx (I32 [F])
  plano/anim/escena.tensores.json          diccionario: canales, pistas de exposicion, piezas, columnas
  plano/anim/escena.x-harmony.json         sidecar `x-harmony/2` {modelo, origen, residual} (el lector acepta tambien `/1`, ver ESQUEMA_X_HARMONY
                                           para los campos del modelo; (doc interna omitida) «Implementacion del residual»)
  plano/harmony/{arbol.json.gz,manifiesto.json,mapa_ids.json}   residual: proyecto Harmony como arbol exacto (compilar/residual.py)
  plano/dibujos/<clave>.svg                activos (copiados del almacen; la clave es la del almacen)
  plano/fuentes.json                       clave -> .tvg de origen (ruta relativa a la escena + sha256), base/deformado
"""
import json, shutil, time, subprocess
from pathlib import Path
import numpy as np
from safetensors.numpy import save_file, load_file
from ..planofmt import comun
from ..planofmt.exportar import _nombres
from . import almacen
from . import avisos as avisos_mod
from . import residual as residual_mod

BK, EX = 12, 8     # columnas por pieza: baked (spec D-Tab) y exacto (f64: a b tx c d ty opacidad z)
STD = ("PositionX", "PositionY", "Rotation", "ScaleX", "ScaleY")
ESQUEMA_X_HARMONY = {
    "esquema": "x-harmony/1",
    "escena": "ruta del .xstage de origen", "camara": "{cx,cy,sx,sy,div} rejilla px/campos", "tamano": "[1920,1080]",
    "fps_supuesto": True, "frames": "[numeros de fotograma, mismo orden que las filas de los tensores]",
    "dibujos": "[clave de almacen]; baked[...,7] y exposure_runs[...,2] indexan esta lista",
    "piezas": "[{nombre, id (ruta del READ), puertos}] mismo orden que las columnas de baked/exacto",
    "extras": "[tabla de dicts unicos: razon, orden_lista, capas, recorte[{nodo,invertido,mattes[{id,dibujo(clave),matriz_campo,capas}]}], avisos, mezcla ('suma' = GLOW aditivo; ausente = composicion normal; planos anteriores al 12-11-2026 no la traen)]; "
              "extras_idx[f,p] indexa; -1 = pieza ausente en ese cuadro",
    "cuadros": "[tabla de dicts unicos {avisos, apilado}]; cuadro_idx[f] indexa",
    "formato": "(raiz del sidecar /2, desde 12-11-2026) {version:3, capas:[C1,(C0)], requiere:[], avisos:{CODIGO:n}}; ausente = plano anterior (PLANO_SIN_MEZCLA)",
}


def _jd(o):
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


ESQUEMA_2 = "x-harmony/2"


def cargar_sidecar(ruta):
    """-> (raw, plano). `raw` = dict tal cual esta en disco (con TODO campo desconocido, E5); `plano` = vista plana del modelo
    que usa el lector, para `x-harmony/1` (todo en la raiz) y `x-harmony/2` (modelo/origen/residual)."""
    raw = json.load(open(ruta, encoding="utf-8"))
    if raw.get("esquema") == ESQUEMA_2:
        flat = dict(raw["modelo"])
        flat["escena"] = (raw.get("origen") or {}).get("escena")
    else:
        flat = dict(raw)
    return raw, flat


FORMATO_VERSION = 3            # version del FORMATO (capas). El `esquema` del sidecar sigue en x-harmony/2: la cabecera es aditiva
CAPAS_SOPORTADAS = ("C0", "C1")  # C0 = residual exacto (plano/harmony), C1 = piezas horneadas (tensores + extras + SVG)
REQUIERE_SOPORTADO = ()          # tokens de `formato.requiere` que este lector entiende (R3: un plano que exige otro no se lee en silencio)


class PlanoNoSoportado(RuntimeError):
    pass


def cabecera_formato(modelo, residual):
    """`formato{version, capas, requiere, avisos}`: que capas trae el plano, que debe entender el lector (`requiere`, vacio = cualquier lector
    del formato 3 sirve) y el recuento de avisos por CODIGO estable (compilar/avisos.py; n = avisos distintos de las tablas del plano, no por cuadro)."""
    textos = [a for c in modelo["cuadros"] for a in c["avisos"]] + [a for e in modelo["extras"] for a in e.get("avisos", [])]
    return {"version": FORMATO_VERSION, "capas": ["C1"] + (["C0"] if residual else []), "requiere": [], "avisos": avisos_mod.recuento(textos)}


def reescribir_sidecar(ruta, destino=None):
    """Carga y vuelve a escribir el sidecar sin perder campos extra (E5)."""
    raw, _ = cargar_sidecar(ruta)
    Path(destino or ruta).write_bytes(json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def escribir(salida, xs, frames, J, REGS, residual=True, depurar_personal=False):
    """J = {frame: escena.json dict}; REGS = {frame: almacen.tomar_registro()}. Devuelve estadisticas.
    residual=True escribe ademas plano/harmony/ (arbol de origen exacto, manifiesto, mapa_ids)."""
    out = Path(salida); pl = out / "plano"; an = pl / "anim"; dd = pl / "dibujos"
    an.mkdir(parents=True, exist_ok=True); dd.mkdir(parents=True, exist_ok=True)
    esc = Path(xs).parent
    # --- tablas
    claves, ci = [], {}          # claves de dibujo en orden de aparicion
    fuentes = {}

    def clave_de(f, rel):
        r = REGS[f].get(Path(rel).name)
        if r is None:
            raise RuntimeError(f"f{f}: sin clave de almacen para {rel} (almacen desactivado?)")
        k = r["clave"]
        if k not in ci:
            ci[k] = len(claves); claves.append(k)
            tv = Path(r["tvg"]) if r.get("tvg") else None
            fuentes[k] = {"base": r["base"], "deformado": r["base"] != k,
                          "tvg": (str(tv.relative_to(esc)).replace("\\", "/") if tv and esc in tv.parents else (str(tv) if tv else None)),
                          "sha256_tvg": almacen.sha_archivo(tv) if tv and tv.is_file() else None}
        return k

    piezas, pi = [], {}
    for f in frames:
        for nom, p in zip(_nombres(J[f]["piezas"]), J[f]["piezas"]):
            if nom not in pi:
                pi[nom] = len(piezas); piezas.append({"nombre": nom, "id": p["id"], "puertos": p.get("puertos", [])})
    F, P = len(frames), len(piezas)
    baked = np.zeros((F, P * BK), np.float32); baked[:, 7::BK] = -1
    exacto = np.zeros((F, P * EX), np.float64)
    ex_idx = np.full((F, P), -1, np.int32); cu_idx = np.zeros(F, np.int32)
    extras, ei = [], {}; cuadros, cqi = [], {}
    for fi, f in enumerate(frames):
        j = J[f]
        for nom, p in zip(_nombres(j["piezas"]), j["piezas"]):
            o = pi[nom]
            (a, b, tx), (c, d, ty) = p["matriz_campo"]
            k = clave_de(f, p["dibujo"])
            baked[fi, o * BK:(o + 1) * BK] = [a, b, tx, c, d, ty, p["opacidad"], ci[k], p["orden"], p["z"], 1.0, 0.0]
            exacto[fi, o * EX:(o + 1) * EX] = [a, b, tx, c, d, ty, p["opacidad"], p["z"]]
            e = {kk: p[kk] for kk in ("razon", "orden_lista", "capas", "recorte", "avisos", "mezcla") if kk in p}
            if "recorte" in e:
                rec = []
                for r in e["recorte"]:
                    r = dict(r); r["mattes"] = [dict(mm, dibujo=clave_de(f, mm["dibujo"])) for mm in r.get("mattes", [])]
                    rec.append(r)
                e["recorte"] = rec
            s = _jd(e)
            if s not in ei:
                ei[s] = len(extras); extras.append(e)
            ex_idx[fi, o] = ei[s]
        c = {"avisos": j["avisos"], "apilado": j["apilado"]}; s = _jd(c)
        if s not in cqi:
            cqi[s] = len(cuadros); cuadros.append(c)
        cu_idx[fi] = cqi[s]
    # --- canales Hold estandar + exposicion (D-Tab), por pieza
    keys, interp, offs, chs = [], [], [0], []
    runs, eoffs, pistas = [], [0], []
    fr = list(frames)
    for nom, o in pi.items():
        pres = ex_idx[:, o] >= 0
        idx = [fi for fi in range(F) if pres[fi]]
        if not idx:
            continue
        ff = [fr[fi] for fi in idx]
        comps = [comun.descomponer([[baked[fi, o * BK + 0], baked[fi, o * BK + 1], baked[fi, o * BK + 2]],
                                    [baked[fi, o * BK + 3], baked[fi, o * BK + 4], baked[fi, o * BK + 5]]]) for fi in idx]
        for a_ in STD:
            for kf in comun.claves_hold(ff, [float(c[a_]) for c in comps])["keyframes"]:
                keys.append([kf["time"], kf["value"], 0, 0, 0, 0]); interp.append(0)
            offs.append(len(keys)); chs.append({"path": ["mundo", nom], "attribute": a_})
        for s_, n_, d_ in comun.runs(ff, [int(baked[fi, o * BK + 7]) for fi in idx]):
            runs.append([s_, n_, d_])
        eoffs.append(len(runs)); pistas.append({"path": ["mundo", nom], "level": piezas[o]["id"]})
    t = {"keys": np.array(keys, np.float64).reshape(-1, 6), "key_interp": np.array(interp, np.uint8),
         "channel_offsets": np.array(offs, np.uint32), "exposure_runs": np.array(runs, np.uint32).reshape(-1, 3),
         "exposure_offsets": np.array(eoffs, np.uint32), "baked": baked, "exacto": exacto, "extras_idx": ex_idx, "cuadro_idx": cu_idx}
    save_file(t, str(an / "escena.tensores.safetensors"))
    json.dump({"canales": chs, "pistas_exposicion": pistas, "dibujos": claves,
               "baked": {"frames": list(frames), "piezas": [p["nombre"] for p in piezas], "columnas": BK, "dtype": "F32",
                         "por_pieza": ["a", "b", "tx", "c", "d", "ty", "opacidad", "dibujo", "orden", "z", "visible", "relleno"]},
               "exacto": {"columnas": EX, "dtype": "F64", "por_pieza": ["a", "b", "tx", "c", "d", "ty", "opacidad", "z"]}},
              open(an / "escena.tensores.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    j0 = J[frames[0]]
    modelo = {"camara": j0["camara"], "tamano": j0["tamano"], "version_escena_json": j0["version"], "frames": list(frames),
              "dibujos": claves, "piezas": piezas, "extras": extras, "cuadros": cuadros}
    res = None; fps = 24.0
    if residual and Path(xs).is_file():
        res = residual_mod.escribir_harmony(pl, xs, depurar_personal)
        fps = res["fps"] or 24.0                       # LEIDO de project/options/framerate (E9), ya no supuesto
        side = {"esquema": ESQUEMA_2, "modelo": modelo, "origen": dict(res["origen"], conversor=almacen.version_conversor()),
                "residual": res["residual"]}
    else:                                              # sin residual: x-harmony/2 sin arbol (origen minimo, sin rutas absolutas)
        side = {"esquema": ESQUEMA_2, "modelo": modelo, "origen": {"escena": Path(xs).name, "conversor": almacen.version_conversor()}, "residual": None}
    side["formato"] = cabecera_formato(modelo, residual=res is not None)
    json.dump(side, open(an / "escena.x-harmony.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    ident = {"position": [0.0, 0.0], "pivot": [0.0, 0.0], "rotation": 0.0, "scale": [1.0, 1.0], "shear": [0.0, 0.0]}
    json.dump({"timing": {"frames": F, "frame_start": frames[0], "frame_start_global": frames[0], "fps": fps}, "camera": ident, "background": None,
               "props": [], "characters": [], "overlays": [], "library": {"path": "."},
               "x-harmony": {"esquema": ESQUEMA_2, "origen": {"escena": Path(xs).name}, "sidecar": "anim/escena.x-harmony.json"}},
              open(pl / "scene.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    for k in claves:
        shutil.copyfile(almacen.ruta(k), dd / f"{k}.svg")
    json.dump({"nota": "SVG = activo del almacen (derivado); el .tvg es la fuente (solo lectura)", "escena": Path(xs).name, "dibujos": fuentes},
              open(pl / "fuentes.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return {"piezas": P, "frames": F, "dibujos": len(claves), "extras": len(extras), "cuadros": len(cuadros),
            **({"residual": {k: v for k, v in res.items() if k not in ("origen", "residual")}} if res else {})}


class Plano:
    """Lector. Carga tensores y sidecar UNA vez; `cuadro(N)` arma el escena.json de un fotograma (sin .xstage ni .tvg)."""

    def __init__(self, directorio, exacto=True):
        t0 = time.perf_counter()
        self.dir = Path(directorio); pl = self.dir / "plano"
        self.T = load_file(str(pl / "anim" / "escena.tensores.safetensors"))
        self.raw, self.S = cargar_sidecar(pl / "anim" / "escena.x-harmony.json")      # acepta x-harmony/1 y /2
        self.fi = {f: i for i, f in enumerate(self.S["frames"])}
        self.svg = [str((pl / "dibujos" / f"{k}.svg").resolve()) for k in self.S["dibujos"]]
        self.usar_exacto = exacto and "exacto" in self.T
        no = [r for r in self.formato.get("requiere", []) if r not in REQUIERE_SOPORTADO]
        if no:
            raise PlanoNoSoportado(f"{self.dir}: el plano exige {no} (este lector entiende {list(REQUIERE_SOPORTADO)})")
        self.t_carga = time.perf_counter() - t0

    @property
    def formato(self):
        """Cabecera `formato` del sidecar. Sin ella (planos anteriores a la FASE 1) = {version:1|2 segun el esquema, capas:[C1(+C0)], requiere:[]}."""
        f = self.raw.get("formato")
        if f is not None:
            return f
        v2 = self.raw.get("esquema") == ESQUEMA_2
        return {"version": 2 if v2 else 1, "capas": ["C1"] + (["C0"] if v2 and self.raw.get("residual") else []), "requiere": [], "avisos": None, "sin_cabecera": True}

    def avisos_formato(self):
        """Avisos DEL PLANO (no de un cuadro) por codigo: {codigo: n|texto}. Los planos sin cabecera traen PLANO_SIN_MEZCLA (no fallan)."""
        f = self.formato; out = dict(f.get("avisos") or {})
        if f.get("sin_cabecera"):
            out["PLANO_SIN_MEZCLA"] = avisos_mod.EXTRA["PLANO_SIN_MEZCLA"]
        return out

    @property
    def frames(self):
        return self.S["frames"]

    def cuadro(self, n):
        i = self.fi[n]; S = self.S; P = len(S["piezas"])
        b = self.T["baked"][i].reshape(P, BK)
        e = self.T["exacto"][i].reshape(P, EX) if self.usar_exacto else None
        eidx = self.T["extras_idx"][i]
        vis = np.nonzero((eidx >= 0) & (b[:, 10] > 0))[0]
        vis = vis[np.argsort(b[vis, 8], kind="stable")]
        piezas = []
        for o in vis:
            m = e[o] if e is not None else b[o]
            ex = S["extras"][int(eidx[o])]
            p = {"id": S["piezas"][o]["id"], "orden": int(b[o, 8]), "orden_lista": ex.get("orden_lista"), "z": float(m[7] if e is not None else b[o, 9]),
                 "razon": ex.get("razon"), "puertos": S["piezas"][o]["puertos"]}
            if "capas" in ex:
                p["capas"] = ex["capas"]
            if "mezcla" in ex:
                p["mezcla"] = ex["mezcla"]
            if "recorte" in ex:
                p["recorte"] = [dict(r, mattes=[dict(mm, dibujo=self.svg[self._ix(mm["dibujo"])]) for mm in r["mattes"]]) for r in ex["recorte"]]
            p.update(dibujo=self.svg[int(b[o, 7])], matriz_campo=[[float(m[0]), float(m[1]), float(m[2])], [float(m[3]), float(m[4]), float(m[5])]],
                     opacidad=float(m[6]), avisos=ex.get("avisos", []))
            piezas.append(p)
        cu = S["cuadros"][int(self.T["cuadro_idx"][i])]
        return {"version": S["version_escena_json"], "escena": S["escena"], "fotograma": n, "camara": S["camara"], "tamano": S["tamano"],
                "avisos": cu["avisos"], "apilado": cu["apilado"], "piezas": piezas}

    def _ix(self, clave):
        if not hasattr(self, "_cix"):
            self._cix = {k: i for i, k in enumerate(S_dib(self.S))}
        return self._cix[clave]


def S_dib(S):
    return S["dibujos"]


def render_plano(directorio, frame, png, salida_json=None, flags=("--aa-gauss", "0.45", "--ss", "2", "--opacidad-grupo"), exacto=True):
    """Lee el cuadro del plano y lo pasa al crate. Devuelve tiempos {carga, cuadro, json, render} en segundos."""
    from ..medir.render import renderizar
    t = {}
    t0 = time.perf_counter(); P = Plano(directorio, exacto); t["carga"] = time.perf_counter() - t0
    t0 = time.perf_counter(); doc = P.cuadro(frame); t["cuadro"] = time.perf_counter() - t0
    rj = Path(salida_json) if salida_json else Path(png).with_suffix(".json")
    rj.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter(); json.dump(doc, open(rj, "w", encoding="utf-8"), ensure_ascii=False); t["json"] = time.perf_counter() - t0
    t0 = time.perf_counter(); renderizar(rj, png, "gris", list(flags)); t["render"] = time.perf_counter() - t0
    return t
