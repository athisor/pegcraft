"""Modelo de dibujo v1, forma SVG: apariencia ya resuelta (la pinta cualquier visor) + datos del trazo en un espacio de nombres propio.

    <svg xmlns=SVG xmlns:lotte=NS viewBox=... lotte:version="1" lotte:precision="f32"|"f64">
      <metadata><lotte:drawing state units y> <lotte:source/> <lotte:opaque/>* <lotte:color/>* <lotte:gradient/>* </lotte:drawing></metadata>
      <g transform="matrix(1 0 0 -1 0 0)"> ...apariencia resuelta: DERIVADA, se regenera, no se edita... </g>
      <g lotte:role="data" display="none" transform="matrix(1 0 0 -1 0 0)">
        <g lotte:art="line"><g lotte:layer="0">
          <path id="a2-c0-t0" d="M .. C .." fill="none" stroke="none" lotte:line=ID lotte:width=.. lotte:knots="t,izq,der;.." lotte:interp=.. lotte:raw=..
                lotte:fill-left=ID lotte:fill-right=ID lotte:invisible="true"/>
          <path id="a2-c0-t1" lotte:geometry-of="a2-c0-t0" .../>

`d` es la linea central: M, y por cada ancla L / Q / C segun lleve 0, 1 o 2 tiradores antes. Si los puntos no caben en ese patron
van en `lotte:points="x,y,1;x,y,0;..."`. Los datos del trazo mandan; la apariencia resuelta se recalcula con `sightread.tvg.a_svg`.
Especificacion: docs/formato/modelo-de-dibujo.md
"""
import struct
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

from . import modelo as M

SVG = "http://www.w3.org/2000/svg"
NS = "https://lotte.dev/ns/draw"      # identifica el formato; el prefijo (`lotte`) es libre en XML
PREFIJO = "lotte"
_EJE = 'transform="matrix(1 0 0 -1 0 0)"'


def _f32(x):
    try:
        return struct.unpack("<f", struct.pack("<f", x))[0]
    except (OverflowError, struct.error):
        return None


def _numeros(d):
    for a in d["arts"]:
        for capa in a["layers"]:
            for s in capa["strokes"]:
                for p in s.get("points", ()):
                    yield p[0]
                    yield p[1]
                if "width" in s:
                    yield s["width"]
                pf = s.get("profile")
                if pf:
                    for k in pf["knots"]:
                        yield from k
                    for r in pf.get("raw") or ():
                        yield from r


def _escritor(f32):
    def num(x):
        x = float(x)
        if f32:
            for n in (7, 8, 9):          # 9 cifras bastan para devolver un f32 exacto
                s = "%.*g" % (n, x)
                if _f32(float(s)) == x:
                    return s
        return repr(x)
    return num


def _d(pts, num):
    """Linea central como `d` (M L Q C absolutos), o None si los puntos no caben en ese patron."""
    if not pts or not pts[0][2] or not pts[-1][2]:
        return None
    out, ctl = ["M %s %s" % (num(pts[0][0]), num(pts[0][1]))], []
    for x, y, ancla in pts[1:]:
        if not ancla:
            ctl.append((x, y))
            continue
        if len(ctl) > 2:
            return None
        out.append("LQC"[len(ctl)] + " " + " ".join("%s %s" % (num(px), num(py)) for px, py in ctl + [(x, y)]))
        ctl = []
    return " ".join(out)


def _at(nombre, valor):
    return "%s:%s=%s" % (PREFIJO, nombre, quoteattr(str(valor)))


def _trazo(s, num):
    at = ["id=" + quoteattr(s["id"])]
    if "geometry_of" in s:
        at.append(_at("geometry-of", s["geometry_of"]))
    else:
        d = _d(s["points"], num)
        if d is not None:
            at.append('d="%s"' % d)
        else:
            at.append(_at("points", ";".join("%s,%s,%d" % (num(x), num(y), a) for x, y, a in s["points"])))
    at.append('fill="none" stroke="none"')
    if "line" in s:
        at += [_at("line", s["line"]), _at("width", num(s["width"]))]
    pf = s.get("profile")
    if pf:
        at += [_at("knots", ";".join(",".join(num(v) for v in k) for k in pf["knots"])), _at("interp", pf["interp"])]
        if "raw" in pf:
            at.append(_at("raw", ";".join(",".join(num(v) for v in r) for r in pf["raw"])))
    for k in ("fill_left", "fill_right"):
        if k in s:
            at.append(_at(k.replace("_", "-"), s[k]))
    if s.get("invisible"):
        at.append(_at("invisible", "true"))
    return "<path %s/>" % " ".join(at)


def a_svg(d):
    """dibujo -> texto SVG (apariencia resuelta + datos del trazo)."""
    from sightread.tvg import a_svg as resolver
    base = resolver(M.a_modelo_lector(d))                # <svg xmlns=... viewBox=...><g transform=...>...</g></svg>
    corte = base.index(">")
    f32 = all(_f32(float(v)) == float(v) for v in _numeros(d))
    num = _escritor(f32)
    meta = ["<%s:drawing state=%s units=%s y=%s>" % (PREFIJO, quoteattr(d["state"]), quoteattr(d["units"]["name"]), quoteattr(d["units"]["y"]))]
    if "source" in d:
        meta.append("<%s:source %s/>" % (PREFIJO, " ".join("%s=%s" % (k, quoteattr(str(v))) for k, v in sorted(d["source"].items()))))
    meta += ["<%s:opaque what=%s/>" % (PREFIJO, quoteattr(o)) for o in d.get("opaque", [])]
    for cid, c in d["palette"].items():
        rgba = "" if c.get("rgba") is None else " rgba=%s" % quoteattr(",".join(str(int(v)) for v in c["rgba"]))
        meta.append("<%s:color key=%s name=%s palette=%s kind=%s%s/>" % (PREFIJO, quoteattr(cid), quoteattr(c["name"]), quoteattr(c["palette"]),
                                                                       quoteattr(c["kind"]), rgba))
    for cid, ms in d.get("gradients", {}).items():
        meta += ["<%s:gradient color=%s m=%s/>" % (PREFIJO, quoteattr(cid), quoteattr(",".join(repr(float(v)) for v in mx))) for mx in ms]
    meta.append("</%s:drawing>" % PREFIJO)
    datos = []
    for a in d["arts"]:
        capas = "".join('<g %s>%s</g>' % (_at("layer", i), "".join(_trazo(s, num) for s in capa["strokes"])) for i, capa in enumerate(a["layers"]))
        datos.append('<g %s>%s</g>' % (_at("art", a["name"]), capas))
    return ("%s xmlns:%s=%s %s %s><metadata>%s</metadata>%s<g %s display=\"none\" %s>%s</g></svg>"
            % (base[:corte], PREFIJO, quoteattr(NS), _at("version", d["version"]), _at("precision", "f32" if f32 else "f64"),
               "".join(meta), base[corte + 1:-len("</svg>")], _at("role", "data"), _EJE, "".join(datos)))


def _de_d(d, num):
    pts, tok, i = [], d.split(), 0
    pares = {"M": 1, "L": 1, "Q": 2, "C": 3}
    while i < len(tok):
        c = tok[i]
        if c not in pares:
            raise ValueError("comando %r en la linea central: solo M, L, Q y C absolutos" % c)
        n = pares[c]
        vals = [num(v) for v in tok[i + 1:i + 1 + 2 * n]]
        if len(vals) != 2 * n:
            raise ValueError("linea central truncada")
        for j in range(n):
            pts.append([vals[2 * j], vals[2 * j + 1], j == n - 1])
        i += 1 + 2 * n
    return pts


def desde_svg(texto):
    """Texto SVG del modelo -> dibujo. Lee SOLO los datos del trazo; la apariencia resuelta se ignora."""
    raiz = ET.fromstring(texto)
    q = lambda n: "{%s}%s" % (NS, n)
    if raiz.get(q("version")) is None:
        raise ValueError("el SVG no trae datos del modelo de dibujo (falta %s:version)" % PREFIJO)
    f32 = raiz.get(q("precision")) == "f32"
    num = (lambda s: _f32(float(s))) if f32 else float
    lista = lambda s, sep=",": [num(v) for v in s.split(sep)] if s else []
    dw = raiz.find("{%s}metadata/%s" % (SVG, q("drawing")))
    if dw is None:
        raise ValueError("falta <metadata><%s:drawing>" % PREFIJO)
    d = {"version": int(raiz.get(q("version"))), "state": dw.get("state"), "units": {"name": dw.get("units"), "y": dw.get("y")},
         "opaque": [o.get("what") for o in dw.findall(q("opaque"))], "palette": {}, "gradients": {}, "arts": []}
    src = dw.find(q("source"))
    if src is not None:
        d["source"] = dict(src.attrib)
    for c in dw.findall(q("color")):
        d["palette"][c.get("key")] = {"name": c.get("name"), "palette": c.get("palette"), "kind": c.get("kind"),
                                      "rgba": [int(v) for v in c.get("rgba").split(",")] if c.get("rgba") is not None else None}
    for g in dw.findall(q("gradient")):
        d["gradients"].setdefault(g.get("color"), []).append([float(v) for v in g.get("m").split(",")])
    datos = next((g for g in raiz.findall("{%s}g" % SVG) if g.get(q("role")) == "data"), None)
    if datos is None:
        raise ValueError("falta el grupo de datos del trazo (%s:role=\"data\")" % PREFIJO)
    for ga in datos.findall("{%s}g" % SVG):
        cerrados, layers = {}, []
        for gl in ga.findall("{%s}g" % SVG):
            strokes = []
            for p in gl.findall("{%s}path" % SVG):
                s = {"id": p.get("id")}
                if p.get(q("geometry-of")) is not None:
                    s["geometry_of"] = p.get(q("geometry-of"))
                    s["closed"] = cerrados[s["geometry_of"]]
                else:
                    if p.get(q("points")) is not None:
                        pts = [[num(a), num(b), c == "1"] for a, b, c in (t.split(",") for t in p.get(q("points")).split(";") if t)]
                    else:
                        pts = _de_d(p.get("d") or "", num)
                    s["points"] = pts
                    s["closed"] = cerrados[s["id"]] = len(pts) > 1 and pts[0][:2] == pts[-1][:2]
                if p.get(q("line")) is not None:
                    s["line"], s["width"] = p.get(q("line")), num(p.get(q("width")))
                if p.get(q("knots")) is not None:
                    s["profile"] = {"knots": [lista(k) for k in p.get(q("knots")).split(";")], "interp": p.get(q("interp"))}
                    if p.get(q("raw")) is not None:
                        s["profile"]["raw"] = [lista(r) for r in p.get(q("raw")).split(";")]
                for k in ("fill-left", "fill-right"):
                    if p.get(q(k)) is not None:
                        s[k.replace("-", "_")] = p.get(q(k))
                if p.get(q("invisible")) == "true":
                    s["invisible"] = True
                strokes.append(s)
            layers.append({"strokes": strokes})
        d["arts"].append({"name": ga.get(q("art")), "layers": layers})
    return d
