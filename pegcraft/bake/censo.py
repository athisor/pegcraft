"""censo.py <xstage> <fotograma> [regex]: para cada READ, la cadena de entrada 0 hasta la raiz; por cada deformador
(OffsetModule/CurveModule) el valor en el fotograma contra el de reposo. Escribe censo.json. Solo lectura.
Como modulo: censo(xstage, fotograma, regex) -> {ruta_read: [eslabones del mas cercano al mas lejano]}."""
import sys, re, json, os
import xml.etree.ElementTree as ET
sys.dont_write_bytecode = True

# PEGCRAFT_SWITCH: que TransformationSwitch siguen el puerto elegido por el dibujo expuesto en su columna (Harmony elige la entrada N cuya lista
# `transformationN val="a;b;"` contiene ese dibujo; la entrada 0 = sin deformar). "0"/"" = siempre puerto 0 (comportamiento anterior),
# "cuello" = solo los switches dentro de un grupo Deformation-*Cuello, "todos" = todos, otro valor = regex sobre la ruta del switch.
SWITCH_DEF = "todos"   # 12-11-2026 noche: con deformadores.grupos (composicion padre/hijo) el banco sube en varios planos (PLANO +0,08, PLANO +0,06, PLANO +0,04, PLANO +0,08..0,13), ninguno baja


def _modo_switch():
    v = os.environ.get("PEGCRAFT_SWITCH", SWITCH_DEF).strip()
    if v in ("", "0", "no", "off"):
        return None
    if v == "cuello":
        return re.compile(r"/Deformation-[^/]*Cuello[^/]*/[^/]*$", re.I)
    if v == "todos":
        return re.compile(".")
    return re.compile(v, re.I)


def _exposicion(texto, col, f):
    """dibujo expuesto (str) de la columna `col` en el fotograma f, o None."""
    m = re.search(r'<column type="0" name="%s"[^>]*>(.*?)</column>' % re.escape(col), texto, re.S)
    if not m:
        return None
    for s in re.finditer(r'<elementSeq exposures="([^"]*)" val="([^"]*)"', m.group(1)):
        for r in s.group(1).split(","):
            a, _, b = r.partition("-")
            if int(a) <= f <= int(b or a):
                return s.group(2)
    return None


def censo(xs, f, patron="."):
    from . import apilado  # deja lector_xstage importable
    from lector_xstage.core.scene_graph import SceneGraph
    from lector_xstage.propuesta_layout import evaluar as E, cadena as C, caja as J
    rx = re.compile(patron, re.I)
    g = SceneGraph.from_xstage(str(xs))
    doc = E.abrir(E.xstage_de(str(xs)))
    sw = _modo_switch()
    _txt = []

    def puerto_switch(nodo):
        """entrada del TransformationSwitch que Harmony usa en el fotograma f (0 si ninguna lista contiene el dibujo expuesto)."""
        if not _txt:
            _txt.append(open(E.xstage_de(str(xs)), encoding="utf-8", errors="replace").read())
        a = doc.nodes[C.ruta_nodo(nodo)].element.find("attrs")
        dib = _exposicion(_txt[0], a.find("drawing/element").get("col"), f)
        n = int(a.find("transformationnames/size").get("val"))
        for k in range(1, n + 1):
            v = a.find("transformationnames/transformation%d" % k).get("val", "")
            if dib is not None and dib in [x for x in v.split(";") if x]:
                return k
        return 0

    def num(a, r):
        e = a.find(r)
        if e is None:
            return None
        x, _ = J._num(doc, e, f)
        if x is None:
            try:
                x = float(e.get("val"))
            except Exception:
                x = None
        return x

    def deformador(ruta):
        a = doc.nodes[C.ruta_nodo(ruta)].element.find("attrs")
        t = g.nodes[ruta].type
        d = {"ruta": ruta, "tipo": t}
        if t == "OffsetModule":
            pares = [("offset/x", "restingoffset/x"), ("offset/y", "restingoffset/y"), ("orientation", "restingorientation")]
        elif t == "CurveModule":
            pares = [("offset/x", "restingoffset/x"), ("offset/y", "restingoffset/y"), ("length0", "restlength0"),
                     ("orientation0", "restingorientation0"), ("length1", "restlength1"), ("orientation1", "restingorientation1")]
        else:
            d["attrs"] = re.sub(r"\s+", " ", ET.tostring(a, encoding="unicode"))[:600] if a is not None else None
            if t in ("DeformationCompositeModule", "KinematicOutputModule"):   # para los avisos de «no modelado» (deformadores.avisos_no_modelados)
                d["vals"] = {c.tag: c.get("val") for c in (a if a is not None else []) if c.get("val") is not None}
                d["fuera_de_defecto"] = sorted(c.tag for c in (a if a is not None else []) if c.get("val") is not None and c.get("defaultValue") is not None and c.get("val") != c.get("defaultValue"))
                d["puertos_usados"] = sorted(pt for pt in g.inputs(ruta) if g.input_cables(ruta, pt))
            return d
        d["act"] = {p[0]: num(a, p[0]) for p in pares}
        d["rep"] = {p[0]: num(a, p[1]) for p in pares}
        d["delta"] = max(abs((d["act"][k] or 0) - (d["rep"][k] or 0)) for k in d["act"])
        for k in ("localreferential", "influencetype", "transversalradius", "closepath"):
            e = a.find(k)
            if e is not None:
                d[k] = e.get("val")
        return d

    out = {}
    for ruta, n in g.nodes.items():
        if n.type != "READ" or not rx.search(ruta):
            continue
        cad, nodo, vistos, puerto, cin = [], ruta, set(), 0, False
        while nodo and nodo not in vistos:
            vistos.add(nodo)
            ins = [s for s, _ in g.input_cables(nodo, puerto)] if puerto in g.inputs(nodo) else []
            nodo = ins[0] if ins else None
            puerto = 0
            if nodo:
                t = g.nodes[nodo].type
                cad.append(deformador(nodo) if t != "PEG" else {"ruta": nodo, "tipo": "PEG"})
                if t == "KinematicOutputModule":
                    cin = True   # lo que cuelga aguas arriba de un KinematicOutput se aplica como transformacion rigida de la punta
                elif cin and t in ("OffsetModule", "CurveModule"):
                    cad[-1]["cinematico"] = True
                if sw is not None and t == "TransformationSwitch" and sw.search(nodo):
                    puerto = puerto_switch(nodo)
        out[ruta] = cad
    return out


def main(xs, f, patron=".", salida=None):
    """Imprime los READ con deformadores activos; con `salida` escribe el censo JSON."""
    out = censo(xs, f, patron)
    if salida:
        json.dump(out, open(salida, "w"), indent=1)
    for r, cad in out.items():
        ds = [c for c in cad if c["tipo"] in ("OffsetModule", "CurveModule")]
        if ds:
            print(r.split("/")[-1], "| n_def", len(ds), "| max_delta", round(max(c["delta"] for c in ds), 5),
                  "| activos:", [c["ruta"].split("/")[-1] for c in ds if c["delta"] > 1e-6])
