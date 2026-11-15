"""Modelo de un dibujo .tvg: paleta, artes -> capas -> trazos, y matrices TGCO.

Citas: TVG-v1 §3-§4, TVG-v0 §5-§7, CENSO-n (LT\\procedencia.md).
"""
import struct

from . import contenedor
from .registros import TvgIlegible, leer_registro, registros, u32

# TVG-v1 §3.2: la etiqueta fija el arte. Las mayusculas (TUAA...) siguen la misma gramática (CENSO-3).
ARTES = {b"TUAA": "underlay", b"TCAA": "colour", b"TLAA": "line", b"TOAA": "overlay"}
ORDEN_ARTES = ("underlay", "colour", "line", "overlay")
ID_DEFECTO = "0000000000000003"   # TVG-v1 §4: «Vectorized Line», negro opaco


def _hex_id(b, pos):
    return "%016x" % struct.unpack_from("<Q", b, pos)[0]


def leer_paleta(carga, d1):
    """TPAL -> {id_hex16: {nombre, rgba, paleta}}; rgba = None en las entradas de textura.  # TVG-v1 §4, CENSO-13"""
    out = {}
    if len(carga) < 4:
        return out
    k = u32(carga, 0)
    pos = 4
    for _ in range(k):
        kind = carga[pos]
        if kind == 0x79:         # 79 00 + u32 subtipo (0 = solido: TCSC; 1 = degradado: TCGC, CENSO-13)
            etq, i, f = leer_registro(carga, pos + 6, d1)
            if etq == b"TCSC" and f - i >= 4:
                rgba, tipo = tuple(carga[i:i + 4]), "solido"   # TCSC 01 04 R G B A: forma F=1 de 4 B
            elif etq == b"TCGC":
                rgba, tipo = None, "degradado"   # las paradas y la matriz estan en la .plt y el TGCO
            else:
                raise TvgIlegible(f"se esperaba TCSC o TCGC y hay {etq!r}")
        elif kind == 0x7C:       # textura (CENSO-13): 7c 00 + registro TCTC (imagen, no se decodifica) + TCID
            etq, i, f = leer_registro(carga, pos + 2, d1)
            if etq != b"TCTC":
                raise TvgIlegible(f"se esperaba TCTC y hay {etq!r}")
            rgba, tipo = None, "textura"
        else:
            raise TvgIlegible(f"tipo de entrada {kind:#x} desconocido")
        pos = f
        etq, i, f = leer_registro(carga, pos, d1)
        if etq != b"TCID":
            raise TvgIlegible(f"se esperaba TCID y hay {etq!r}")
        ln = u32(carga, i)
        nombre = carga[i + 4:i + 4 + 2 * ln].decode("utf-16-le", "replace")
        q = i + 4 + 2 * ln
        cid = _hex_id(carga, q)
        lp = u32(carga, q + 8)
        pal = carga[q + 12:q + 12 + 2 * lp].decode("utf-16-le", "replace")
        out.setdefault(cid, {"nombre": nombre, "rgba": rgba, "paleta": pal, "tipo": tipo})
        pos = f
    return out


def _id_tgco(cuerpo):
    # TGCO de 66 B: el id esta 17 B antes del final (TVG-v1 §3.5); en 114 B tambien en [49:57] (CENSO-2)
    if len(cuerpo) < 57:
        raise TvgIlegible(f"TGCO de {len(cuerpo)} B")
    return _hex_id(cuerpo, 49)


def _ranura(b, p, d1, objs, ctx):
    """Ranura de color de un TGSD -> (id_color|None, siguiente_pos).  # TVG-v1 §3.5"""
    t = b[p]
    if t == 0:
        ref = u32(b, p + 1)
        if ref == 0:
            return None, p + 5
        o = objs.get(ref)
        if o is None or o[0] != "color":
            raise TvgIlegible(f"TGSD: referencia de color {ref} sin resolver")
        return o[1], p + 5
    if t == 1:
        etq, i, f = leer_registro(b, p + 3, d1)
        if etq != b"TGCO":
            raise TvgIlegible(f"TGSD: se esperaba TGCO inline y hay {etq!r}")
        cuerpo = b[i:f]
        cid = _id_tgco(cuerpo)
        ctx["n"] += 1                       # TVG-v1 §3.6: cada TGCO inline toma un id de objeto
        objs[ctx["n"]] = ("color", cid)
        if len(cuerpo) in (66, 114) and cuerpo[0] == 1:
            ctx["tgco"].setdefault(cid, []).append(struct.unpack_from("<6d", cuerpo, 1))
        return cid, f
    raise TvgIlegible(f"TGSD: ranura de color con tipo {t}")


def _estilo(b, ini, d1, objs, ctx):
    """TGSD -> dict.  # TVG-v1 §3.5"""
    b0 = b[ini]
    p = ini + 1
    lapiz, ancho = None, 0.0
    if b0 & 4:
        ancho = struct.unpack_from("<f", b, p)[0]
        lapiz = _hex_id(b, p + 4)
        p += 12
    der, p = _ranura(b, p, d1, objs, ctx)
    izq, p = _ranura(b, p, d1, objs, ctx)
    return {"der": der, "izq": izq, "lapiz": lapiz, "ancho": ancho, "invisible": bool(b0 & 2)}


def _puntos(b, ini, fin):
    """TGBP -> (puntos, anclas).  # TVG-v1 §3.4"""
    n = u32(b, ini)
    m = (n + 7) // 8
    if fin - ini != 4 + m + 8 * n:
        raise TvgIlegible(f"TGBP de {fin - ini} B no cuadra con n={n}")
    masc = b[ini + 4:ini + 4 + m]
    anclas = [bool(masc[i >> 3] >> (i & 7) & 1) for i in range(n)]
    vals = struct.unpack_from(f"<{2 * n}f", b, ini + 4 + m)
    return list(zip(vals[0::2], vals[1::2])), anclas


def _perfil(b, ini, fin):
    """tGTB -> lista de llaves (t, izq(5), der(5)) o None si es otra forma.  # TVG-v1 §3.7"""
    n = fin - ini
    if n < 40 or (n - 40) % 44:
        return None
    k = u32(b, ini + 7)
    if 11 + 44 * k + 29 != n:
        return None
    vals = struct.unpack_from(f"<{11 * k}f", b, ini + 11)
    return [(vals[i * 11], tuple(vals[i * 11 + 1:i * 11 + 6]), tuple(vals[i * 11 + 6:i * 11 + 11])) for i in range(k)]


def _trazo(b, ini, fin, d1, objs, ctx):
    """TGVS -> trazo.  # TVG-v1 §3.3, §3.6"""
    etq, i, f = leer_registro(b, ini, d1, fin)
    if etq != b"TGSD":
        raise TvgIlegible(f"TGVS: se esperaba TGSD y hay {etq!r}")
    estilo = _estilo(b, i, d1, objs, ctx)
    p = f
    if p >= fin:
        raise TvgIlegible("TGVS sin geometria")
    flag = b[p]
    ref = None
    if flag == 1:
        etq, i, f = leer_registro(b, p + 1, d1, fin)
        if etq != b"TGBP":
            raise TvgIlegible(f"TGVS: se esperaba TGBP y hay {etq!r}")
        puntos, anclas = _puntos(b, i, f)
        ctx["n"] += 1                       # el trazo con geometria propia toma el id siguiente (TVG-v1 §3.6)
        objs[ctx["n"]] = ("trazo", puntos, anclas)
        p = f
    elif flag == 0:
        ref = u32(b, p + 1)
        o = objs.get(ref)
        if o is None or o[0] != "trazo":
            raise TvgIlegible(f"TGVS: referencia de trazo {ref} sin resolver")
        puntos, anclas = o[1], o[2]
        p += 5
    else:
        raise TvgIlegible(f"TGVS: marca de geometria {flag}")
    perfil = None
    for etq, i, f in registros(b, p, fin, d1):
        if etq == b"tGTB":
            perfil = _perfil(b, i, f)
            if perfil is None:
                ctx["avisos"].append("tGTB con forma alternativa (%d B)" % (f - i))
        # tGTI (D1): sin interpretar (TVG-v1 §7)
    cerrado = len(puntos) > 1 and puntos[0] == puntos[-1]   # TVG-v1 §3.4
    return {"puntos": puntos, "anclas": anclas, "cerrado": cerrado, "estilo": estilo, "perfil": perfil, "ref": ref}


def _items(b, p, m, d1, objs, ctx, capas):
    """m elementos `prefijo u32 | registro` desde p: prefijo 2 = TGLY (capa); prefijo 1 = TGND, que contiene mas
    capas (CENSO-14) o es una capa de texto (se omite). Devuelve la posicion siguiente."""
    for _ in range(m):
        pref = u32(b, p)
        etq, i, f = leer_registro(b, p + 4, d1)
        if pref == 2 and etq == b"TGLY":
            v = struct.unpack_from("<H", b, i + 2)[0]
            trazos = []
            pos = i + 6
            for _ in range(v):
                e2, i2, f2 = leer_registro(b, pos, d1, f)
                if e2 != b"TGVS":
                    raise TvgIlegible(f"se esperaba TGVS y hay {e2!r}")
                trazos.append(_trazo(b, i2, f2, d1, objs, ctx))
                pos = f2
            capas.append({"trazos": trazos})
        elif pref == 1 and etq == b"TGND":
            # CENSO-14: TGND = u32 n + n elementos (prefijo 2 | TGLY, o 1 | TGND anidado): capas de dibujo agrupadas;
            # si el primer elemento es otro (prefijo 3 | TGTL) es una capa de texto y se omite
            if f - i >= 16 and b[i + 4] in (1, 2) and b[i + 5:i + 8] == b"\x00\x00\x00" and b[i + 8:i + 12] in (b"TGLY", b"TGND"):
                _items(b, i + 4, u32(b, i), d1, objs, ctx, capas)
            else:
                ctx["avisos"].append("capa de texto (TGND) omitida")
        else:
            raise TvgIlegible(f"elemento de capa con prefijo {pref} y registro {etq!r} no soportado")
        p = f
    return p


def leer_arte(carga, d1, tgco, avisos):
    """Carga de arte -> {capas: [{trazos: [...]}]}.  # TVG-v1 §3.2"""
    if len(carga) < 3 or carga[0] != 0:
        raise TvgIlegible("carga de arte con cabecera inesperada")
    ctx = {"n": 0, "tgco": tgco, "avisos": avisos}
    objs = {}
    capas = []
    p = 2
    if carga[1]:
        p = _items(carga, p + 4, u32(carga, p), d1, objs, ctx, capas)
    # cola: 00 | 01 u32 1 i32 -1 u32 0 u32 1 registro TGND (capa de texto, no se dibuja)  # TVG-v1 §3.2, §7
    if p < len(carga) and carga[p] == 1:
        avisos.append("capa de texto (TGND) omitida")
    return {"capas": capas}


def decodificar(datos):
    """bytes de un .tvg -> modelo {disp, paleta, artes, tgco, avisos}."""
    c = contenedor.abrir(datos)
    d1 = c["disp"] == "D1"
    modelo = {"disp": c["disp"], "paleta": {}, "artes": {}, "tgco": {}, "avisos": []}
    for etq, _modo, carga in c["bloques"]:
        try:
            if etq == b"TPAL":
                try:
                    modelo["paleta"] = leer_paleta(carga, d1)
                except (TvgIlegible, struct.error, IndexError):
                    if not d1:
                        raise
                    modelo["avisos"].append("paleta D1 ilegible (texturas)")
            elif etq.upper() in ARTES:
                modelo["artes"][ARTES[etq.upper()]] = leer_arte(carga, d1, modelo["tgco"], modelo["avisos"])
        except struct.error as e:
            raise TvgIlegible(f"{etq.decode(errors='replace')}: bloque truncado ({e})") from None
        except TvgIlegible as e:
            raise TvgIlegible(f"{etq.decode(errors='replace')}: {e}") from None
    modelo["artes"] = {k: modelo["artes"][k] for k in ORDEN_ARTES if k in modelo["artes"]}
    return modelo
