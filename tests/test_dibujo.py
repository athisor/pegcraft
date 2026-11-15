"""Modelo de dibujo v1 (pegcraft.dibujo): .tvg sintetico -> dibujo (JSON) -> SVG con datos del trazo -> dibujo, igual.
Solo datos sinteticos (sightread.sintetico.tvg_minimo y modelos armados a mano).
python -m unittest discover -s tests -p test_dibujo.py"""
import os, struct, sys, unittest
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pegcraft import dibujo as D
from pegcraft.dibujo import verificar as V
from sightread.sintetico import tvg_minimo as T
from sightread.tvg import a_svg as resolver, decodificar

ROJO, TINTA = "0d00000000000001", "0d00000000000002"


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def trazo(puntos, anclas=None, perfil=None, ref=None, **estilo):
    e = {"der": None, "izq": None, "lapiz": None, "ancho": 0.0, "invisible": False}
    e.update(estilo)
    return {"puntos": puntos, "anclas": anclas or [True] * len(puntos), "cerrado": len(puntos) > 1 and puntos[0] == puntos[-1],
            "perfil": perfil, "ref": ref, "estilo": e}


def modelo(trazos, arte="line", paleta=None, avisos=()):
    paleta = paleta or {TINTA: {"nombre": "tinta", "rgba": (20, 20, 20, 255), "paleta": "P", "tipo": "solido"}}
    return {"disp": "D2", "paleta": paleta, "artes": {arte: {"capas": [{"trazos": trazos}]}}, "tgco": {}, "avisos": list(avisos)}


def vuelta(d):
    return D.desde_svg(D.a_svg(d))


class TestDesdeTvg(unittest.TestCase):
    def setUp(self):
        self.datos = T.escribir(T.demo())          # cuadrado rojo (relleno) con borde de tinta
        self.d = D.desde_tvg(self.datos, "demo.tvg")

    def test_bien_formado_y_cuatro_artes(self):
        self.assertEqual(D.validar(self.d), [])
        self.assertEqual([a["name"] for a in self.d["arts"]], list(D.ARTS))
        self.assertEqual(self.d["state"], "derived")
        self.assertEqual(self.d["source"]["kind"], "tvg")
        self.assertEqual(len(self.d["source"]["sha256"]), 64)

    def test_relleno_a_la_izquierda_de_un_contorno_antihorario(self):
        (s,) = self.d["arts"][1]["layers"][0]["strokes"]       # colour
        self.assertEqual(s["fill_left"], ROJO)
        self.assertNotIn("fill_right", s)
        self.assertTrue(s["invisible"])
        self.assertTrue(s["closed"])
        self.assertNotIn("line", s)

    def test_linea_con_color_y_semiancho(self):
        (s,) = self.d["arts"][2]["layers"][0]["strokes"]       # line
        self.assertEqual((s["line"], s["width"]), (TINTA, 3.0))
        self.assertEqual(s["id"], "a2-c0-t0")

    def test_ida_y_vuelta_por_svg_y_por_el_modelo_del_lector(self):
        self.assertEqual(D.canonico(vuelta(self.d)), D.canonico(self.d))
        self.assertEqual(D.canonico(D.nucleo(D.desde_lector(D.a_modelo_lector(self.d)))), D.canonico(D.nucleo(self.d)))
        self.assertEqual(V.uno(self.datos)[0], [])

    def test_la_apariencia_resuelta_es_la_del_lector(self):
        viejo = resolver(decodificar(self.datos))
        self.assertEqual(resolver(D.a_modelo_lector(self.d)), viejo)
        nuevo = D.a_svg(self.d)
        self.assertIn(viejo[viejo.index(">") + 1:-len("</svg>")], nuevo)       # va tal cual dentro del SVG nuevo
        self.assertIn('fill="none" stroke="none"', nuevo)                      # los trazos de datos no se pintan

    def test_curvas(self):
        c, l = T.forma(T.elipse(0, 0, 50, 30), relleno=int(ROJO, 16), linea=int(TINTA, 16))
        pal = T.demo()["paleta"]
        d = D.desde_tvg(T.escribir({"paleta": pal, "artes": {"colour": c, "line": l}}))
        self.assertIn(" C ", D.a_svg(d))
        self.assertEqual(D.canonico(vuelta(d)), D.canonico(d))


class TestModeloAMano(unittest.TestCase):
    def test_perfil_y_puntos_compartidos(self):
        pts = [(f32(0.1), 0.0), (10.0, f32(5.3)), (20.0, 0.0)]
        perfil = [(0.0, (1.5, 1.0, 2.0, 3.0, 4.0), (2.5, 5.0, 6.0, 7.0, 8.0)), (1.0, (0.5, 0.0, 0.0, 0.0, 0.0), (0.25, 0.0, 0.0, 0.0, 0.0))]
        a = trazo(pts, perfil=perfil, lapiz=TINTA, ancho=1.5)
        b = trazo(a["puntos"], a["anclas"], ref=1, izq=TINTA, invisible=True)      # misma lista: comparte los puntos
        d = D.desde_lector(modelo([a, b]))
        s1, s2 = d["arts"][2]["layers"][0]["strokes"]
        self.assertEqual(s1["profile"]["knots"], [[0.0, 1.5, 2.5], [1.0, 0.5, 0.25]])
        self.assertEqual(s1["profile"]["raw"][0], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
        self.assertEqual(s2, {"id": "a2-c0-t1", "geometry_of": "a2-c0-t0", "closed": False, "fill_right": TINTA, "invisible": True})
        self.assertEqual(D.validar(d), [])
        texto = D.a_svg(d)
        self.assertIn('lotte:precision="f32"', texto)
        self.assertIn('lotte:geometry-of="a2-c0-t0"', texto)
        self.assertEqual(D.canonico(D.desde_svg(texto)), D.canonico(d))
        m2 = D.a_modelo_lector(d)
        t1, t2 = m2["artes"]["line"]["capas"][0]["trazos"]
        self.assertIs(t1["puntos"], t2["puntos"])
        self.assertEqual(t1["perfil"], perfil)

    def test_numeros_que_no_son_f32_van_exactos_en_f64(self):
        d = D.desde_lector(modelo([trazo([(0.1, 0.2), (1 / 3, 2 / 3)], lapiz=TINTA, ancho=0.7)]))
        texto = D.a_svg(d)
        self.assertIn('lotte:precision="f64"', texto)
        self.assertEqual(D.canonico(D.desde_svg(texto)), D.canonico(d))

    def test_puntos_fuera_de_patron(self):
        casos = [([(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (4.0, 4.0)], [True, False, False, False, True]),     # tres tiradores seguidos
                 ([(0.0, 0.0), (1.0, 1.0)], [False, True]),                                                           # empieza en tirador
                 ([(5.0, 5.0)], [True]), ([], [])]
        for pts, anc in casos:
            d = D.desde_lector(modelo([trazo(pts, anc, lapiz=TINTA, ancho=1.0)]))
            self.assertEqual(D.canonico(vuelta(d)), D.canonico(d), (pts, anc))
        d = D.desde_lector(modelo([trazo(*casos[0], lapiz=TINTA, ancho=1.0)]))
        self.assertIn("lotte:points=", D.a_svg(d))
        d = D.desde_lector(modelo([trazo([(0.0, 0.0), (1.0, 2.0), (3.0, 0.0)], [True, False, True])]))        # un tirador: Q
        self.assertIn(" Q ", D.a_svg(d))
        self.assertEqual(D.canonico(vuelta(d)), D.canonico(d))

    def test_nombres_con_caracteres_de_xml_y_opacos(self):
        pal = {TINTA: {"nombre": 'a "b" <c> & d', "rgba": (1, 2, 3, 4), "paleta": "P&Q", "tipo": "solido"},
               ROJO: {"nombre": "tex", "rgba": None, "paleta": "P", "tipo": "textura"}}
        m = modelo([trazo([(0.0, 0.0), (1.0, 0.0)], der=ROJO)], arte="colour", paleta=pal, avisos=["capa de texto (TGND) omitida", "tGTB con forma alternativa (99 B)"])
        m["tgco"] = {ROJO: [(1.0, 0.0, 0.0, 1.0, 0.5, 0.25)], TINTA: [(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)]}
        d = D.desde_lector(m, bloques=["TLAB"])
        self.assertEqual(d["opaque"], ["block:TLAB", "profile-undecoded", "text", "texture-fill"])
        self.assertEqual(list(d["gradients"]), [ROJO])            # la matriz de un color solido no dice nada: no se guarda
        self.assertEqual(D.canonico(vuelta(d)), D.canonico(d))

    def test_validar(self):
        base = D.desde_lector(modelo([trazo([(0.0, 0.0), (1.0, 0.0)], lapiz=TINTA, ancho=1.0), trazo([(0.0, 0.0), (2.0, 0.0)])]))
        self.assertEqual(D.validar(base), [])
        import copy
        d = copy.deepcopy(base); d["arts"][2]["layers"][0]["strokes"][1]["id"] = "a2-c0-t0"
        self.assertTrue(any("repetido" in e for e in D.validar(d)))
        d = copy.deepcopy(base); s = d["arts"][2]["layers"][0]["strokes"][1]; del s["points"]; s["geometry_of"] = "no-existe"
        self.assertTrue(any("geometry_of" in e for e in D.validar(d)))
        d = copy.deepcopy(base); d["arts"] = d["arts"][:3]
        self.assertTrue(D.validar(d))
        d = copy.deepcopy(base); d["arts"][2]["layers"][0]["strokes"][0]["closed"] = True
        self.assertTrue(any("closed" in e for e in D.validar(d)))
        d = copy.deepcopy(base); del d["arts"][2]["layers"][0]["strokes"][0]["width"]
        self.assertTrue(any("width" in e for e in D.validar(d)))

    def test_svg_sin_datos_del_modelo_se_rechaza(self):
        with self.assertRaises(ValueError):
            D.desde_svg('<svg xmlns="http://www.w3.org/2000/svg"><path d="M 0 0 L 1 1"/></svg>')


if __name__ == "__main__":
    unittest.main()
