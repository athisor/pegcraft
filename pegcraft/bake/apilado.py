"""Orden de apilado de los READ de una escena Harmony en un fotograma (T7 de (doc interna omitida).

Reglas ( §2-§6):
- El recorrido parte del composite que alimenta al WRITE/DISPLAY (o Top/Composite) y va AGUAS ARRIBA,
  puerto por puerto en orden creciente (0 = atras), expandiendo cada composite anidado en su lugar
  (profundidad primero). Los grupos se cruzan por Multi-Port (SceneGraph.input_cables).
- Manda el numero de puerto, no el orden del archivo; un hueco de puertos no cambia nada.
- Con Z distinta gana la Z (Z de la cadena de escena_evaluar = Z acumulada); con Z igual manda el puerto.
  Se implementa como orden estable por (z, indice del recorrido).
- DeformationCompositeModule no apila (compone cadenas de deformacion): se salta con aviso.
- CUTTER: puerto 0 = imagen (se apila en el lugar del cutter), puerto 1 = matte (NO se dibuja; queda como
  `recorte` de las piezas del puerto 0). El rasterizador aun no recorta: se avisa.
- READ que el evaluador expone pero el recorrido no alcanza: no llegan al render (se excluyen con aviso).

Uso CLI: python -I apilado.py <xstage> <fotograma> [--json salida.json]
API:     orden_apilado(escena, fotograma) -> dict(orden=[{id, z, recorrido, puertos, razon, ...}], excluidas, mattes, avisos)
"""
import sys, json, os, importlib.util
sys.dont_write_bytecode = True
# Fachada del lector de escenas (dependencia externa, ver LIMPIEZA_PENDIENTE.md): ruta de su api.py en PEGCRAFT_XSTAGE_API.
_API = os.environ.get("PEGCRAFT_XSTAGE_API", "")
if _API and os.path.isfile(_API):
    sys.path.insert(0, os.path.dirname(os.path.dirname(_API))); sys.path.insert(0, os.path.dirname(_API))
    _spec = importlib.util.spec_from_file_location("xapi", _API)
    X = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(X)
else:
    X = None   # sin el lector externo el horneado no funciona; las funciones puras de este modulo si se importan

EXCEPCIONES_Z = ("ANIMATIC", "TIMECODE", "FONDO_PEG")   # Z conocida (doc §6, criterio del estudio)


def norm(r):
    r = r.lstrip("/")
    return r if r.startswith("Top/") or r == "Top" else "Top/" + r


def _raiz(g, avisos):
    for p, n in g.nodes.items():
        if n.type in ("WRITE", "DISPLAY") and not n.disabled:
            s = g.resolve_source(p, 0)
            if s and g.nodes[s[0]].type == "COMPOSITE":
                return s[0]
    if "Top/Composite" in g.nodes:
        avisos.append("sin WRITE/DISPLAY con composite: se usa Top/Composite")
        return "Top/Composite"
    raise SystemExit("no se encontro el composite raiz")


def recorrer(g, raiz):
    """Hojas READ en orden de recorrido (atras -> adelante) con la ruta de puertos y el recorte."""
    hojas, mattes, avisos, vistos = [], [], [], set()

    def visitar(nodo, puertos, recorte, modo, prof):
        if prof > 200:
            avisos.append(f"recorrido demasiado profundo en {nodo}"); return
        n = g.nodes[nodo]
        t = n.type
        if t == "READ":
            if n.disabled:
                return
            if modo == "matte":
                mattes.append({"id": nodo, "puertos": list(puertos)}); return
            if nodo in vistos:
                avisos.append(f"READ alcanzado por dos caminos (se dibuja dos veces): {nodo}")
            vistos.add(nodo)
            hojas.append({"id": nodo, "puertos": list(puertos), "recorte": list(recorte)}); return
        if n.disabled and t == "COMPOSITE":
            avisos.append(f"composite apagado, se omite su contenido: {nodo}"); return
        if t == "DeformationCompositeModule":
            avisos.append(f"DeformationCompositeModule en el camino de imagen (no apila; se salta): {nodo}"); return
        if t == "PEG" or t.endswith("Module") or t in ("StaticConstraint",):
            return   # transformaciones y deformadores: no son imagen
        if t == "COMPOSITE":
            for p in g.composite_ports(nodo):
                for s, _sp in g.input_cables(nodo, p.port):
                    visitar(s, puertos + (p.port,), recorte, modo, prof + 1)
            return
        if t == "CUTTER" or "MATTE" in t.upper():
            antes = len(mattes)
            for s, _sp in g.input_cables(nodo, 1):
                visitar(s, puertos, (), "matte", prof + 1)
            inv = g.attr_val(nodo, "inverted")
            rec = recorte + ({"nodo": nodo, "tipo": t, "invertido": inv,
                              "mattes": [m["id"] for m in mattes[antes:]]},)
            for s, _sp in g.input_cables(nodo, 0):
                visitar(s, puertos, rec, modo, prof + 1)
            return
        # intermedios (LINE_ART, COLOR_ART, AutoPatchModule, OVERLAY...): la imagen sigue por sus entradas
        ins = sorted(g.inputs(nodo))
        if len(ins) > 1:
            avisos.append(f"{t} con {len(ins)} entradas tratadas como imagen en orden de puerto: {nodo}")
        for ip in ins:
            for s, _sp in g.input_cables(nodo, ip):
                visitar(s, puertos, recorte, modo, prof + 1)

    visitar(raiz, (), (), "imagen", 0)
    return hojas, mattes, avisos


def orden_apilado(escena, fotograma, evaluados=None):
    avisos = []
    xs, g = X._grafo(escena, avisos)
    raiz = _raiz(g, avisos)
    hojas, mattes, av = recorrer(g, raiz)
    avisos += av
    if evaluados is None:
        evaluados = X.escena_evaluar(str(xs), fotograma=fotograma, tipos=["READ"], solo_con_dibujo=True, max=2000)["nodos"]
    ev = {norm(n["ruta"]): n for n in evaluados}
    matte_ids = {m["id"] for m in mattes}
    filas = []
    for i, h in enumerate(hojas):
        e = ev.get(h["id"])
        if e is None or e["apagado"]:
            continue   # sin dibujo expuesto en este fotograma o apagado por un grupo
        filas.append({**h, "recorrido": i, "z": float(e["z"])})
    final = sorted(filas, key=lambda r: (r["z"], r["recorrido"]))
    pos = {r["id"]: k for k, r in enumerate(final)}
    # razon: inversiones contra el orden por puerto (pares donde la Z decide)
    for r in final:
        inv = [o["id"] for o in filas if (o["recorrido"] < r["recorrido"]) != (pos[o["id"]] < pos[r["id"]])]
        r["inversiones_z"] = len(inv)
        if not inv:
            r["razon"] = "puerto"
        else:
            r["razon"] = "z_acumulada"
            r["invierte_con"] = inv[:5]
            r["z_excepcion_conocida"] = any(k in r["id"].upper() for k in EXCEPCIONES_Z)
        if r["recorte"]:
            r.setdefault("avisos", []).append("tiene cutter/matte: el rasterizador aun no recorta")
    n_inv = sum(1 for r in final if r["razon"] != "puerto")
    if n_inv:
        avisos.append(f"{n_inv} piezas cambian de lugar por Z contra el orden de puertos (criterio del estudio: la Z es excepcion; revisar)")
    alcanzados = {h["id"] for h in hojas}
    excluidas = [{"id": k, "motivo": "matte de un cutter" if k in matte_ids else "no llega al composite raiz"}
                 for k, e in ev.items() if not e["apagado"] and k not in alcanzados]
    for k in excluidas:
        avisos.append(f"excluida ({k['motivo']}): {k['id']}")
    for k, r in enumerate(final):
        r["orden"] = k
    return {"escena": str(xs), "fotograma": fotograma, "raiz": raiz, "orden": final,
            "mattes": mattes, "excluidas": excluidas, "avisos": avisos}


# ---- Conectores (integrado de <datos de trabajo omitidos>, 11-11-2026; <datos de trabajo omitidos> §2-§6 y §12) ----
# - Cada hoja lleva `capas` (subconjunto de underlay/colour/line/overlay): LINE_ART, COLOR_ART, OVERLAY, UNDERLAY y LAYER_SELECTOR filtran.
# - VISIBILITY con softrender=false corta el camino (solo se ve en OpenGL, no en el render).
# - AutoPatchModule NO es un deformador (termina en "Module"): como matte entrega el arte de color de su READ.
# - CUTTER: el matte (puerto 1) se guarda con detalle [{id, capas}]; sin cable en el puerto 1 o apagado = pasa la imagen.
# - z_modo: "global" o "bitmap" (un composite no passthrough es un bloque; sin medir).
# Banderas de experimento (dict `exp`): sin_selector, sin_capas, sin_visibility, sin_autopatch, sin_cutter, apagar=[nodos].
TODAS = ("underlay", "colour", "line", "overlay")
FILTRO = {"LINE_ART": {"line"}, "COLOR_ART": {"colour"}, "OVERLAY": {"overlay"}, "UNDERLAY": {"underlay"}}
SI = lambda v: str(v).lower() in ("true", "y", "1")


def recorrer_conectores(g, raiz, exp=None, efectos=None):
    """`efectos` (dict opcional, se llena): BLEND_MODE_MODULE y GLOW activos y ALCANZADOS desde la raiz, para avisar (no cambia el recorrido ni el render)."""
    exp = exp or {}
    hojas, avisos, cortados = [], [], []
    blur_pila = []   # GAUSSIANBLUR sobre un matte (cutter puerto 1): su desenfoque (blurriness) se acumula en la hoja
    apagar = {"Top/Personaje/" + a if "/" not in a else a for a in exp.get("apagar", [])}

    def capas_sel(nodo):
        m = {"underlay": "readUnderlay", "colour": "readColourart", "line": "readLineart", "overlay": "readOverlay"}
        return {c for c, a in m.items() if SI(g.attr_val(nodo, a))}

    def visitar(nodo, puertos, recorte, capas, modo, dest, prof, bloque, glow=False):
        n = g.nodes[nodo]; t = n.type
        des = n.disabled or nodo in apagar or (t == "CUTTER" and exp.get("sin_cutter"))   # apagado = deja pasar su entrada 0
        if t == "READ":
            if des or not capas:
                return
            h = {"id": nodo, "puertos": list(puertos), "recorte": list(recorte), "capas": [c for c in TODAS if c in capas], "bloque": bloque}
            if blur_pila:
                h["blur"] = sum(blur_pila)
            if glow:
                h["glow"] = True; h["glow_gain"] = float(glow)   # rama READ -> ... -> GLOW (aditivo): hornear la marca como mezcla "suma" con glow_suma
            dest.append(h)
            return
        if t == "COMPOSITE":
            if des:
                avisos.append(f"composite apagado: {nodo}"); return
            b = bloque
            if b is None and g.attr_val(nodo, "compositeMode") != "compositePassthrough":
                b = nodo   # bloque = el composite no passthrough mas externo
            for p in g.composite_ports(nodo):
                for s, _ in g.input_cables(nodo, p.port):
                    visitar(s, puertos + (p.port,), recorte, capas, modo, dest, prof + 1, b, glow)
            return
        if t == "AutoPatchModule" and not exp.get("sin_autopatch"):
            # SUPUESTO (coherente con el experimento E3): el matte de un Auto-Patch es el arte de COLOR del dibujo
            for s, _ in g.input_cables(nodo, 0):
                visitar(s, puertos, recorte, set(capas) & {"colour"} if not des else capas, modo, dest, prof + 1, bloque, glow)
            return
        if t == "DeformationCompositeModule" or t == "PEG" or t.endswith("Module") and t != "BLEND_MODE_MODULE" or t in ("StaticConstraint", "MasterController"):
            return
        if t == "GAUSSIANBLUR-PLUGIN" and modo == "matte" and not des:
            try:
                b = float(g.attr_val(nodo, "blurriness"))
            except (TypeError, ValueError):
                b = 0.0
            blur_pila.append(b)
            try:
                for ip in sorted(g.inputs(nodo)):
                    for s, _ in g.input_cables(nodo, ip):
                        visitar(s, puertos, recorte, capas, modo, dest, prof + 1, bloque, glow)
            finally:
                blur_pila.pop()
            return
        if t == "VISIBILITY":
            if not SI(g.attr_val(nodo, "softrender")) and not des and not exp.get("sin_visibility"):
                cortados.append(nodo); return
        if t == "CUTTER":
            ms = []
            if not des and not exp.get("sin_cutter"):
                for s, _ in g.input_cables(nodo, 1):
                    visitar(s, (), (), set(TODAS), "matte", ms, prof + 1, None)
            rec = recorte
            if ms:
                rec = recorte + ({"nodo": nodo, "invertido": SI(g.attr_val(nodo, "inverted")),
                                  "mattes": [{"id": m["id"], "capas": m["capas"], **({"blur": m["blur"]} if m.get("blur") else {})} for m in ms]},)
            elif not des:
                avisos.append(f"cutter sin matte (pasa la imagen): {nodo}")
            for s, _ in g.input_cables(nodo, 0):
                visitar(s, puertos, rec, capas, modo, dest, prof + 1, bloque, glow)
            return
        if efectos is not None and not des and t in ("BLEND_MODE_MODULE", "GLOW"):
            efectos.setdefault(nodo, {"tipo": t, "modo": g.attr_val(nodo, "blendMode"), "radio": g.attr_val(nodo, "radius"),
                                      "multiplicativo": SI(g.attr_val(nodo, "multiplicative"))})
        c2 = capas
        if not des and not exp.get("sin_capas"):
            if t in FILTRO:
                c2 = set(capas) & FILTRO[t]
            elif t == "LAYER_SELECTOR" and not exp.get("sin_selector"):
                c2 = set(capas) & capas_sel(nodo)
        if t not in FILTRO and t not in ("LAYER_SELECTOR", "VISIBILITY"):
            avisos.append(f"{t} tratado como transparente (efecto no aplicado): {nodo}")
        # GLOW con multiplicative=false y no apagado: lo que le llega por arriba se SUMA (Harmony). Con multiplicative=true no se marca.
        g2 = glow
        if t == "GLOW" and not des and not SI(g.attr_val(nodo, "multiplicative")):
            try:
                g2 = float(g.attr_val(nodo, "colourGain"))
            except (TypeError, ValueError):
                g2 = 1.0
            g2 = min(g2, 1.0)   # MEDIDO PLANO: con colourGain 2 el ajuste empeora (0,899 con 1 -> 0,82 con 2); queda abierto por que
            _mp = dict(kv.split(":") for kv in os.environ.get("PEGCRAFT_GLOW_MAP", "").split(",") if ":" in kv)
            if nodo.split("/")[-1] in _mp:
                g2 = float(_mp[nodo.split("/")[-1]])
            elif os.environ.get("PEGCRAFT_GLOW_GAIN"):   # experimento: fuerza la ganancia
                g2 = float(os.environ["PEGCRAFT_GLOW_GAIN"])
        for ip in sorted(g.inputs(nodo)):
            for s, _ in g.input_cables(nodo, ip):
                visitar(s, puertos, recorte, c2, modo, dest, prof + 1, bloque, g2)

    visitar(raiz, (), (), set(TODAS), "imagen", hojas, 0, None)
    return hojas, avisos, cortados


BLEND_NORMAL = "eNORMAL_BLEND"


def avisos_efectos(efectos):
    """Avisos (texto + codigo en compilar/avisos.py) de efectos activos que el horneado NO modela; no cambian el render.
    BLEND_MODE_MODULE con modo != eNORMAL_BLEND -> BLEND_MODE_NO_MODELADO (el modulo se trata como transparente).
    GLOW con radio > 0 (o no legible) -> GLOW_NO_MODELADO (el desenfoque del glow no existe; solo se modela la suma con radio 0);
    mas de un GLOW alcanzado -> GLOW_MULTIPLE (revisar orden y suma)."""
    out, glows = [], []
    for ruta, e in sorted(efectos.items()):
        if e["tipo"] == "BLEND_MODE_MODULE":
            if (e["modo"] or "?") != BLEND_NORMAL:
                out.append(f"BLEND_MODE_MODULE activo ({e['modo']}) en {ruta}: no modelado (se compone como normal); revisar")
        else:
            glows.append(ruta)
            try:
                r = float(e["radio"])
            except (TypeError, ValueError):
                out.append(f"GLOW activo con radio no legible ({e['radio']}) en {ruta}: no modelado; revisar"); continue
            if r > 0:
                out.append(f"GLOW activo con radio={r:g} en {ruta}: el desenfoque del glow no esta modelado; revisar")
    if len(glows) > 1:
        out.append(f"GLOW multiples: {len(glows)} activos ({', '.join(glows[:4])}{', ...' if len(glows) > 4 else ''}): revisar orden y suma")
    return out


def orden_apilado_conectores(escena, fotograma, evaluados=None, exp=None, z_modo="global"):
    avisos = []
    xs, g = X._grafo(escena, avisos)
    raiz = _raiz(g, avisos)
    efectos = {}
    hojas, av, cortados = recorrer_conectores(g, raiz, exp, efectos)
    avisos += av
    if evaluados is None:
        evaluados = X.escena_evaluar(str(xs), fotograma=fotograma, tipos=["READ"], solo_con_dibujo=True, max=2000)["nodos"]
    ev = {norm(n["ruta"]): n for n in evaluados}
    filas = []
    for i, h in enumerate(hojas):
        e = ev.get(h["id"])
        if e is None or e["apagado"]:
            continue
        filas.append({**h, "recorrido": i, "z": float(e["z"])})
    if z_modo == "bitmap":
        zb = {}
        for r in filas:
            if r["bloque"]:
                zb[r["bloque"]] = r["z"]   # la ultima hoja del bloque = puerto mas alto (LEFTMOST, SUPUESTO)
        prim = {}
        for r in filas:
            if r["bloque"]:
                prim.setdefault(r["bloque"], r["recorrido"])
        clave = lambda r: (zb[r["bloque"]], prim[r["bloque"]], r["z"], r["recorrido"]) if r["bloque"] else (r["z"], r["recorrido"], 0, 0)
    else:
        clave = lambda r: (r["z"], r["recorrido"])
    final = sorted(filas, key=clave)
    for k, r in enumerate(final):
        r["orden"] = k; r["razon"] = "puerto+z"
    return {"escena": str(xs), "fotograma": fotograma, "raiz": raiz, "orden": final, "cortados_visibility": cortados,
            "avisos": sorted(set(avisos)), "mattes": [], "excluidas": [], "efectos_avisos": avisos_efectos(efectos)}


if __name__ == "__main__":
    a = sys.argv
    r = orden_apilado(a[1], int(a[2]))
    if "--json" in a:
        json.dump(r, open(a[a.index("--json") + 1], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps({"raiz": r["raiz"], "n": len(r["orden"]), "excluidas": len(r["excluidas"]), "mattes": len(r["mattes"]),
                      "por_z": sum(1 for o in r["orden"] if o["razon"] != "puerto"), "avisos": r["avisos"][:12]}, ensure_ascii=False))
