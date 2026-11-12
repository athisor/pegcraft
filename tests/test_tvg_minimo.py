"""Pruebas de ida del escritor minimo de .tvg sinteticos: escribir -> decodificar -> mismos trazos.

    python -I -m unittest discover -s tests -p "test_tvg_minimo.py"
"""
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tools" / "sintetico"))
import tvg_minimo as w
from pegcraft.tvg import a_svg, decodificar

ROJO, VERDE, TINTA = 0x0D00000000000001, 0x0D00000000000002, 0x0D00000000000003 + 1


def hexa(i):
    return "%016x" % i


PAL = [{"id": ROJO, "rgba": (220, 40, 40, 255), "nombre": "rojo"}, {"id": VERDE, "rgba": (0, 160, 60, 128), "nombre": "verde"},
       {"id": TINTA, "rgba": (10, 10, 10, 255), "nombre": "tinta", "paleta": "Ñandú"}]


class TestEscritor(unittest.TestCase):
    def dibujo(self):
        c1, l1 = w.forma(w.rectangulo(-100, -50, 100, 50), relleno=ROJO, linea=TINTA, grosor=3)
        c2, l2 = w.forma(w.elipse(300, 0, 80, 40), relleno=ROJO, linea=TINTA, grosor=1.5)
        c3, _ = w.forma(w.rectangulo(0, 200, 50, 250), relleno=VERDE)
        return {"paleta": PAL, "artes": {"colour": c1 + c2 + c3, "line": l1 + l2}}

    def test_ida(self):
        d = self.dibujo()
        m = decodificar(w.escribir(d))
        self.assertEqual(m["disp"], "D2")
        self.assertEqual(m["avisos"], [])
        self.assertEqual(list(m["artes"]), ["underlay", "colour", "line", "overlay"])
        self.assertEqual(m["artes"]["underlay"]["capas"], [])
        for arte in ("colour", "line"):
            esp = [t for capa in d["artes"][arte] for t in capa]
            got = [t for capa in m["artes"][arte]["capas"] for t in capa["trazos"]]
            self.assertEqual(len(got), len(esp))
            for g, e in zip(got, esp):
                self.assertEqual(len(g["puntos"]), len(e["puntos"]))
                for (gx, gy), (ex, ey) in zip(g["puntos"], e["puntos"]):     # f32
                    self.assertAlmostEqual(gx, ex, places=3)
                    self.assertAlmostEqual(gy, ey, places=3)
                self.assertEqual(g["anclas"], e["anclas"] or [True] * len(e["puntos"]))
                self.assertEqual(g["estilo"]["der"], hexa(e["der"]) if e.get("der") else None)
                self.assertIsNone(g["estilo"]["izq"])
                self.assertEqual(g["estilo"]["lapiz"], hexa(e["lapiz"][0]) if e.get("lapiz") else None)
                self.assertEqual(g["estilo"]["invisible"], bool(e.get("invisible")))
                if e.get("lapiz"):
                    self.assertAlmostEqual(g["estilo"]["ancho"], e["lapiz"][1])
        self.assertTrue(all(t["cerrado"] for c in m["artes"]["colour"]["capas"] for t in c["trazos"]))
        self.assertEqual(m["paleta"][hexa(VERDE)]["rgba"], (0, 160, 60, 128))
        self.assertEqual(m["paleta"][hexa(TINTA)]["paleta"], "Ñandú")
        self.assertEqual(sorted(m["tgco"]), sorted([hexa(ROJO), hexa(VERDE)]))

    def test_svg(self):
        s = a_svg(decodificar(w.escribir(self.dibujo())))
        self.assertIn('<g id="colour">', s)
        self.assertIn('<g id="line">', s)
        self.assertIn('fill="#dc2828" fill-rule="nonzero"', s)
        self.assertIn('fill="#00a03c" fill-rule="nonzero" fill-opacity="0.502"', s)
        self.assertIn('stroke="#0a0a0a" stroke-width="6"', s)
        self.assertIn("C ", s)          # la elipse lleva cubicas

    def test_determinista_y_sin_firma(self):
        a, b = w.escribir(self.dibujo()), w.escribir(self.dibujo())
        self.assertEqual(a, b)
        self.assertNotIn(b"CERT", a)
        self.assertNotIn(b"SIGN", a)

    def test_arte_grande_usa_f_de_varios_bytes(self):
        pts = [(i * 0.5, (i % 7) * 3.0) for i in range(12000)]       # > 64 KB
        d = {"paleta": PAL, "artes": {"line": [[{"puntos": pts, "lapiz": (TINTA, 1)}]]}}
        m = decodificar(w.escribir(d))
        self.assertEqual(len(m["artes"]["line"]["capas"][0]["trazos"][0]["puntos"]), 12000)

    def test_demo(self):
        self.assertIn("<path", a_svg(decodificar(w.escribir(w.demo()))))


if __name__ == "__main__":
    unittest.main()
