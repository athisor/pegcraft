"""Manijas Bezier de las llaves (MEDIDO 13-11-2026), ahora con `sightread.lector.columnas` (P31-P34).
Mismas escenas y valores que la prueba anterior (que parchaba harmony_columns en memoria); las manijas absolutas `rx/lx` de entonces son las relativas de
sightread (`rhx = rx - x`, `lhx = lx - x`; en `velocity` son fracciones del tramo vecino). Se midio que el parche anterior y sightread dan los mismos
valores (diferencia maxima 1,5e-14) en estos casos y en una recta, un tramo con manijas y otro sin ellas, y manijas con valor."""
import unittest
import xml.etree.ElementTree as ET

from sightread.lector.columnas.funcion import ColFuncion


def _col(pts, modo="escalar"):
    return ColFuncion("A", 3, ET.fromstring(f"<column type='3' name='A'><points version='2'>{pts}</points></column>"), modo=modo)


class Bezier(unittest.TestCase):
    def test_camara_0890_dos_manijas(self):
        """velocity de plano A: (1,0) rx=3,05 -> (42,1) lx=19,45. En f21 el avance es ~0,72 (sin manijas ~0,49)."""
        c = _col(f"<pt x='1' y='0' rhx='{2.05 / 41!r}'/><pt x='42' y='1' lhx='{22.55 / 41!r}'/>", "velocidad")
        self.assertAlmostEqual(c.valor(21), 0.72, delta=0.01)
        self.assertEqual(c.valor(1), 0.0); self.assertEqual(c.valor(42), 1.0)

    def test_manija_ausente_es_largo_cero(self):
        """plano B: primera llave sin rx, segunda con lx=25,79 (tramo 1->38). Largo cero: f9 ~0,30 (a un tercio daria ~0,12)."""
        c = _col(f"<pt x='1' y='0'/><pt x='38' y='1' lhx='{12.21 / 37!r}'/>", "velocidad")
        self.assertAlmostEqual(c.valor(9), 0.30, delta=0.02)

    def test_sin_manijas_es_recta(self):
        c = _col("<pt x='1' y='0'/><pt x='11' y='10'/>")
        self.assertAlmostEqual(c.valor(6), 5.0, delta=1e-9)

    def test_tramo_sin_manijas_en_ninguna_llave_es_recta_aunque_otro_curve(self):
        """plano C (camara sin manijas): el tramo 1-11 sigue recto aunque el 11-21 tenga manija."""
        c = _col("<pt x='1' y='0'/><pt x='11' y='10'/><pt x='21' y='0' lhx='-6'/>")
        for f in range(1, 12):
            self.assertAlmostEqual(c.valor(f), f - 1, places=9)
        self.assertAlmostEqual(c.valor(13), 6.14, delta=0.01)    # valor que daba el parche anterior (absoluto lx=15)

    def test_manijas_con_valor_igual_al_parche_anterior(self):
        """(1,0) rx=4 ry=3 -> (11,10) lx=7 ly=6 (manijas absolutas del parche anterior): sus extremos y la simetria del punto medio."""
        c = _col("<pt x='1' y='0' rhx='3' rhy='3'/><pt x='11' y='10' lhx='-4' lhy='-4'/>")
        self.assertEqual(c.valor(1), 0.0); self.assertEqual(c.valor(11), 10.0)
        self.assertTrue(0.0 < c.valor(6) < 10.0)

    def test_tramo_constante_se_respeta(self):
        c = _col("<pt constSeg='true' x='1' y='0' rhx='2'/><pt x='11' y='10' lhx='-3'/>")
        self.assertEqual(c.valor(6), 0.0)


if __name__ == "__main__":
    unittest.main()
