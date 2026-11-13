"""Analisis de UNA escena: que hay en ella que pegcraft no conoce o no soporta.

Barato a proposito: lee la estructura completa (nodos, columnas, atributos), evalua una MUESTRA de fotogramas (por omision primero, medio y ultimo) con las mismas
etapas del horneado (evaluador, apilado de conectores, matriz causal, censo de deformadores) pero SIN convertir SVG, y decodifica una vez cada .tvg y cada
.plt que esos fotogramas usan. Nada se escribe. Una etapa que revienta no detiene las demas: queda como `error_lectura`.

`analizar_escena(xstage, fotogramas="muestra") -> dict` con `hallazgos`: lista de {categoria, clave, n, nodos[], fotogramas[], ejemplo}.
`clave` es estable entre escenas (numeros y rutas normalizados), para poder agrupar un lote.
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True

MAX_TVG = 600            # tope de .tvg distintos que se decodifican por escena (la lectura de dibujos es lo mas caro)
MAX_EJEMPLOS = 6

# Tipos cuyos atributos se leen por fuera de Escena.atributo_elem (censo/matriz causal hacen `elem.find` directo): no se les puede decir «no leido».
LEIDOS_DIRECTO = frozenset({"OffsetModule", "CurveModule", "DeformationCompositeModule", "KinematicOutputModule", "TransformationSwitch", "PointConstraint2"})
# Avisos que son informacion y no un limite del sistema.
_INFORMATIVOS = (r"^composite apagado", r"^matriz causal:", r"^deformadores: modelo", r"^camara: \S+ x=", r"piezas cambian de lugar por Z", r"^puerto_grupo",
                 r"tiene cutter/matte")


# ------------------------------------------------------------------ normalizacion
_RX_RUTA = re.compile(r"(?:\.{0,2}[A-Za-z]:)?[\w\-.]*(?:[\\/][\w\-.]+)+")
_RX_NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:e-?\d+)?(?![\w])")
_RX_HEX = re.compile(r"\b[0-9a-fA-F]{16}\b")
_RX_CORCH = re.compile(r"\[[^\]]*\]")


def normalizar(texto: str, largo: int = 110) -> str:
    """Texto sin rutas de nodo, ids hex, numeros ni listas de ejemplos: la parte que no cambia entre escenas."""
    t = str(texto).replace("\n", " ")
    t = _RX_CORCH.sub("[...]", t)
    t = _RX_RUTA.sub("<ruta>", t)
    t = _RX_HEX.sub("<id>", t)
    t = _RX_NUM.sub("N", t)
    t = re.sub(r"\s+", " ", t).strip(" :;,")
    return t[:largo]


class _Acum:
    """Acumula hallazgos de una escena agrupados por (categoria, clave)."""

    def __init__(self):
        self.d: dict[tuple[str, str], dict] = {}

    def add(self, categoria: str, clave: str, nodo: str | None = None, f: int | None = None, ejemplo: str | None = None, n: int = 1):
        h = self.d.setdefault((categoria, clave), {"nodos": [], "fotogramas": set(), "ejemplo": None, "extra": 0})
        if nodo is not None and nodo not in h["nodos"]:
            h["nodos"].append(nodo)
        if nodo is None:
            h["extra"] = max(h["extra"], n)
        if f is not None:
            h["fotogramas"].add(f)
        if h["ejemplo"] is None and ejemplo:
            h["ejemplo"] = str(ejemplo)[:300]

    def lista(self) -> list[dict]:
        out = []
        for (cat, clave), h in sorted(self.d.items()):
            out.append({"categoria": cat, "clave": clave, "n": max(len(h["nodos"]), h["extra"], 1), "nodos": h["nodos"][:MAX_EJEMPLOS],
                        "fotogramas": sorted(h["fotogramas"])[:12], "ejemplo": h["ejemplo"]})
        return out


def _corto(ex: BaseException) -> str:
    """Solo el TIPO de la excepcion: la clave del hallazgo no lleva el mensaje (puede traer rutas o nombres); el mensaje va en `ejemplo`."""
    return type(ex).__name__


class _Etapa:
    """`with etapa("nombre"):` mide el tiempo y convierte cualquier excepcion (incluido SystemExit, que usa el apilado) en un hallazgo error_lectura."""

    def __init__(self, ac: _Acum, tiempos: dict, nombre: str, f: int | None = None):
        self.ac, self.t, self.nombre, self.f = ac, tiempos, nombre, f

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, tp, ex, tb):
        self.t[self.nombre] = self.t.get(self.nombre, 0.0) + time.perf_counter() - self.t0
        if ex is None or isinstance(ex, KeyboardInterrupt):
            return False
        self.ac.add("error_lectura", f"{self.nombre}: {_corto(ex)}", f=self.f, ejemplo=f"{type(ex).__name__}: {ex}")
        return True


# ------------------------------------------------------------------ avisos de bake -> hallazgos
def _desde_aviso(ac: _Acum, texto: str, f: int | None, fuente: str = "") -> None:
    """Clasifica un aviso de texto libre del horneado. Los informativos se descartan; lo que no encaja queda en `aviso_otro`."""
    t = str(texto)
    if any(re.search(p, t) for p in _INFORMATIVOS):
        return
    m = re.match(r"^deformadores no modelado: \d+ nodo\(s\) (.*?) \[(.*)\]$", t)
    if m:
        for ej in [x.strip() for x in m.group(2).split(",") if x.strip() and x.strip() != "..."] or [None]:
            ac.add("deformador_no_soportado", normalizar(m.group(1)), nodo=ej, f=f, ejemplo=t)
        return
    m = re.match(r"^BLEND_MODE_MODULE activo \((.*?)\) en (\S+):", t)
    if m:
        ac.add("efecto_no_soportado", f"BLEND_MODE_MODULE {m.group(1)}", nodo=m.group(2), f=f, ejemplo=t); return
    m = re.match(r"^GLOW activo con (radio=\S+|radio no legible[^)]*\)?) en (\S+):", t)
    if m:
        ac.add("efecto_no_soportado", "GLOW con radio > 0 o ilegible (desenfoque no modelado)", nodo=m.group(2), f=f, ejemplo=t); return
    if t.startswith("GLOW multiples"):
        ac.add("efecto_no_soportado", "GLOW multiples (orden y suma no validados)", f=f, ejemplo=t); return
    m = re.match(r"^(\S+) tratado como transparente \(efecto no aplicado\): (\S+)", t)
    if m:
        ac.add("efecto_no_soportado", f"{m.group(1)} tratado como transparente", nodo=m.group(2), f=f, ejemplo=t); return
    if re.match(r"^(DeformationCompositeModule en el camino|cutter sin matte|READ alcanzado por dos|recorrido demasiado|sin WRITE/DISPLAY|\S+ con \d+ entradas|excluida)", t):
        ac.add("apilado_aviso", normalizar(t), nodo=(re.search(r"(Top/\S+)", t) or [None, None])[1], f=f, ejemplo=t); return
    if re.match(r"^(PointConstraint2 con parametros|camara:|sesgo|/.*sesgo|sesgo en la cadena)", t) or "sesgo" in t and "considera" in t:
        ac.add("matriz_aviso", normalizar(t), f=f, ejemplo=t); return
    if re.match(r"^(opacidad no leida|gradiente|gradientes )", t):
        ac.add("plt_no_reconocido", normalizar(t), f=f, ejemplo=t); return
    ac.add("aviso_otro", normalizar(t), f=f, ejemplo=f"[{fuente}] {t}")


# ------------------------------------------------------------------ espia de atributos
@contextlib.contextmanager
def _espiar():
    """Registra cada `Escena.atributo_elem(ruta, *claves)` (por ahi pasan atributo(), el evaluador y los conectores)."""
    from sightread.lector.escena import Escena
    leidos: dict[str, set[str]] = defaultdict(set)
    orig = Escena.atributo_elem

    def espia(self, ruta, *claves):
        if claves:
            try:
                leidos[self.ruta_norm(ruta)].add("/".join(str(c).strip("/") for c in claves))
            except Exception:  # noqa: BLE001 - el espia nunca debe romper la lectura
                pass
        return orig(self, ruta, *claves)

    Escena.atributo_elem = espia
    try:
        yield leidos
    finally:
        Escena.atributo_elem = orig


def _hojas(el, pre=""):
    for ch in el:
        p = f"{pre}/{ch.tag}" if pre else ch.tag
        if ch.get("val") is not None or ch.get("col") is not None:
            yield p, ch
        yield from _hojas(ch, p)


def _fuera_de_defecto(ch) -> bool:
    if ch.get("col"):
        return True
    d, v = ch.get("defaultValue"), ch.get("val")
    if d is None or v is None:
        return False
    try:
        return abs(float(v) - float(d)) > 1e-9
    except ValueError:
        return v != d


TRANSFORMADORES_EVALUADOS = frozenset({"PEG", "READ", "StaticConstraint"})     # sus canales los lee el Evaluador, y solo de los nodos que llega a evaluar


def _atributos_no_leidos(ac: _Acum, e, leidos: dict[str, set[str]], evaluados: set[str]) -> None:
    """`evaluados`: rutas cuya especificacion de canales armo el Evaluador (un READ sin dibujo en la muestra no se evalua aunque otra etapa lo toque)."""
    for ruta, n in e.nodos.items():
        if n.tipo in LEIDOS_DIRECTO:
            continue
        lei = leidos.get(ruta)
        if not lei:            # nodo que ninguna etapa visito (fuera de las cadenas de los READ): no se juzga
            continue
        if n.tipo in TRANSFORMADORES_EVALUADOS and ruta not in evaluados:
            continue
        a = n.elem.find("attrs")
        if a is None:
            continue
        for p, ch in _hojas(a):
            if not _fuera_de_defecto(ch):
                continue
            if any(p == r or p.startswith(r + "/") or r.startswith(p + "/") for r in lei):
                continue
            ac.add("atributo_no_leido", f"{n.tipo}.{p}", nodo=ruta, ejemplo=f"val={ch.get('val')} defaultValue={ch.get('defaultValue')} col={ch.get('col')}")


# ------------------------------------------------------------------ fotogramas
def elegir_fotogramas(n: int, spec="muestra") -> list[int]:
    n = max(1, int(n))
    if spec in (None, "", "muestra"):
        return sorted({1, (n + 1) // 2, n})
    if spec == "todos":
        return list(range(1, n + 1))
    if isinstance(spec, (list, tuple)):
        return [f for f in sorted({int(x) for x in spec}) if 1 <= f <= n]
    s = str(spec)
    if ":" in s:
        a, b = s.split(":", 1)
        return list(range(max(1, int(a)), min(n, int(b)) + 1))
    return [f for f in sorted({int(x) for x in s.split(",") if x.strip()}) if 1 <= f <= n]


# ------------------------------------------------------------------ analisis
def analizar_escena(xstage, fotogramas="muestra", max_tvg: int = MAX_TVG) -> dict:
    """Analiza una escena. No lanza (salvo KeyboardInterrupt): lo que falla queda como hallazgo `error_lectura`."""
    from ..bake import apilado, censo as C, deformadores as D, matriz_causal as mc
    from ..compilar.avisos import codigo as _codigo   # noqa: F401 - disponible para quien quiera el codigo estable de un aviso de bake
    from sightread.lector import compat as L
    from sightread.lector.escena import limpiar_cache
    from sightread.lector.columnas.opaca import ColOpaca, TIPOS_CONOCIDOS_OPACOS

    t_ini = time.perf_counter()
    ac, T = _Acum(), {}
    xs = str(xstage)
    info = {"escena": xs, "n_fotogramas": None, "fotogramas": [], "nodos": None}
    # `sensibles`: nombres propios de la escena (carpetas, archivo, nodos, columnas, elementos). No va al log; sirve para depurar el log compartible.
    sensibles: set[str] = set(Path(xs).parts) | {Path(xs).stem}
    limpiar_cache()
    L._EVALUADORES.clear()
    err = io.StringIO()
    with contextlib.redirect_stderr(err), _espiar() as leidos:
        e = None
        with _Etapa(ac, T, "abrir"):
            e = L.escena(xs)
            info["n_fotogramas"] = e.n_fotogramas
            info["nodos"] = len(e.nodos)
            info["harmony"] = " build ".join(x for x in (e.raiz.get("version"), e.raiz.get("build")) if x) or None     # version de Harmony que guardo la escena
            for n in e.nodos.values():
                sensibles.add(n.nombre); sensibles.update(n.ruta.split("/"))
            sensibles.update(str(c) for c in e.columnas)
            for el in e.elementos.values():
                sensibles.update(x for x in (el.nombre, el.carpeta) if x)
            for a in e.avisos:
                ac.add("escena_aviso", normalizar(a), ejemplo=a)
        if e is None:
            info["sensibles"] = sorted(sensibles)
            return _cerrar(info, ac, T, t_ini)

        # --- estructura: tipos de nodo
        with _Etapa(ac, T, "tipos"):
            for ruta, n in e.nodos.items():
                if n.tipo not in apilado.TIPOS_MODELADOS:
                    ac.add("nodo_tipo_no_soportado", n.tipo, nodo=ruta, ejemplo=f"{n.tipo} en {ruta}")
        # --- estructura: columnas (se construyen todas)
        with _Etapa(ac, T, "columnas"):
            for a in e.columnas.avisos:
                ac.add("columna_aviso", normalizar(a), ejemplo=a)
            for nombre in list(e.columnas):
                try:
                    col = e.columnas[nombre]
                except Exception as ex:  # noqa: BLE001
                    ac.add("error_lectura", f"columna: {_corto(ex)}", nodo=nombre, ejemplo=str(ex)); continue
                if isinstance(col, ColOpaca):
                    motivo = f" ({TIPOS_CONOCIDOS_OPACOS[col.tipo]})" if col.tipo in TIPOS_CONOCIDOS_OPACOS else ""
                    motivo_txt = re.sub(r"\((\w+): [^)]*\)", r"(\1)", "; ".join(col.avisos))     # «(ValueError: mensaje)» -> «(ValueError)»
                    extra = "" if (col.tipo in TIPOS_CONOCIDOS_OPACOS and not col.avisos) else ": " + normalizar(motivo_txt)
                    ac.add("columna_opaca", f"tipo {col.tipo}{motivo}{extra}", nodo=nombre, ejemplo="; ".join(col.avisos) or None)

        # --- fotogramas
        try:
            fr = elegir_fotogramas(e.n_fotogramas, fotogramas)
        except ValueError:
            fr = elegir_fotogramas(e.n_fotogramas, "muestra")
        info["fotogramas"] = fr
        dibujos: dict[tuple[str, str], str] = {}     # (ruta READ normalizada, dibujo) -> ruta del READ
        elem = {}
        with _Etapa(ac, T, "dibujos_de_reads"):
            elem = L.dibujos_de_reads(xs)
        for f in fr:
            ev, ap = [], None
            with _Etapa(ac, T, "evaluar", f):
                ev = L.nodos_evaluados(xs, f)
                for r in ev:
                    for a in r.get("avisos", []):
                        _desde_aviso(ac, a, f, "evaluador")
            evd = {apilado.norm(r["ruta"]): r for r in ev}
            with _Etapa(ac, T, "apilado", f):
                ap = apilado.orden_apilado_conectores(xs, f, evaluados=ev)
                for a in ap["avisos"] + ap.get("efectos_avisos", []):
                    _desde_aviso(ac, a, f, "apilado")
            with _Etapa(ac, T, "matriz_causal", f):
                av: list[str] = []
                mc.matrices(xs, f, list(evd), av)
                av_c: list[str] = []
                mc.camara_peg(xs, f, av_c)
                for a in av + av_c:
                    _desde_aviso(ac, a, f, "matriz_causal")
            with _Etapa(ac, T, "deformadores", f):
                cen = C.censo(xs, f, ".")
                segs = {r: D.segmentos(cad) for r, cad in cen.items()}
                segs = {r: sg for r, sg in segs.items() if sg}
                for a in D.avisos_no_modelados(cen, segs):
                    _desde_aviso(ac, a, f, "deformadores")
            dibujados = [x["id"] for x in ap["orden"]] if ap else [k for k, r in evd.items() if not r["apagado"]]
            with _Etapa(ac, T, "opacidad", f):
                evl = L.evaluador(xs)
                for k in dibujados:
                    evl.valor(k, "opacity", f)         # como hace hornear: asi el espia ve que se lee
            for k in dibujados:
                r = evd.get(k)
                if r and r.get("dibujo") is not None:
                    dibujos.setdefault((k, str(r["dibujo"])), r["ruta"])
        with _Etapa(ac, T, "evaluador_avisos"):
            for a in L.evaluador(xs).avisos:
                _desde_aviso(ac, a, None, "evaluador")
            for nombre in list(e.columnas):            # avisos que las columnas anotan al evaluarse
                col = e.columnas[nombre]
                if not isinstance(col, ColOpaca):
                    for a in col.avisos:
                        ac.add("columna_aviso", normalizar(a), nodo=nombre, ejemplo=a)
        with _Etapa(ac, T, "atributos"):
            _atributos_no_leidos(ac, e, leidos, set(getattr(L.evaluador(xs), "_spec", {})))
        # --- dibujos y paletas
        with _Etapa(ac, T, "tvg_plt"):
            _dibujos_y_paletas(ac, T, xs, e, elem, dibujos, max_tvg)
    info["sensibles"] = sorted(sensibles)
    return _cerrar(info, ac, T, t_ini)


def _cerrar(info: dict, ac: _Acum, T: dict, t_ini: float) -> dict:
    info["hallazgos"] = ac.lista()
    info["t_s"] = round(time.perf_counter() - t_ini, 3)
    info["etapas_s"] = {k: round(v, 3) for k, v in T.items()}
    return info


def _dibujos_y_paletas(ac: _Acum, T: dict, xs: str, e, elem: dict, dibujos: dict, max_tvg: int) -> None:
    from sightread import plt as _plt, rutas as _rutas
    from sightread.tvg import TvgIlegible
    from ..bake import apilado, gradientes as G
    esc = Path(xs).parent
    # paletas de la escena
    declaradas = _plt.paletas(esc)
    textura_ids: set[str] = set()
    grad_ids: set[str] = set()
    for p in declaradas:
        if not p["declarada"]:
            continue
        if p["archivo"] is None:
            ac.add("paleta_faltante", "paleta declarada sin archivo", nodo=p["clave"], ejemplo=str(p))
            continue
        try:
            pal = _plt.leer(Path(p["archivo"]).read_bytes())
        except _plt.PaletaIlegible as ex:
            ac.add("plt_no_reconocido", f"paleta ilegible: {normalizar(ex)}", nodo=p["clave"]); continue
        except OSError as ex:
            ac.add("error_lectura", f"plt: {_corto(ex)}", nodo=p["clave"]); continue
        if pal.conteo.get("Desconocida"):
            ac.add("plt_no_reconocido", "linea de paleta desconocida", nodo=p["clave"], ejemplo=f"{pal.conteo['Desconocida']} linea(s) en {p['clave']}", n=pal.conteo["Desconocida"])
        for c in pal.colores():
            if c["tipo"] == "Texture":
                textura_ids.add(c["id"])
            elif c["tipo"] == "Gradient":
                grad_ids.add(c["id"])
    # dibujos
    vistos: dict[Path, tuple] = {}
    for (k, dib), ruta in sorted(dibujos.items()):
        el = elem.get(k)
        if not el or not el[0]:
            ac.add("dibujo_faltante", "READ dibujado sin elemento", nodo=ruta); continue
        carp = el[1] or el[0]
        tvg = esc / "elements" / carp / f"{el[0]}-{dib}.tvg"
        if not tvg.is_file():
            t2 = _rutas.buscar(esc, "elements", carp, f"{el[0]}-{dib}.tvg")
            if t2 is None or not t2.is_file():
                ac.add("dibujo_faltante", "tvg inexistente en disco", nodo=ruta, ejemplo=str(tvg.name))
                continue
            tvg = t2
        if tvg in vistos:
            continue
        if len(vistos) >= max_tvg:
            ac.add("aviso_otro", f"analisis: tope de {max_tvg} .tvg alcanzado (el resto no se decodifico)")
            break
        t0 = time.perf_counter()
        try:
            m, _, _ = G.decodificar(tvg, esc)
        except TvgIlegible as ex:
            ac.add("tvg_no_reconocido", f"ilegible: {normalizar(ex)}", nodo=ruta, ejemplo=f"{tvg.name}: {ex}")
            vistos[tvg] = ()
            continue
        except Exception as ex:  # noqa: BLE001
            ac.add("error_lectura", f"tvg: {_corto(ex)}", nodo=ruta, ejemplo=f"{tvg.name}: {type(ex).__name__}: {ex}")
            vistos[tvg] = ()
            continue
        T["tvg_decodificar"] = T.get("tvg_decodificar", 0.0) + time.perf_counter() - t0
        vistos[tvg] = (m,)
        for a in m.get("avisos", []):
            ac.add("tvg_no_reconocido", normalizar(a), nodo=ruta, ejemplo=f"{tvg.name}: {a}")
        # colores usados por los trazos que no se pueden resolver a un RGBA
        usados = set()
        for arte in m["artes"].values():
            for capa in arte["capas"]:
                for tz in capa["trazos"]:
                    est = tz.get("estilo") or {}
                    usados.update(x for x in (est.get("der"), est.get("izq"), est.get("lapiz")) if x)
        for cid in sorted(usados):
            c = m["paleta"].get(cid)
            if c is None:
                ac.add("paleta_faltante", "color usado por un trazo sin entrada en la paleta", nodo=ruta, ejemplo=f"{tvg.name}: {cid}")
            elif isinstance(c, dict) and not c.get("rgba") and cid not in grad_ids:
                clave = "textura usada (no se dibuja)" if cid in textura_ids else "relleno sin color resoluble (degradado o textura no soportado)"
                ac.add("plt_no_reconocido", clave, nodo=ruta, ejemplo=f"{tvg.name}: {cid}")
