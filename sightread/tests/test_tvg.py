"""Pruebas del lector .tvg de sala limpia. Los bytes se construyen aqui (no hay archivos .tvg reales).

    python -I -m unittest tests.test_tvg -v
"""
import re
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sightread.tvg import TvgIlegible, a_svg, decodificar
from sightread.tvg.registros import leer_registro

ROJO, NEGRO, AZUL = 0x0D00000000000001, 0x0D00000000000002, 0x0D00000000000003


# ---------------------------------------------------------------- constructores de bytes (D2 por omisión)
def reg(tag, cuerpo, d1=False, f=None):
    """Registro: D1 = etiqueta + u32 largo; D2 = etiqueta + F + largo (F mascara de bytes del largo u32)."""
    if d1:
        return tag + struct.pack("<I", len(cuerpo)) + cuerpo
    n = len(cuerpo)
    if f is None:
        f = 1 if n < 256 else 3 if n < 65536 else 7
    largo = struct.pack("<I", n)
    return tag + bytes([f]) + bytes(largo[i] for i in range(4) if f >> i & 1) + cuerpo


def tgbp(pts, anclas=None):
    n = len(pts)
    anclas = anclas or [True] * n
    masc = bytearray((n + 7) // 8)
    for i, a in enumerate(anclas):
        if a:
            masc[i >> 3] |= 1 << (i & 7)
    return struct.pack("<I", n) + bytes(masc) + b"".join(struct.pack("<ff", *p) for p in pts)


def tgco(cid, mat=(1, 0, 0, 1, 0, 0)):
    return b"\x01" + struct.pack("<6d", *mat) + struct.pack("<Q", cid) + b"\x00" + b"\xff" * 8


def ranura(d1, ref=0, color=None):
    if color is None:
        return b"\x00" + struct.pack("<I", ref)
    return b"\x01\xcd\x00" + reg(b"TGCO", tgco(*color), d1)


def tgsd(d1, lapiz=None, der=None, izq=None, invisible=False):
    """der/izq: ('ref', k) o (cid, matriz)."""
    b0 = (4 if lapiz else 0) | (2 if invisible else 0)
    cuerpo = bytes([b0])
    if lapiz:
        cuerpo += struct.pack("<fQ", lapiz[1], lapiz[0])
    for s in (der, izq):
        if s is None:
            cuerpo += ranura(d1)
        elif s[0] == "ref":
            cuerpo += ranura(d1, ref=s[1])
        else:
            cuerpo += ranura(d1, color=s)
    return cuerpo + b"\x00\x00"


def tgvs(d1, estilo, pts=None, anclas=None, ref=None, extra=b""):
    geo = b"\x01" + reg(b"TGBP", tgbp(pts, anclas), d1) if ref is None else b"\x00" + struct.pack("<I", ref)
    return reg(b"TGVS", reg(b"TGSD", estilo, d1) + geo + extra, d1)


def tgly(d1, trazos):
    return reg(b"TGLY", struct.pack("<HHH", 0, len(trazos), 0) + b"".join(trazos), d1)


def arte(d1, capas, cola=b"\x00"):
    out = b"\x00\x01" + struct.pack("<I", len(capas))
    for c in capas:
        out += struct.pack("<I", 2) + c
    return out + cola + reg(b"TGRV", b"\x00" * 8, d1)


def arte_vacio(d1):
    return b"\x00\x00\x00" + reg(b"TGRV", b"\x00" * 8, d1)


def tpal(d1, colores):
    """colores: [(id, (r,g,b,a), nombre)]"""
    out = struct.pack("<I", len(colores))
    for cid, rgba, nombre in colores:
        n = nombre.encode("utf-16-le")
        out += b"\x79\x00\x00\x00\x00\x00" + reg(b"TCSC", bytes(rgba), d1)
        out += reg(b"TCID", struct.pack("<I", len(nombre)) + n + struct.pack("<Q", cid) + struct.pack("<I", 4) + "paleta"[:4].encode("utf-16-le"), d1)
    return out


def subbloque(tag, carga, d1, comprimir):
    if comprimir:
        z = zlib.compress(carga, 6)
        if d1:
            return tag + b"ZLIB" + struct.pack("<II", len(z) + 4, len(carga)) + z
        return tag + b"ZLIB" + struct.pack("<IIII", len(z) + 8, 0, len(carga), 0) + z
    if d1:
        return tag + b"UNCO" + struct.pack("<I", len(carga)) + carga
    return tag + b"UNCO" + struct.pack("<II", len(carga), 0) + carga


def archivo(arts, paleta, d1=False, tags=(b"tUAA", b"tCAA", b"tLAA", b"tOAA"), comprimir=False):
    """arts: 4 cargas de arte (underlay, colour, line, overlay)."""
    cuerpo = [(b"TVCI", b"\x00" * 20), (b"CREA", struct.pack("<I", 2)), (b"AUIF", struct.pack("<I", 1))]
    cuerpo += list(zip(tags, arts)) + [(b"TPAL", paleta)]
    subs = b"".join(subbloque(t, c, d1, comprimir and t not in (b"TVCI", b"CREA", b"AUIF")) for t, c in cuerpo)
    cert = b"CERT" + struct.pack("<III", 8 + 16, 1, 16) + b"x" * 16
    out = b"OTVGfull" + struct.pack("<III", 1009, 2, 1) + cert + b"ENDT" + struct.pack("<I", 0)
    if d1:
        out += b"UNCO" + struct.pack("<I", len(subs)) + subs + b"TTOC" + struct.pack("<I", 8) + b"\x00" * 64 + struct.pack("<II", 8, 1)
    else:
        out += b"UNCO" + struct.pack("<I", 0) + b"TTOC" + struct.pack("<II", 0, 8) + b"\x00" * 96
        out += b"UNCO" + struct.pack("<II", len(subs), 0) + subs + struct.pack("<I", 1)
    return out + b"SIGN" + b"\x00" * 79


def cuadrado(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


PAL = tpal(False, [(ROJO, (255, 0, 0, 255), "rojo"), (NEGRO, (0, 0, 0, 128), "negro"), (AZUL, (0, 0, 255, 255), "Piñón")])


def d1_pal():
    return tpal(True, [(ROJO, (255, 0, 0, 255), "rojo"), (NEGRO, (0, 0, 0, 128), "negro")])


# ---------------------------------------------------------------- pruebas
class TestRegistros(unittest.TestCase):
    def test_formas_de_largo(self):
        for f, n in ((1, 7), (2, 512), (3, 700), (7, 70000), (15, 70000), (13, 0x10000 * 0 + 65536 * 3)):
            b = reg(b"TEST", bytes(n), f=f)
            etq, i, fin = leer_registro(b, 0)
            self.assertEqual((etq, fin - i), (b"TEST", n), f)

    def test_forma_con_bytes_ausentes(self):
        # F=9: bytes 0 y 3 del largo (byte 1 y 2 = 0); el cuerpo declarado (16 MB) se sale del bloque
        with self.assertRaises(TvgIlegible):
            leer_registro(b"TEST" + bytes([9]) + b"\x10\x01", 0)

    def test_d1(self):
        b = reg(b"TEST", b"abc", d1=True)
        self.assertEqual(leer_registro(b, 0, True), (b"TEST", 8, 11))

    def test_forma_invalida(self):
        with self.assertRaises(TvgIlegible):
            leer_registro(b"TEST\x00\x01abc", 0)
        with self.assertRaises(TvgIlegible):
            leer_registro(b"TEST\x10\x01abc", 0)

    def test_registro_truncado(self):
        with self.assertRaises(TvgIlegible):
            leer_registro(b"TEST\x01\x09abc", 0)


class TestContenedor(unittest.TestCase):
    def vacio(self, d1=False, **kw):
        v = arte_vacio(d1)
        return archivo([v] * 4, tpal(d1, []), d1=d1, **kw)

    def test_d2_y_d1(self):
        self.assertEqual(decodificar(self.vacio())["disp"], "D2")
        self.assertEqual(decodificar(self.vacio(d1=True))["disp"], "D1")

    def test_comprimido(self):
        m = decodificar(self.vacio(comprimir=True))
        self.assertEqual(m["artes"]["line"]["capas"], [])
        m = decodificar(self.vacio(d1=True, comprimir=True))
        self.assertEqual(m["disp"], "D1")

    def test_firma_y_version(self):
        b = bytearray(self.vacio())
        b[:8] = b"NOTAVGFU"
        with self.assertRaises(TvgIlegible):
            decodificar(bytes(b))
        b = bytearray(self.vacio())
        b[8:12] = struct.pack("<I", 1010)
        with self.assertRaises(TvgIlegible):
            decodificar(bytes(b))
        with self.assertRaises(TvgIlegible):
            decodificar(b"")

    def test_flujo_zlib_corrupto(self):
        b = bytearray(self.vacio(comprimir=True))
        i = b.find(b"ZLIB")
        b[i + 30] ^= 0xFF
        b[i + 31] ^= 0xFF
        with self.assertRaises(TvgIlegible):
            decodificar(bytes(b))

    def test_etiquetas_en_mayuscula(self):
        m = decodificar(archivo([arte_vacio(False)] * 4, tpal(False, []), tags=(b"TUAA", b"TCAA", b"TLAA", b"TOAA")))
        self.assertEqual(list(m["artes"]), ["underlay", "colour", "line", "overlay"])


class TestDibujo(unittest.TestCase):
    def linea(self, d1=False, grosor=3.0, extra=b""):
        t = tgvs(d1, tgsd(d1, lapiz=(ROJO, grosor)), [(0, 0), (100, 0)], extra=extra)
        a = arte(d1, [tgly(d1, [t])])
        v = arte_vacio(d1)
        return archivo([v, v, a, v], PAL if not d1 else d1_pal(), d1=d1)

    def test_perfil_variable_es_poligono_relleno(self):
        def tgtb(ts, anchos):
            llaves = b"".join(struct.pack("<11f", t, w, 0, 0.33, 0, 0.33, w, 0, 0.33, 0, 0.33) for t, w in zip(ts, anchos))
            return reg(b"tGTB", b"\x01\xff\xff\xff\xff\xcf\x00" + struct.pack("<I", len(ts)) + llaves + b"\x00" * 29)
        # recta de (0,0) a (100,0) con semiancho 1 -> 3: el contorno del oraculo (E5_var2)
        s = a_svg(decodificar(self.linea(grosor=0.0, extra=tgtb((0.0, 1.0), (1.0, 3.0)))))
        self.assertIn('d="M 0 1 L 100 3 L 101.148 2.772 L 102.121 2.121 L 102.772 1.148 L 103 0 L 102.772 -1.148 L 102.121 -2.121 '
                      'L 101.148 -2.772 L 100 -3 L 0 -1 L -0.383 -0.924 L -0.707 -0.707 L -0.924 -0.383 L -1 0 L -0.924 0.383 '
                      'L -0.707 0.707 L -0.383 0.924 Z" fill="#ff0000" stroke="none"', s)
        self.assertNotIn("fill-rule", s)
        # tres llaves aunque el grosor sea constante: tambien poligono (CENSO-21)
        s = a_svg(decodificar(self.linea(grosor=0.0, extra=tgtb((0.0, 0.5, 1.0), (2.0, 2.0, 2.0)))))
        self.assertIn('stroke="none"', s)
        self.assertNotIn("stroke-width", s)

    def test_lapiz(self):
        m = decodificar(self.linea())
        t = m["artes"]["line"]["capas"][0]["trazos"][0]
        self.assertEqual(t["puntos"], [(0.0, 0.0), (100.0, 0.0)])
        self.assertEqual(t["estilo"]["lapiz"], "%016x" % ROJO)
        self.assertFalse(t["cerrado"])
        self.assertEqual(m["paleta"]["%016x" % NEGRO]["rgba"], (0, 0, 0, 128))
        self.assertEqual(m["paleta"]["%016x" % AZUL]["nombre"], "Piñón")
        s = a_svg(m)
        self.assertIn('<g transform="matrix(1 0 0 -1 0 0)"><g id="line">', s)
        self.assertIn('d="M 0 0 L 100 0"', s)
        self.assertIn('stroke="#ff0000" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"', s)
        self.assertNotIn("underlay", s)

    def test_lapiz_d1(self):
        s = a_svg(decodificar(self.linea(d1=True)))
        self.assertIn('stroke="#ff0000" stroke-width="6"', s)

    def test_perfil_constante_y_alternativo(self):
        llaves = struct.pack("<I", 2) + b"".join(struct.pack("<11f", t, 2.0, 0, 0.33, 0, 0.33, 2.0, 0, 0.33, 0, 0.33) for t in (0.0, 1.0))
        tgtb = b"\x01\xff\xff\xff\xff\xcf\x00" + llaves + b"\x00" * 29
        self.assertEqual(len(tgtb), 128)
        m = decodificar(self.linea(grosor=0.0, extra=reg(b"tGTB", tgtb)))
        t = m["artes"]["line"]["capas"][0]["trazos"][0]
        self.assertEqual(len(t["perfil"]), 2)
        self.assertIn('stroke-width="4"', a_svg(m))     # izq + der de la llave
        m = decodificar(self.linea(grosor=3.0, extra=reg(b"tGTB", b"\x00" * 29)))
        self.assertIsNone(m["artes"]["line"]["capas"][0]["trazos"][0]["perfil"])
        self.assertIn('stroke-width="6"', a_svg(m))     # forma alternativa: 2 x f32 de TGSD

    def test_color_con_alfa_y_defecto(self):
        t1 = tgvs(False, tgsd(False, lapiz=(NEGRO, 1.0)), [(0, 0), (10, 0)])
        t2 = tgvs(False, tgsd(False, lapiz=(3, 1.0)), [(0, 5), (10, 5)])
        a = arte(False, [tgly(False, [t1, t2])])
        s = a_svg(decodificar(archivo([arte_vacio(False), arte_vacio(False), a, arte_vacio(False)], PAL)))
        self.assertIn('stroke="#000000" stroke-opacity="0.502"', s)
        self.assertIn('stroke="#000000" stroke-width="2"', s)     # id ...03: negro opaco

    def test_invisible_no_dibuja_lapiz(self):
        t = tgvs(False, tgsd(False, lapiz=(ROJO, 1.0), invisible=True), [(0, 0), (10, 0)])
        s = a_svg(decodificar(archivo([arte_vacio(False)] * 2 + [arte(False, [tgly(False, [t])]), arte_vacio(False)], PAL)))
        self.assertNotIn("<path", s)

    def test_relleno_con_tgco_y_referencias(self):
        # un cuadrado cerrado con relleno a la izquierda (TGCO inline: id de objeto 1; el trazo toma el 2), otro trazo por referencia con lapiz
        mat = (4.0, 0, 0, 4.0, -10.0, 5.0)
        cuad = cuadrado(0, 0, 100, 100)
        t1 = tgvs(False, tgsd(False, der=(ROJO, mat)), cuad)
        t2 = tgvs(False, tgsd(False, lapiz=(NEGRO, 2.0)), ref=2)
        t3 = tgvs(False, tgsd(False, der=("ref", 1)), cuadrado(200, 0, 300, 100))
        a = arte(False, [tgly(False, [t1, t2, t3])])
        m = decodificar(archivo([arte_vacio(False), a, arte_vacio(False), arte_vacio(False)], PAL))
        trazos = m["artes"]["colour"]["capas"][0]["trazos"]
        self.assertTrue(trazos[0]["cerrado"])
        self.assertEqual(trazos[0]["estilo"]["der"], "%016x" % ROJO)
        self.assertEqual(trazos[1]["ref"], 2)
        self.assertEqual(trazos[1]["puntos"], trazos[0]["puntos"])
        self.assertEqual(trazos[2]["estilo"]["der"], "%016x" % ROJO)
        self.assertEqual(m["tgco"], {"%016x" % ROJO: [mat]})
        s = a_svg(m)
        self.assertEqual(s.count('fill="#ff0000" fill-rule="nonzero"'), 1)     # un path por color y capa, con dos bucles
        self.assertEqual(s.count(" Z"), 3)     # dos bucles de relleno + el lapiz cerrado
        self.assertIn("M 0 0 L 100 0 L 100 100 L 0 100 L 0 0 Z", s)
        self.assertIn('stroke="#000000" stroke-opacity="0.502" stroke-width="4"', s)

    def test_referencia_sin_resolver(self):
        t = tgvs(False, tgsd(False, lapiz=(ROJO, 1.0)), ref=9)
        a = arte(False, [tgly(False, [t])])
        with self.assertRaises(TvgIlegible):
            decodificar(archivo([a] + [arte_vacio(False)] * 3, PAL))

    def test_curva_cubica_y_region_con_agujero(self):
        pts = [(0, 0), (0, 10), (10, 10), (10, 0)]
        t = tgvs(False, tgsd(False, lapiz=(ROJO, 1.0)), pts, anclas=[True, False, False, True])
        s = a_svg(decodificar(archivo([arte_vacio(False)] * 2 + [arte(False, [tgly(False, [t])]), arte_vacio(False)], PAL)))
        self.assertIn("M 0 0 C 0 10 10 10 10 0", s)
        # exterior con relleno a la izquierda (antihorario) e interior con relleno a la izquierda (horario): dos bucles en un solo path
        ext = tgvs(False, tgsd(False, der=(ROJO, (1, 0, 0, 1, 0, 0))), cuadrado(0, 0, 100, 100))
        hueco = tgvs(False, tgsd(False, der=("ref", 1)), cuadrado(20, 20, 20 + 0.0, 20)[:1] + [(20, 80), (80, 80), (80, 20), (20, 20)])
        s = a_svg(decodificar(archivo([arte_vacio(False), arte(False, [tgly(False, [ext, hueco])]), arte_vacio(False), arte_vacio(False)], PAL)))
        self.assertEqual(s.count("<path"), 1)
        self.assertEqual(s.count("Z"), 2)

    def test_degradado_y_textura_no_se_dibujan(self):
        pal = struct.pack("<I", 2)
        pal += b"\x79\x00\x01\x00\x00\x00" + reg(b"TCGC", b"\x00" * 28) + reg(b"TCID", struct.pack("<I", 1) + "g".encode("utf-16-le") + struct.pack("<Q", ROJO) + struct.pack("<I", 0))
        pal += b"\x7c\x00" + reg(b"TCTC", b"\x00" * 300) + reg(b"TCID", struct.pack("<I", 1) + "t".encode("utf-16-le") + struct.pack("<Q", NEGRO) + struct.pack("<I", 0))
        t = tgvs(False, tgsd(False, der=(ROJO, (1, 0, 0, 1, 0, 0)), izq=(NEGRO, (1, 0, 0, 1, 0, 0))), cuadrado(0, 0, 10, 10))
        m = decodificar(archivo([arte_vacio(False), arte(False, [tgly(False, [t])]), arte_vacio(False), arte_vacio(False)], pal))
        self.assertEqual(m["paleta"]["%016x" % ROJO]["tipo"], "degradado")
        self.assertEqual(m["paleta"]["%016x" % NEGRO]["tipo"], "textura")
        self.assertIsNone(m["paleta"]["%016x" % NEGRO]["rgba"])
        self.assertNotIn("<path", a_svg(m))
        m["paleta"]["%016x" % ROJO]["rgba"] = (1, 2, 3, 255)      # como hace la integracion con los degradados
        self.assertIn('fill="#010203"', a_svg(m))

    def test_capas_agrupadas_en_tgnd_y_texto(self):
        d1 = False
        capa = struct.pack("<I", 2) + tgly(d1, [tgvs(d1, tgsd(d1, lapiz=(ROJO, 1.0)), [(0, 0), (5, 5)])])
        interno = reg(b"TGND", struct.pack("<I", 1) + capa)
        grupo = struct.pack("<I", 1) + reg(b"TGND", struct.pack("<I", 1) + struct.pack("<I", 1) + interno)
        a = b"\x00\x01" + struct.pack("<I", 1) + grupo + b"\x00" + reg(b"TGRV", bytes(8))
        m = decodificar(archivo([arte_vacio(d1)] * 2 + [a, arte_vacio(d1)], PAL))
        self.assertEqual(len(m["artes"]["line"]["capas"]), 1)
        # TGND de texto (primer elemento con prefijo 3): se omite con aviso
        texto = struct.pack("<I", 1) + reg(b"TGND", struct.pack("<I", 1) + struct.pack("<I", 3) + b"\x01TGTL" + bytes(20))
        a = b"\x00\x01" + struct.pack("<I", 1) + texto + b"\x00" + reg(b"TGRV", bytes(8))
        m = decodificar(archivo([arte_vacio(d1)] * 2 + [a, arte_vacio(d1)], PAL))
        self.assertEqual(m["artes"]["line"]["capas"], [])
        self.assertIn("capa de texto (TGND) omitida", m["avisos"])

    def test_forma_no_soportada_es_ilegible(self):
        a = arte(False, [tgly(False, [tgvs(False, tgsd(False, lapiz=(ROJO, 1.0)), [(0, 0), (1, 1)])])])
        b = a.replace(b"TGLY\x01", b"TGLY\x00")
        with self.assertRaises(TvgIlegible):
            decodificar(archivo([b] + [arte_vacio(False)] * 3, PAL))

    def test_svg_cumple_el_contrato(self):
        s = a_svg(decodificar(TestDibujo.linea(self)))
        self.assertTrue(s.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-1875 -1875 3750 3750">'))
        self.assertEqual(set(re.findall(r"<(\w+)", s)), {"svg", "g", "path"})
        self.assertEqual(set(re.findall(r"[A-Za-z]", re.search(r' d="([^"]*)"', s).group(1))), {"M", "L"})


if __name__ == "__main__":
    unittest.main()
