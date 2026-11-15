"""Contenedor .tvg: cabecera, CERT, ENDT, sub-bloques (UNCO/ZLIB), disposiciones D1/D2.

# TVG-v1 §2 / TVG-v0 §3-§5.
cabecera (20 B) | CERT | ENDT u32 0 | UNCO u32 S | [cuerpo + TTOC] | cola previa | SIGN
S != 0 -> D1; S == 0 -> D2.
D1: ... UNCO S | subbloque* | TTOC n (etq,desp)* | cola | SIGN
D2: ... UNCO 0 | TTOC 0 n (etq,desp,0)* | UNCO S 0 | subbloque* | cola | SIGN
"""
import struct
import zlib

from .registros import TvgIlegible

CABECERA = b"OTVGfull"


def _u32(b, p):
    if p + 4 > len(b):
        raise TvgIlegible(f"archivo truncado en {p}")
    return struct.unpack_from("<I", b, p)[0]


def abrir(datos):
    """Devuelve {"disp": "D1"|"D2", "bloques": [(etiqueta: bytes, modo: bytes, carga: bytes)]} con las cargas descomprimidas."""
    b = bytes(datos)
    if len(b) < 40 or b[:8] != CABECERA:
        raise TvgIlegible("no es un .tvg (falta la firma OTVGfull)")
    # TVG-v0 §3.1: versión 1009; otros valores se rechazan hasta ampliar la muestra
    ver = _u32(b, 8)
    if ver != 1009:
        raise TvgIlegible(f"version de formato {ver} no soportada")
    # El CERT es opcional para el lector: los .tvg sinteticos de sintetico/ no lo llevan (ni firma).
    p = 20 + 8 + _u32(b, 24) if b[20:24] == b"CERT" else 20  # el bloque CERT ocupa 8 + L (TVG-v1 §2)
    if b[p:p + 4] != b"ENDT" or b[p + 8:p + 12] != b"UNCO":
        raise TvgIlegible("falta ENDT/UNCO tras la cabecera")
    s = _u32(b, p + 12)
    p += 16
    d1 = s != 0
    if d1:
        cuerpo, fin = p, p + s
    else:
        # D2: tabla TTOC antes del cuerpo (TVG-v0 §5.3)
        if b[p:p + 4] != b"TTOC":
            raise TvgIlegible("D2 sin TTOC")
        n = _u32(b, p + 8)
        p += 12 + 12 * n
        if b[p:p + 4] != b"UNCO":
            raise TvgIlegible("D2 sin UNCO de cuerpo")
        s = _u32(b, p + 4)
        cuerpo, fin = p + 12, p + 12 + s
    if fin > len(b):
        raise TvgIlegible("el cuerpo se sale del archivo")
    bloques = []
    p = cuerpo
    while p < fin:
        etq, modo = b[p:p + 4], b[p + 4:p + 8]
        if modo == b"UNCO":
            n = _u32(b, p + 8)
            ini = p + (12 if d1 else 16)
            carga = b[ini:ini + n]
            p = ini + n
            if len(carga) != n:
                raise TvgIlegible(f"sub-bloque {etq!r} truncado")
        elif modo == b"ZLIB":
            if d1:
                c, u = _u32(b, p + 8), _u32(b, p + 12)
                ini, nf = p + 16, c - 4
                p = p + 12 + c
            else:
                c, u = _u32(b, p + 8), _u32(b, p + 16)
                ini, nf = p + 24, c - 8
                p = p + 16 + c
            try:
                carga = zlib.decompress(b[ini:ini + nf])
            except zlib.error as e:
                raise TvgIlegible(f"flujo zlib de {etq!r} invalido: {e}")
            if len(carga) != u:
                raise TvgIlegible(f"sub-bloque {etq!r}: largo descomprimido {len(carga)} != {u}")
        else:
            raise TvgIlegible(f"sub-bloque {etq!r} con modo {modo!r} desconocido")
        bloques.append((etq, modo, carga))
    if p != fin:
        raise TvgIlegible("los sub-bloques no cuadran con el tamano del cuerpo")
    return {"disp": "D1" if d1 else "D2", "bloques": bloques}
