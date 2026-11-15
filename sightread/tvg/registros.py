"""Registros del formato .tvg: etiqueta + forma de largo + cuerpo (sala limpia, solo desde la especificacion).

# TVG-v1 §3.1: D2 = etiqueta, byte de forma F, largo, cuerpo.
# CENSO-12: F es una MASCARA de bytes del largo u32: el bit i de F indica que el byte i del largo (little-endian) esta presente;
#   los ausentes valen 0. Vistos: F=1 (byte 0), 2 (byte 1: largo = byte*256), 3 (bytes 0-1), 7 (0-2), 13 (bytes 0, 2 y 3), 15 (0-3).
#   F=4, 5, 6 y el resto de 1..15 salen de la misma regla (sin ejemplo propio).
# TVG-v0 §7.2: D1 = etiqueta, u32 largo, cuerpo.
"""
import struct


class TvgIlegible(Exception):
    """El archivo .tvg no se puede leer con lo que la especificacion cubre."""


def leer_registro(b, pos, d1=False, fin=None):
    """Lee la cabecera de un registro en `pos`. Devuelve (etiqueta: bytes, inicio_cuerpo, fin_cuerpo)."""
    fin = len(b) if fin is None else fin
    if pos + 5 > fin:
        raise TvgIlegible(f"registro truncado en {pos}")
    etq = bytes(b[pos:pos + 4])
    if d1:
        if pos + 8 > fin:
            raise TvgIlegible(f"registro D1 truncado en {pos}")
        (largo,) = struct.unpack_from("<I", b, pos + 4)
        ini = pos + 8
    else:
        f = b[pos + 4]
        if not 1 <= f <= 15:
            raise TvgIlegible(f"forma F={f} en el registro {etq!r} (posicion {pos}) no soportada")
        largo, ini = 0, pos + 5
        for i in range(4):
            if f >> i & 1:
                if ini >= fin:
                    raise TvgIlegible(f"registro truncado en {pos}")
                largo |= b[ini] << (8 * i)
                ini += 1
    if ini + largo > fin:
        raise TvgIlegible(f"registro {etq!r} se sale del bloque ({ini}+{largo}>{fin})")
    return etq, ini, ini + largo


def registros(b, ini, fin, d1=False):
    """Recorre los registros consecutivos de b[ini:fin]. Rinde (etiqueta, inicio_cuerpo, fin_cuerpo)."""
    pos = ini
    while pos < fin:
        etq, i, f = leer_registro(b, pos, d1, fin)
        yield etq, i, f
        pos = f


def u32(b, pos):
    if pos + 4 > len(b):
        raise TvgIlegible(f"lectura de u32 fuera de rango en {pos}")
    return struct.unpack_from("<I", b, pos)[0]
