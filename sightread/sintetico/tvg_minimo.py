"""tvg_minimo: escritor MINIMO de dibujos .tvg SINTETICOS (solo biblioteca estandar) que lee `sightread.tvg`.

Escribe la disposicion D2 con cabecera, `ENDT`, `TTOC`, los 8 sub-bloques, la `TPAL` y las cuatro cargas de arte. NO escribe el
bloque `CERT` ni el bloque `SIGN` (firma): el resultado NO es un archivo que Harmony acepte; sirve solo para las pruebas y los
ejemplos de quien consuma el paquete. Formato segun TVG-v1 §2-§4 y CENSO-12/13 de la sala limpia.

Dibujo (dict):
    {"paleta": [{"id": int, "rgba": (r, g, b, a), "nombre": str, "paleta": str}],
     "artes": {"underlay"|"colour"|"line"|"overlay": [capa, ...]}}      capa = [trazo, ...]
    trazo = {"puntos": [(x, y), ...], "anclas": [bool, ...] | None,     (None: todos anclas = segmentos rectos)
             "lapiz": (id_color, semiancho) | None, "izq": id_color | None, "der": id_color | None, "invisible": False}
El relleno de una region lo da el color de "der" (shaderRight) de los trazos que la recorren en sentido antihorario (y hacia arriba); "izq" es el de la region del otro lado (CENSO-20).

    python sintetico/tvg_minimo.py SALIDA.tvg     escribe un dibujo de demostracion (un cuadrado rojo con borde)
"""
import struct
import sys
import zlib

ARTES = ("underlay", "colour", "line", "overlay")
ETQ_ARTE = {"underlay": b"tUAA", "colour": b"tCAA", "line": b"tLAA", "overlay": b"tOAA"}


def _reg(tag, cuerpo):
    """Registro D2: etiqueta + F (mascara de bytes del largo) + largo + cuerpo."""
    n = len(cuerpo)
    f = 1 if n < 1 << 8 else 3 if n < 1 << 16 else 7 if n < 1 << 24 else 15
    largo = struct.pack("<I", n)
    return tag + bytes([f]) + bytes(largo[i] for i in range(4) if f >> i & 1) + cuerpo


def _tgbp(puntos, anclas):
    n = len(puntos)
    anclas = anclas or [True] * n
    masc = bytearray((n + 7) // 8)
    for i, a in enumerate(anclas):
        if a:
            masc[i >> 3] |= 1 << (i & 7)
    return struct.pack("<I", n) + bytes(masc) + b"".join(struct.pack("<ff", float(x), float(y)) for x, y in puntos)


def _tgco(cid):
    # TVG-v1 §3.5: 66 B; matriz identidad en [1:49], id en [49:57], 00 y 8 x ff
    return b"\x01" + struct.pack("<6d", 1, 0, 0, 1, 0, 0) + struct.pack("<Q", cid) + b"\x00" + b"\xff" * 8


def _arte(capas):
    if not capas:
        return b"\x00\x00\x00" + _reg(b"TGRV", bytes(8))
    n = 0                       # contador de ids de objeto del arte (TVG-v1 §3.6)
    definidos = {}              # id de color -> id de objeto
    out = b"\x00\x01" + struct.pack("<I", len(capas))
    for capa in capas:
        cuerpo = b""
        for t in capa:
            b0 = (4 if t.get("lapiz") else 0) | (2 if t.get("invisible") else 0)
            sd = bytes([b0])
            if t.get("lapiz"):
                sd += struct.pack("<fQ", float(t["lapiz"][1]), t["lapiz"][0])
            for lado in ("der", "izq"):
                c = t.get(lado)
                if not c:
                    sd += b"\x00" + struct.pack("<I", 0)
                elif c in definidos:
                    sd += b"\x00" + struct.pack("<I", definidos[c])
                else:
                    n += 1
                    definidos[c] = n
                    sd += b"\x01\xcd\x00" + _reg(b"TGCO", _tgco(c))
            sd += b"\x00\x00"
            n += 1
            cuerpo += _reg(b"TGVS", _reg(b"TGSD", sd) + b"\x01" + _reg(b"TGBP", _tgbp(t["puntos"], t.get("anclas"))))
        out += struct.pack("<I", 2) + _reg(b"TGLY", struct.pack("<HHH", 0, len(capa), 0) + cuerpo)
    return out + b"\x00" + _reg(b"TGRV", bytes(8))


def _tpal(paleta):
    out = struct.pack("<I", len(paleta))
    for c in paleta:
        nom, pal = c["nombre"].encode("utf-16-le"), c.get("paleta", "Paleta").encode("utf-16-le")
        out += b"\x79\x00\x00\x00\x00\x00" + _reg(b"TCSC", bytes(c["rgba"]))
        out += _reg(b"TCID", struct.pack("<I", len(nom) // 2) + nom + struct.pack("<Q", c["id"]) + struct.pack("<I", len(pal) // 2) + pal)
    return out


def _subbloque(tag, carga, comprimir):
    if comprimir:
        z = zlib.compress(carga, 6)
        if len(z) < len(carga):
            return tag + b"ZLIB" + struct.pack("<IIII", len(z) + 8, 0, len(carga), 0) + z
    return tag + b"UNCO" + struct.pack("<II", len(carga), 0) + carga


def escribir(dibujo):
    """dibujo -> bytes de un .tvg D2 sin CERT ni firma."""
    bloques = [(b"TVCI", bytes(20), False), (b"CREA", struct.pack("<I", 2), False), (b"AUIF", struct.pack("<I", 1 + len(dibujo["paleta"])), False)]
    for a in ARTES:
        bloques.append((ETQ_ARTE[a], _arte(dibujo.get("artes", {}).get(a, [])), True))
    bloques.append((b"TPAL", _tpal(dibujo["paleta"]), True))
    subs = [_subbloque(t, c, z) for t, c, z in bloques]
    desp, o = [], 0
    for s in subs:
        desp.append(o)
        o += len(s)
    ttoc = b"TTOC" + struct.pack("<II", 0, len(bloques)) + b"".join(t + struct.pack("<II", d, 0) for (t, _c, _z), d in zip(bloques, desp))
    cuerpo = b"".join(subs)
    return (b"OTVGfull" + struct.pack("<III", 1009, 2, 1) + b"ENDT" + struct.pack("<I", 0) + b"UNCO" + struct.pack("<I", 0) + ttoc
            + b"UNCO" + struct.pack("<II", len(cuerpo), 0) + cuerpo + struct.pack("<I", 1))


def escribir_archivo(ruta, dibujo):
    with open(ruta, "wb") as f:
        f.write(escribir(dibujo))


# ---------------------------------------------------------------- formas de ayuda (coordenadas del dibujo, y hacia arriba)
def rectangulo(x0, y0, x1, y1):
    """Contorno antihorario (el interior queda a la izquierda): (puntos, anclas)."""
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], None


def elipse(cx, cy, rx, ry):
    """Cuatro cubicas antihorarias (constante 0,5523); empieza y termina en (cx + rx, cy)."""
    k = 0.5522847498
    p = [(cx + rx, cy),
         (cx + rx, cy + k * ry), (cx + k * rx, cy + ry), (cx, cy + ry),
         (cx - k * rx, cy + ry), (cx - rx, cy + k * ry), (cx - rx, cy),
         (cx - rx, cy - k * ry), (cx - k * rx, cy - ry), (cx, cy - ry),
         (cx + k * rx, cy - ry), (cx + rx, cy - k * ry), (cx + rx, cy)]
    return p, [i % 3 == 0 for i in range(13)]


def forma(contorno, relleno=None, linea=None, grosor=3.0):
    """(capa_de_color, capa_de_linea) de una forma cerrada: relleno ("der" del contorno antihorario) y/o lapiz sobre el."""
    puntos, anclas = contorno
    color = [[{"puntos": puntos, "anclas": anclas, "der": relleno, "invisible": True}]] if relleno else []
    lin = [[{"puntos": puntos, "anclas": anclas, "lapiz": (linea, grosor)}]] if linea else []
    return color, lin


def demo():
    paleta = [{"id": 0x0D00000000000001, "rgba": (220, 40, 40, 255), "nombre": "rojo"},
              {"id": 0x0D00000000000002, "rgba": (20, 20, 20, 255), "nombre": "tinta"}]
    c, l = forma(rectangulo(-100, -100, 100, 100), relleno=paleta[0]["id"], linea=paleta[1]["id"])
    return {"paleta": paleta, "artes": {"colour": c, "line": l}}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    escribir_archivo(sys.argv[1], demo())
