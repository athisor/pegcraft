"""xmlfiel: ida y vuelta SIN PERDIDA de un XML (pensado para .xstage), stdlib puro.

Idea (prototipo de factibilidad, (doc interna omitida):
  * `ida(bytes) -> dict` (JSON puro): arbol generico con el ORDEN de elementos y atributos, valores de atributo
    ya decodificados, y solo las EXCEPCIONES lexicas (lo que difiere de la forma canonica de Harmony: sangria de
    1 espacio por nivel, comillas dobles, `<a/>` para vacio, fin de linea unico). Si el archivo ya es canonico, el
    arbol no lleva ni un byte de formato.
  * `vuelta(dict) -> bytes`: reconstruye. Sin ediciones el resultado es identico byte a byte. Una excepcion lexica
    de etiqueta (`ini`) solo se respeta si sus atributos siguen siendo los del arbol: el arbol es la unica fuente de
    verdad y el residuo lexico se descarta solo donde hubo edicion.
  * Total: lo que no se puede tokenizar (XML mal formado, otra codificacion) se guarda crudo en base64.

Nodo elemento = [tag, [n1, v1, n2, v2, ...], [hijos...]] (+ {flags} opcional: ini, fin, par).
Hijo str = hueco/texto EXPLICITO (crudo) antes del nodo siguiente o del cierre; ausente = hueco canonico.
Hijo dict = {"k": cdata|com|pi|doctype, "r": crudo}.
"""
import re, base64, hashlib

FORMATO, VERSION = "pegcraft.xmlfiel", 1

_TOKEN = re.compile(
    r"<!\[CDATA\[.*?\]\]>"
    r"|<!--.*?-->"
    r"|<\?.*?\?>"
    r"|<!DOCTYPE(?:[^>\[]|\[.*?\])*>"
    r"|</[^>]*>"
    r"|<[A-Za-z_:][^\s/>]*(?:\s+[^\s=/>]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*\s*/?>",
    re.S)
_ATTR = re.compile(r"\s+([^\s=/>]+)\s*=\s*(\"[^\"]*\"|'[^']*')")
_NAME = re.compile(r"<([^\s/>]+)")
_ENT = re.compile(r"&(#x[0-9A-Fa-f]+|#[0-9]+|lt|gt|amp|quot|apos);")
_ENTS = {"lt": "<", "gt": ">", "amp": "&", "quot": '"', "apos": "'"}


class NoCanonizable(Exception):
    pass


def _dec1(m):
    e = m.group(1)
    if e[0] == "#":
        return chr(int(e[2:], 16) if e[1] == "x" else int(e[1:]))
    return _ENTS[e]


def dec(raw):
    """Valor de atributo crudo -> valor. Solo referencias; los saltos de linea crudos se conservan."""
    return _ENT.sub(_dec1, raw) if "&" in raw else raw


def esc(v):
    if "&" in v or "<" in v or ">" in v or '"' in v:
        v = v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return v


def _ini(tag, attrs, auto):
    p = ["<", tag]
    for i in range(0, len(attrs), 2):
        p += [" ", attrs[i], '="', esc(attrs[i + 1]), '"']
    p.append("/>" if auto else ">")
    return "".join(p)


def _attrs_de(tok):
    tag = _NAME.match(tok).group(1)
    attrs = []
    for am in _ATTR.finditer(tok, len(tag) + 1):
        attrs.append(am.group(1)); attrs.append(dec(am.group(2)[1:-1]))
    return tag, attrs


def _arbol(data):
    bom = data[:3] == b"\xef\xbb\xbf"
    txt = (data[3:] if bom else data).decode("utf-8")
    crlf = txt.count("\r\n")
    eol = "\r\n" if crlf > txt.count("\n") - crlf else "\n"   # fin de linea MAYORITARIO (hay CRLF sueltos dentro de scripts)
    raiz = []
    pila = [[[None, None, raiz], 0]]
    pos = 0
    for m in _TOKEN.finditer(txt):
        a, b = m.span()
        hueco = txt[pos:a]; pos = b
        if "<" in hueco:
            raise NoCanonizable(f"'<' suelto cerca del caracter {a}")
        tok = m.group()
        prof = len(pila) - 1
        c1 = tok[1]
        if c1 == "/":
            if prof == 0:
                raise NoCanonizable(f"cierre sin apertura en {a}")
            nodo, n = pila.pop()
            canon = (eol + " " * (prof - 1)) if n else ""
            if hueco != canon:
                nodo[2].append(hueco)
            if tok != "</" + nodo[0] + ">":
                if tok[2:-1].strip() != nodo[0]:
                    raise NoCanonizable(f"cierre {tok!r} no coincide con <{nodo[0]}> en {a}")
                _flag(nodo)["fin"] = tok
            if not nodo[2]:
                _flag(nodo)["par"] = 1
            continue
        hijos = pila[-1][0][2]
        canon = (("" if pila[0][1] == 0 else eol) if prof == 0 else eol + " " * prof)
        if hueco != canon:
            hijos.append(hueco)
        pila[-1][1] += 1
        if c1 == "!" or c1 == "?":
            k = "cdata" if tok.startswith("<![CDATA[") else "com" if tok.startswith("<!--") else "pi" if c1 == "?" else "doctype"
            hijos.append({"k": k, "r": tok})
            continue
        tag, attrs = _attrs_de(tok)
        auto = tok.endswith("/>")
        nodo = [tag, attrs, []]
        if _ini(tag, attrs, auto) != tok:
            nodo.append({"ini": tok})
        hijos.append(nodo)
        if not auto:
            pila.append([nodo, 0])
    if len(pila) != 1:
        raise NoCanonizable("elementos sin cerrar")
    final = txt[pos:]
    if "<" in final:
        raise NoCanonizable("'<' suelto al final")
    if final != eol:
        raiz.append(final)
    return {"bom": bom, "eol": eol, "codificacion": "utf-8", "nodos": raiz}


def _flag(nodo):
    if len(nodo) == 3:
        nodo.append({})
    return nodo[3]


def ida(data: bytes) -> dict:
    """Bytes del XML -> documento (dict serializable a JSON). Total y determinista."""
    doc = {"formato": FORMATO, "version": VERSION, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    try:
        doc.update(_arbol(data))
    except (NoCanonizable, UnicodeDecodeError) as e:
        doc["motivo_crudo"] = str(e)
        doc["crudo_b64"] = base64.b64encode(data).decode("ascii")
    return doc


def vuelta(doc: dict, sonda=None) -> bytes:
    """Documento -> bytes. `sonda(ruta_tags, nodo, n_caracteres)` se llama al cerrar cada elemento (para medir)."""
    if "crudo_b64" in doc:
        return base64.b64decode(doc["crudo_b64"])
    eol = doc["eol"]
    out = []
    cuenta = [0]
    ruta = []

    def w(s):
        out.append(s); cuenta[0] += len(s)

    def contenido(hijos, d, top):
        pend = None; n = 0
        for h in hijos:
            if isinstance(h, str):
                pend = h; continue
            if pend is None:
                pend = (("" if n == 0 else eol) if top else eol + " " * d)
            w(pend); pend = None; n += 1
            if isinstance(h, dict):
                w(h["r"])
            else:
                elem(h, d)
        return n, pend

    def elem(n, d):
        tag, attrs, hijos = n[0], n[1], n[2]
        fl = n[3] if len(n) > 3 else None
        auto = not hijos and not (fl and fl.get("par"))
        c0 = cuenta[0]
        ini = None
        if fl and "ini" in fl:
            raw = fl["ini"]
            if raw.endswith("/>") == auto and _attrs_de(raw) == (tag, attrs):
                ini = raw
        w(ini if ini is not None else _ini(tag, attrs, auto))
        if not auto:
            ruta.append(tag)
            k, pend = contenido(hijos, d + 1, False)
            ruta.pop()
            w(pend if pend is not None else ((eol + " " * d) if k else ""))
            fin = fl.get("fin") if fl else None
            w(fin if fin and fin[2:-1].strip() == tag else "</" + tag + ">")
        if sonda:
            sonda(ruta, n, cuenta[0] - c0)

    k, pend = contenido(doc["nodos"], 0, True)
    w(pend if pend is not None else eol)
    b = "".join(out).encode("utf-8")
    return (b"\xef\xbb\xbf" + b) if doc.get("bom") else b


def recorrer(doc):
    """Itera (ruta_tags tuple, nodo elemento) en orden de documento."""
    pila = [((), h) for h in reversed(doc.get("nodos", [])) if isinstance(h, list)]
    while pila:
        ruta, n = pila.pop()
        yield ruta, n
        r2 = ruta + (n[0],)
        for h in reversed(n[2]):
            if isinstance(h, list):
                pila.append((r2, h))


def attr(nodo, nombre, defecto=None):
    a = nodo[1]
    for i in range(0, len(a), 2):
        if a[i] == nombre:
            return a[i + 1]
    return defecto


def poner_attr(nodo, nombre, valor):
    a = nodo[1]
    for i in range(0, len(a), 2):
        if a[i] == nombre:
            a[i + 1] = valor; return
    a += [nombre, valor]
