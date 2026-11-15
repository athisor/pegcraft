"""generador: escribe un .xstage SINTETICO y determinista desde una especificacion JSON.

Uso:
  python sintetico/generador.py ESPEC.json [-o SALIDA.xstage]       genera (por omision junto a la especificacion)
  python sintetico/generador.py ESPEC.json --verificar              regenera y compara byte a byte con el .xstage existente
  python sintetico/generador.py --dir CARPETA [--verificar]         todas las especificaciones de la carpeta (*.json salvo *.esperado.json)

La estructura imita la observada en escenas propias (P01-P06, P09, P17-P22; tabla en docs/PROCEDENCIA.md): indentacion de 1 espacio, LF,
comillas dobles, grupo sin atributo `type`, enlaces `link in/out [inport] [outport]`, columnas tipo 0/2/3.
Se omite a proposito todo `metas` (incluida `checksumValidation`): no hace falta para leer. Sin rutas absolutas;
los nombres los inventa la especificacion (`Pieza_A`, `Grupo_1`).

Especificacion (todo opcional salvo `nombre` y `nodos`):
  nombre, fotogramas (def. 24), fps (def. 24)
  codificacion: {"bom": false, "entidades_numericas": false}   BOM al inicio; caracteres no ASCII como &#NNN;
  elementos: [{"id": 2, "nombre": "Dibujo_A", "carpeta": "Dibujo_A", "dibujos": ["1", "2"]}]
  columnas:
    {"nombre", "tipo": 0, "elemento": 2, "secuencias": [{"cuadros": "1-4,7", "dibujo": "1"}]}
    {"nombre", "tipo": 3, "puntos": [{"x": "1-5", "y": 0.0, "yLocal": 0.0, "constSeg": false, "extra": {"rx": 1}}],
     "sin_yLocal": false, "sin_cuadros": false}
    {"nombre", "tipo": 2, "puntos": [{"v": [0, 0, 0], "t": 1}], "velocidad": <columna tipo 3 sin nombre>, "constanteZ": false}
  nodos: lista (raiz = grupo Top). Cada nodo:
    {"tipo": "PEG|READ|COMPOSITE|WRITE|DISPLAY|MULTIPORT_IN|MULTIPORT_OUT|<otro>", "nombre", "pos": "x,y,n", "apagado": false,
     "attrs": {"scale/x": 2, "rotation/anglez": {"val": 0, "col": "Col_A"}, "position/attr3dpath": {"col": "Col_T"}},
     "puertos": [{"tipo": "PEG", "idx": 0}]}                       (MULTIPORT_*)
    {"tipo": "GROUP", "nombre", "apagado", "nodos": [...], "enlaces": [...], "backdrops": [{"titulo", "rect": [x0,y0,x1,y1]}]}
  enlaces: [{"origen": "A", "destino": "B", "puerto_origen": 0, "puerto_destino": 0, "explicito": false}]
    (`origen` envia a `destino`; en el archivo: link out=origen in=destino; los puertos 0 se omiten salvo `explicito`)
  Un valor de atributo que sea texto con saltos de linea se escribe con el salto crudo; con {"val": ..., "salto": "entidad"}, como &#10;.
"""
import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CABECERA_SOURCE = "Generador sintetico (tools/sintetico) version 2402 build 23443"


class Crudo(str):
    """Texto cuyos saltos de linea se escriben tal cual (como hace Harmony en scriptEditor)."""


# ---------------------------------------------------------------- plantillas de atributos
# Estructura observada en archivos propios (P20, P21, P22, P24; `scale/inFields` siempre false: P24) y valores por omision del XML. Sin `metas` (P26).
_PEG = """<attrs>
<enable3d val="false"/><faceCamera val="false"/><cameraAlignment val="NO_CAMERA_ALIGNMENT"/>
<position><separate val="false"/><x val="0" defaultValue="0"/><y val="0" defaultValue="0"/><z val="0" defaultValue="0"/></position>
<scale><separate val="true"/><inFields val="false"/><xy val="1" defaultValue="1"/><x val="1" defaultValue="1"/><y val="1" defaultValue="1"/><z val="1" defaultValue="1"/></scale>
<rotation><separate val="false"/><anglex val="0" defaultValue="0"/><angley val="0" defaultValue="0"/><anglez val="0" defaultValue="0"/></rotation>
<angle val="0" defaultValue="0"/><skew val="0" defaultValue="0"/>
<pivot><x val="0" defaultValue="0"/><y val="0" defaultValue="0"/><z val="0" defaultValue="0"/></pivot>
<splineOffset><x val="0" defaultValue="0"/><y val="0" defaultValue="0"/><z val="0" defaultValue="0"/></splineOffset>
<ignoreParentPegScaling val="false"/><disableFieldRendering val="false"/><depth val="0"/>
<enableMinMaxAngle val="false"/><minAngle val="-360" defaultValue="-360"/><maxAngle val="360" defaultValue="360"/>
<nailForChildren val="false"/><ikHoldOrientation val="false"/><ikHoldX val="false"/><ikHoldY val="false"/><ikExcluded val="false"/>
<ikCanRotate val="true"/><ikCanTranslateX val="false"/><ikCanTranslateY val="false"/>
<ikBoneX val="0.20000000000000001" defaultValue="0.20000000000000001"/><ikBoneY val="0" defaultValue="0"/><ikStiffness val="1" defaultValue="1"/>
<groupAtNetworkBuilding val="false"/><addCompositeToGroup val="true"/>
</attrs>"""

_READ = """<attrs>
<enable3d val="false"/><faceCamera val="false"/><cameraAlignment val="NO_CAMERA_ALIGNMENT"/>
<offset><separate val="true"/><x val="0" defaultValue="0"/><y val="0" defaultValue="0"/><z val="0" defaultValue="0"/></offset>
<scale><separate val="true"/><inFields val="false"/><xy val="1" defaultValue="1"/><x val="1" defaultValue="1"/><y val="1" defaultValue="1"/><z val="1" defaultValue="1"/></scale>
<rotation><separate val="false"/><anglex val="0" defaultValue="0"/><angley val="0" defaultValue="0"/><anglez val="0" defaultValue="0"/></rotation>
<angle val="0" defaultValue="0"/><skew val="0" defaultValue="0"/>
<pivot><x val="0" defaultValue="0"/><y val="0" defaultValue="0"/><z val="0" defaultValue="0"/></pivot>
<splineOffset><x val="0" defaultValue="0"/><y val="0" defaultValue="0"/><z val="0" defaultValue="0"/></splineOffset>
<ignoreParentPegScaling val="false"/><disableFieldRendering val="false"/><depth val="0"/>
<enableMinMaxAngle val="false"/><minAngle val="-360" defaultValue="-360"/><maxAngle val="360" defaultValue="360"/>
<nailForChildren val="false"/><ikHoldOrientation val="false"/><ikHoldX val="false"/><ikHoldY val="false"/><ikExcluded val="false"/>
<ikCanRotate val="true"/><ikCanTranslateX val="false"/><ikCanTranslateY val="false"/>
<ikBoneX val="0.20000000000000001" defaultValue="0.20000000000000001"/><ikBoneY val="0" defaultValue="0"/><ikStiffness val="1" defaultValue="1"/>
<drawing><elementMode val="true"/><element col=""><layer val=""/></element>
<customName><name val=""/><extension val="tga"/><fieldChart val="12" defaultValue="12"/></customName></drawing>
<readOverlay val="true"/><readLineArt val="true"/><readColorArt val="true"/><readUnderlay val="true"/>
<overlayArtDrawingMode val="VectorDrawingMode"/><lineArtDrawingMode val="VectorDrawingMode"/>
<colorArtDrawingMode val="VectorDrawingMode"/><underlayArtDrawingMode val="VectorDrawingMode"/>
<readColor val="true"/><readTransparency val="true"/><colorTransformation val="Linear"/><colorSpace val="sRGB"/>
<opacity val="100" defaultValue="100"/><textureFilter val="NEAREST_FILTERED"/>
<useDrawingPivot val="APPLY_ON_READ_TRANSFORM"/><flipHor val="false"/><flipVert val="false"/>
<canAnimate val="true"/><tileHorizontal val="false"/><tileVertical val="false"/>
</attrs>"""

_COMPOSITE = """<attrs>
<compositeMode val="compositeBitmap"/><flattenOutput val="true"/><flattenVector val="false"/>
<composite2d val="false"/><composite3d val="false"/><outputZ val="LEFTMOST"/><outputZInputPort val="1"/>
<applyFocus val="true"/><multiplier val="1" defaultValue="1"/><tvgPalette val="compositedPalette"/><mergeVector val="false"/>
</attrs>"""

_WRITE = """<attrs>
<exportToMovie val="false"/><drawingName val="frames/final-"/><moviePath val="frames/output"/>
<movieFormat val="com.toonboom.quicktime.legacy"/><movieAudio val=""/><movieVideo val=""/><movieVideoaudio val=""/>
<leadingZeros val="3"/><start val="1"/><drawingType val="TGA"/>
<enabling><filter val="ALWAYS"/><filterName val=""/><filterResX val="720"/><filterResY val="540"/></enabling>
<scriptMovie val="false"/><scriptEditor val="// Codigo de ejemplo sintetico&#10;// segunda linea"/>
<colorSpace val=""/><compositePartitioning val="NoCompositePartitioning"/>
<zPartitionRange val="1" defaultValue="1"/><cleanUpPartitionFolders val="true"/>
</attrs>"""

PLANTILLAS = {"PEG": _PEG, "READ": _READ, "COMPOSITE": _COMPOSITE, "WRITE": _WRITE}
SIN_TAB = {"MULTIPORT_IN", "MULTIPORT_OUT"}


# ---------------------------------------------------------------- utilidades
def fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    return v


def _x(v):
    """Campo x de un punto: texto/rangos o lista de enteros."""
    if isinstance(v, (list, tuple)):
        return ",".join(str(i) for i in v)
    return str(v)


def _el(tag, attrs=None, hijos=()):
    e = ET.Element(tag)
    for k, v in (attrs or {}).items():
        e.set(k, fmt(v))
    for h in hijos:
        e.append(h)
    return e


def _opciones(apagado=False, extra=()):
    o = ET.Element("options")
    if apagado:                                      # P14, A2-06: options/disabled@val="true" (módulo y grupo)
        o.append(_el("disabled", {"val": True}))
    o.append(_el("collapsed", {"val": False}))
    for k, v in extra:
        o.append(_el(k, {"val": v}))
    return o


def _asignar(attrs, ruta, valor, nodo):
    """Pone `valor` en attrs/<ruta>. Escalar -> val; dict -> atributos del elemento."""
    partes = ruta.split("/")
    cur = attrs
    for i, p in enumerate(partes):
        sig = cur.find(p)
        if sig is None:
            sig = ET.Element(p)
            if p == "attr3dpath":                       # va despues de `separate`, antes de x
                sep = cur.find("separate")
                cur.insert(1 if sep is not None else 0, sig)
            else:
                cur.append(sig)
        cur = sig
    if isinstance(valor, dict):
        d = dict(valor)
        salto = d.pop("salto", None)
        for k, v in d.items():
            v = fmt(v)
            if isinstance(v, str) and ("\n" in v or "\r" in v) and salto != "entidad":
                v = Crudo(v)
            cur.set(k, v)
    else:
        v = fmt(valor)
        if isinstance(v, str) and ("\n" in v or "\r" in v):
            v = Crudo(v)
        cur.set("val", v)


def _modulo(n, indice):
    tipo = n["tipo"]
    pos = n.get("pos", f"0,{-100 * indice},{indice}")
    a = {"type": tipo, "name": n["nombre"], "pos": pos}                # P07: module@{type,name,pos,publishUnderTab}
    if tipo not in SIN_TAB:
        a["publishUnderTab"] = n["nombre"]
    m = _el("module", a)
    m.append(_opciones(n.get("apagado", False), [("version", n.get("version", 1))]))
    attrs = n.get("attrs", {})
    if tipo in PLANTILLAS:
        base = ET.fromstring(PLANTILLAS[tipo])
    elif attrs:
        base = ET.Element("attrs")
    else:
        base = None
    if base is not None:
        attrs = dict(attrs)
        if tipo in ("PEG", "READ") and "rotation/anglez" in attrs and "angle" not in attrs:
            attrs["angle"] = attrs["rotation/anglez"]         # P23: angle y anglez comparten columna
        for ruta, v in attrs.items():
            _asignar(base, ruta, v, n)
        m.append(base)
    if tipo in SIN_TAB:
        ps = ET.Element("ports")
        for p in n.get("puertos", [{"tipo": "PEG", "idx": 0}]):
            ps.append(_el("port", {"type": p["tipo"], "idx": p["idx"]}))
        m.append(ps)
    return m


def _enlaces(lista, nombres, donde):
    ll = ET.Element("linkedlist")
    for e in lista:
        for k in ("origen", "destino"):
            if e[k] not in nombres:
                raise ValueError(f"enlace con nodo inexistente '{e[k]}' en {donde}")
        po, pd = e.get("puerto_origen", 0), e.get("puerto_destino", 0)
        ex = bool(e.get("explicito"))
        # P09, P10, A7-01: orden observado de los atributos: in, inport, out, outport; los puertos 0 se omiten
        l = ET.Element("link")
        l.set("in", e["destino"])
        if pd or ex:
            l.set("inport", str(pd))
        l.set("out", e["origen"])
        if po or ex:
            l.set("outport", str(po))
        ll.append(l)
    return ll


def _grupo_contenido(nodos, enlaces, donde, contador):
    nl = ET.Element("nodeslist")
    nombres = set()
    for n in nodos:
        if n["nombre"] in nombres:
            raise ValueError(f"nombre repetido '{n['nombre']}' en {donde}")
        nombres.add(n["nombre"])
        i = contador[0]
        contador[0] += 1
        if n["tipo"] == "GROUP":
            g = _el("group", {"name": n["nombre"], "pos": n.get("pos", f"0,{-100 * i},{i}")})   # P06, P08: grupo sin atributo type
            g.append(_opciones(n.get("apagado", False), [("subnodeCollapsed", True), ("showsPublished", True)]))
            g.append(ET.Element("attrs"))
            sub, ll = _grupo_contenido(n.get("nodos", []), n.get("enlaces", []), donde + "/" + n["nombre"], contador)
            g.append(sub)
            g.append(ll)
            if n.get("backdrops"):                       # A2-01: topLeft/bottomRight "x,y"

                bs = ET.Element("backdrops")
                for b in n["backdrops"]:
                    x0, y0, x1, y1 = b["rect"]
                    bd = _el("backdrop", {"topLeft": f"{x0},{y0}", "bottomRight": f"{x1},{y1}"})
                    bd.append(_el("background", {"color": b.get("color", "#D9E8FFFF")}))
                    bd.append(_el("title", {"color": "#000000FF", "font": "Arial", "size": 14, "text": b["titulo"]}))
                    bs.append(bd)
                g.append(bs)
            nl.append(g)
        else:
            nl.append(_modulo(n, i))
    return nl, _enlaces(enlaces, nombres, donde)


def _puntos_tipo3(puntos, sin_yLocal=False):
    """<points version="2"> con <pt constSeg x yLocal y ...> (P17, P33: yLocal y y)."""
    ps = ET.Element("points")
    ps.set("version", "2")
    for p in puntos:
        a = {"constSeg": bool(p.get("constSeg", False)), "x": _x(p["x"])}
        y = p["y"] if "y" in p else p["yLocal"]
        if not sin_yLocal:
            a["yLocal"] = p.get("yLocal", y)
        a["y"] = y
        for k, v in p.get("extra", {}).items():
            a[k] = v
        ps.append(_el("pt", a))
    return ps


def _columna(c, elementos_ids):
    """Columna tipo 0 (P18), 3 (P17) o 2 (P19, P22)."""
    t = c["tipo"]
    if t == 0:
        if c["elemento"] not in elementos_ids:
            raise ValueError(f"columna '{c['nombre']}': elemento {c['elemento']} inexistente")
        e = _el("column", {"type": 0, "name": c["nombre"], "color": "#FFFFFFFF", "displayOrder": 0, "width": 100,
                           "anonymous": True, "id": c["elemento"]})
        for s in c.get("secuencias", []):
            e.append(_el("elementSeq", {"exposures": s["cuadros"], "val": s["dibujo"], "id": c["elemento"]}))
        return e
    if t == 3:
        e = _el("column", {"type": 3, "name": c["nombre"], "displayOrder": 0, "width": 100, "anonymous": True})
        e.append(_el("step", {"val": 1, "start": 1, "stop": 1}))
        if c.get("sin_cuadros"):
            e.append(ET.Element("noFrames"))
        e.append(_puntos_tipo3(c["puntos"], c.get("sin_yLocal", False)))
        return e
    if t == 2:
        e = _el("column", {"type": 2, "name": c["nombre"], "anonymous": True, "displayOrder": 0})
        for k in ("infoX", "infoY", "infoZ", "infoVelocity"):
            e.append(_el(k, {"width": 100}))
        p3 = _el("path3D", {"useVeloX": True, "useVeloY": True, "useVeloZ": True, "constantZ": bool(c.get("constanteZ", False))})
        pts = ET.Element("points")
        for p in c["puntos"]:
            pts.append(_el("pt", {"val": ",".join(fmt(float(v)) if not isinstance(v, str) else v for v in p["v"]),
                                  "lockedInTime": p["t"]}))
        p3.append(pts)
        e.append(p3)
        vel = c.get("velocidad")
        if vel is None:
            t0, t1 = c["puntos"][0]["t"], c["puntos"][-1]["t"]
            vel = {"puntos": [{"x": t0, "y": 0.0}, {"x": t1, "y": 1.0}]}
        v = _el("velocity", {"type": 3, "name": c["nombre"] + "-V", "displayOrder": 0, "width": 100, "anonymous": True})
        v.append(_el("step", {"val": 1, "start": 1, "stop": 1}))
        v.append(_puntos_tipo3(vel["puntos"], vel.get("sin_yLocal", False)))
        e.append(v)
        return e
    raise ValueError(f"tipo de columna {t} no soportado por el generador")


def _completar(spec):
    """Devuelve una copia con elementos y columnas por omision para cada READ sin columna."""
    spec = json.loads(json.dumps(spec))
    if not spec.get("elementos"):
        spec["elementos"] = [{"id": 2, "nombre": "Dibujo_A", "carpeta": "Dibujo_A", "dibujos": []}]
    cols = spec.setdefault("columnas", [])
    nombres = {c["nombre"] for c in cols}
    primero = spec["elementos"][0]["id"]

    def recorrer(ns):
        for n in ns:
            if n["tipo"] == "READ":
                a = n.setdefault("attrs", {})
                d = a.get("drawing/element")
                col = d.get("col") if isinstance(d, dict) else d
                if not col:
                    col = "Col_" + n["nombre"]
                    a["drawing/element"] = {"col": col}
                if col not in nombres:
                    cols.append({"nombre": col, "tipo": 0, "elemento": primero, "secuencias": []})
                    nombres.add(col)
            if n["tipo"] == "GROUP":
                recorrer(n.get("nodos", []))
    recorrer(spec["nodos"])
    return spec


def construir(spec):
    """Especificacion (dict) -> ET.Element raiz. Estructura: P01 (raiz), P02-P03 (options), P04-P06 (scene), P20 (elements); sin metas (P26)."""
    spec = _completar(spec)
    nombre = spec["nombre"]
    nb = int(spec.get("fotogramas", 24))
    fps = spec.get("fps", 24)
    ident = hashlib.sha1(nombre.encode("utf-8")).hexdigest()[:16]
    ids = {e["id"] for e in spec["elementos"]}
    nombres_col = {c["nombre"] for c in spec["columnas"]}

    raiz = _el("project", {"source": CABECERA_SOURCE, "version": "2402", "build": "23443", "creator": "sintetico"})
    els = ET.SubElement(raiz, "elements")
    for e in spec["elementos"]:
        el = _el("element", {"id": e["id"], "elementName": e["nombre"], "elementFolder": e.get("carpeta", e["nombre"]),
                             "pixmapFormat": 2, "scanType": 2, "fieldChart": 12, "vectorType": 2, "rootFolder": "elements"})
        if e.get("dibujos"):
            dr = ET.SubElement(el, "drawings")
            for d in e["dibujos"]:
                dr.append(_el("dwg", {"name": d}))
        els.append(el)
    op = ET.SubElement(raiz, "options")
    op.append(_el("metrics", {"unitAspectRatioX": 4, "unitAspectRatioY": 3, "numberOfUnitsX": 24, "numberOfUnitsY": 24, "numberOfUnitsZ": 12}))
    op.append(_el("resolution", {"name": "HDTV_1080p24", "size": "1920,1080", "fovFit": "VerticalFitFov",
                                 "fov": "41.112090439166927", "projection": "PerspectiveProjection"}))
    op.append(_el("framerate", {"val": fps}))
    op.append(_el("zdragging", {"val": True}))
    op.append(_el("zOrderCompatibilityWith7_3", {"val": False}))
    op.append(_el("pixelPerModelUnitForVectorLayers", {"val": "0.28800000000000009"}))
    op.append(_el("pixelPerModelUnitForBitmapLayers", {"val": "0.28800000000000009"}))
    op.append(_el("scaleFactor", {"val": 1}))
    ET.SubElement(raiz, "timelineMarkers")
    scs = ET.SubElement(raiz, "scenes")
    sc = _el("scene", {"name": "Top", "id": ident, "nbframes": nb, "startFrame": 1, "stopFrame": nb})
    scs.append(sc)
    cs = ET.SubElement(sc, "columns")
    for c in spec["columnas"]:
        cs.append(_columna(c, ids))
    so = ET.SubElement(sc, "options")
    so.append(_el("defaultDisplay", {"val": "Display"}))
    rg = _el("rootgroup", {"name": "Top"})
    rg.append(_el("options", hijos=[_el("collapsed", {"val": False})]))
    # validar columnas referenciadas
    def refs(ns):
        for n in ns:
            for v in n.get("attrs", {}).values():
                col = v.get("col") if isinstance(v, dict) else None
                if col and col not in nombres_col:
                    raise ValueError(f"nodo '{n['nombre']}': columna '{col}' no definida")
            if n["tipo"] == "GROUP":
                refs(n.get("nodos", []))
    refs(spec["nodos"])
    nl, ll = _grupo_contenido(spec["nodos"], spec.get("enlaces", []), "Top", [0])
    rg.append(nl)
    rg.append(ll)
    sc.append(rg)
    uc = ET.SubElement(sc, "unconnectedComposite")
    uc.append(_modulo({"tipo": "COMPOSITE", "nombre": "Unconnected_Composite", "pos": "0,0,0"}, 0))
    ET.SubElement(sc, "timelineOrderer")
    sy = ET.SubElement(raiz, "symbols")
    fo = ET.SubElement(sy, "folder")
    fo.set("name", "Simbolos")
    fo.append(_el("scene", {"id": ident}))
    tl = ET.SubElement(raiz, "timeline")
    tl.append(_el("scene", {"id": ident}))
    return raiz


# ---------------------------------------------------------------- escritura propia (indentacion de 1 espacio, LF)
def _esc(v, num):
    out = []
    crudo = isinstance(v, Crudo)
    for ch in v:
        o = ord(ch)
        if ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        elif ch == '"':
            out.append("&quot;")
        elif ch == "\n":
            out.append("\n" if crudo else "&#10;")
        elif ch == "\r":
            out.append("&#13;")
        elif ch == "\t":
            out.append("&#9;")
        elif o > 127 and num:
            out.append(f"&#{o};")
        else:
            out.append(ch)
    return "".join(out)


def _escribir(e, nivel, out, num):
    sp = " " * nivel
    a = "".join(f' {k}="{_esc(v, num)}"' for k, v in e.attrib.items())
    if len(e) == 0:
        out.append(f"{sp}<{e.tag}{a}/>\n")
        return
    out.append(f"{sp}<{e.tag}{a}>\n")
    for h in e:
        _escribir(h, nivel + 1, out, num)
    out.append(f"{sp}</{e.tag}>\n")


def a_bytes(spec):
    cod = spec.get("codificacion", {})
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n']
    _escribir(construir(spec), 0, out, bool(cod.get("entidades_numericas")))
    datos = "".join(out).encode("utf-8")
    return (b"\xef\xbb\xbf" + datos) if cod.get("bom") else datos


# ---------------------------------------------------------------- CLI
def procesar(ruta_spec, salida=None, verificar=False):
    ruta_spec = Path(ruta_spec)
    spec = json.loads(ruta_spec.read_text(encoding="utf-8"))
    datos = a_bytes(spec)
    destino = Path(salida) if salida else ruta_spec.with_suffix(".xstage")
    if verificar:
        if not destino.exists():
            print(f"FALTA {destino.name}")
            return False
        igual = destino.read_bytes() == datos
        print(("OK    " if igual else "DIFIERE ") + destino.name)
        return igual
    destino.write_bytes(datos)
    print(f"escrito {destino.name} ({len(datos)} bytes)")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("espec", nargs="?")
    ap.add_argument("-o", "--salida")
    ap.add_argument("--dir")
    ap.add_argument("--verificar", action="store_true")
    a = ap.parse_args(argv)
    if a.dir:
        specs = sorted(p for p in Path(a.dir).glob("*.json") if not p.name.endswith(".esperado.json"))
    elif a.espec:
        specs = [Path(a.espec)]
    else:
        ap.error("falta ESPEC.json o --dir")
    ok = all([procesar(p, a.salida if not a.dir else None, a.verificar) for p in specs])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
