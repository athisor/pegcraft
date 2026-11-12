"""Pruebas de reglas y de robustez de las columnas con escenas mínimas escritas aquí (nombres inventados). Sin Harmony.
Valores esperados: derivados de las reglas medidas (P30 exposición, P31-P35 Bézier, P34 trayectoria) o, en las guardas, de convenciones de compatibilidad (A3-01).
Correr desde la raíz del repo:  python -I -m unittest discover -s tests\\lector\\columnas -v
"""
import math
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from sightread.lector.columnas import (ColExposicion, ColFuncion, ColOpaca, ColTrayectoria3D, leer_columnas)  # noqa: E402
from sightread.lector.columnas import exposicion as E  # noqa: E402


def escena(*columnas, extra=""):
    return ET.fromstring(f"<scene name='Top'><columns>{''.join(columnas)}</columns>{extra}</scene>")


def bez(nombre, *pts):
    return f"<column type='3' name='{nombre}'><points version='2'>{''.join(pts)}</points></column>"


def tray(nombre, puntos, velocity="", attrs=""):
    return f"<column type='2' name='{nombre}'><path3D {attrs}><points>{puntos}</points></path3D>{velocity}</column>"


def vel(*pts):
    return f"<velocity type='3' name='v' anonymous='true'><points version='2'>{''.join(pts)}</points></velocity>"


class TestFuncion(unittest.TestCase):
    def test_lineal_sin_manijas(self):
        c = leer_columnas(escena(bez("A", "<pt x='1' y='0'/>", "<pt x='11' y='10'/>")))["A"]
        self.assertIsInstance(c, ColFuncion)
        for f in (1, 3.5, 6, 11):
            self.assertAlmostEqual(c.valor(f), f - 1, places=9)
        self.assertEqual(c.valor(-5), 0.0)           # antes de la primera: constante
        self.assertEqual(c.valor(99), 10.0)          # después de la última: constante

    def test_ylocal_manda_sobre_y(self):                                       # P33
        c = leer_columnas(escena(bez("A", "<pt x='1' y='9' yLocal='2'/>", "<pt x='5' y='9' yLocal='2'/>")))["A"]
        self.assertEqual(c.valor(3), 2.0)

    def test_constseg_escalon(self):
        c = leer_columnas(escena(bez("A", "<pt x='1' y='0' constSeg='true'/>", "<pt x='10' y='5'/>")))["A"]
        self.assertEqual(c.valor(9.99), 0.0)
        self.assertEqual(c.valor(10), 5.0)

    def test_x_con_lista_y_rango_y_orden(self):                               # P35
        c = leer_columnas(escena(bez("A", "<pt x='20' y='7'/>", "<pt x='2-4' y='3'/>", "<pt x='10,12' y='3'/>")))["A"]
        self.assertEqual([p.x for p in c.puntos], [2, 3, 4, 10, 12, 20])
        self.assertEqual(c.valor(2.5), 3.0)

    def test_manijas_relativas_cuentan_y_el_recorte_mantiene_monotonia(self):
        # rhx desbordado: sin recorte x(t) no sería monótona; el valor debe seguir siendo finito y acotado entre los extremos de la cúbica
        c = leer_columnas(escena(bez("A", "<pt x='1' y='0' rhx='50' rhy='0'/>", "<pt x='11' y='10' lhx='-50' lhy='0'/>")))["A"]
        vs = [c.valor(f) for f in range(1, 12)]
        self.assertTrue(all(math.isfinite(v) and -1e-9 <= v <= 10 + 1e-9 for v in vs))
        self.assertEqual(vs, sorted(vs))

    def test_manijas_con_dx_invertido_avisan(self):
        c = leer_columnas(escena(bez("A", "<pt x='1' y='0' rhx='-3'/>", "<pt x='11' y='10'/>")))["A"]
        self.assertFalse(c.exacto)
        self.assertTrue(any("signo invertido" in a for a in c.avisos))

    def test_sin_puntos_es_cero(self):
        c = leer_columnas(escena(bez("A")))["A"]
        self.assertEqual(c.valor(3), 0.0)


class TestTrayectoria(unittest.TestCase):
    P2 = "<pt val='0,0,0' lockedInTime='1'/><pt val='9,3,-6' lockedInTime='10'/>"

    def test_dos_puntos_con_velocity_lineal(self):
        c = leer_columnas(escena(tray("T", self.P2, vel("<pt x='1' y='0'/>", "<pt x='10' y='1'/>"))))["T"]
        self.assertIsInstance(c, ColTrayectoria3D)
        for f in (1, 2, 5.5, 10):
            e = (f - 1) / 9
            q = c.posicion(f)
            for got, want in zip(q, (9 * e, 3 * e, -6 * e)):
                self.assertAlmostEqual(got, want, places=6)

    def test_llave_fija_manda_y_la_ultima_se_mantiene(self):
        # la velocity dice 0,5 en el cuadro de la segunda llave, pero en el cuadro de una llave fija manda la llave (P34)
        c = leer_columnas(escena(tray("T", self.P2, vel("<pt x='1' y='0'/>", "<pt x='10' y='0.5'/>"))))["T"]
        self.assertEqual(c.posicion(10), (9.0, 3.0, -6.0))
        self.assertEqual(c.posicion(50), (9.0, 3.0, -6.0))

    def test_sin_velocity_se_queda_en_el_primer_punto(self):
        c = leer_columnas(escena(tray("T", self.P2)))["T"]
        self.assertIsNone(c.velocidad)
        self.assertEqual(c.posicion(4), (0.0, 0.0, 0.0))

    def test_constantz_escalon(self):
        pts = "<pt val='0,0,1' lockedInTime='1'/><pt val='6,0,5' lockedInTime='7'/><pt val='9,0,9' lockedInTime='10'/>"
        c = leer_columnas(escena(tray("T", pts, vel("<pt x='1' y='0'/>", "<pt x='7' y='0.5'/>", "<pt x='10' y='1'/>"), "constantZ='true'")))["T"]
        self.assertEqual(c.posicion(3)[2], 1.0)
        self.assertEqual(c.posicion(8)[2], 5.0)

    def test_use_velo_cambia_la_longitud(self):
        # Con useVeloZ=false la z no cuenta para el avance: la trayectoria 1,0,0 -> 1,0,1 no avanza en arco (longitud 0) y queda en el primer punto
        pts = "<pt val='0,0,0' lockedInTime='1'/><pt val='0,0,3' lockedInTime='10'/>"
        c = leer_columnas(escena(tray("T", pts, vel("<pt x='1' y='0'/>", "<pt x='10' y='1'/>"), "useVeloZ='false'")))["T"]
        self.assertEqual(c.posicion(5), (0.0, 0.0, 0.0))

    def test_velocity_fuera_de_rango_avisa(self):
        c = leer_columnas(escena(tray("T", self.P2, vel("<pt x='1' y='0' rhx='4'/>", "<pt x='10' y='1' lhx='-3'/>"))))["T"]
        self.assertTrue(any("fuera de [0,1]" in a for a in c.avisos))
        self.assertFalse(c.velocidad.exacto)

    def test_metricas_de_la_escena(self):
        # La longitud depende de K: la misma trayectoria con otras métricas da otra fracción de la curva si los ejes pesan distinto
        pts = "<pt val='0,0,0' lockedInTime='1'/><pt val='5,0,0' lockedInTime='5'/><pt val='5,5,0' lockedInTime='9'/>"
        v = vel("<pt x='1' y='0'/>", "<pt x='5' y='0.5'/>", "<pt x='9' y='1'/>")
        a = leer_columnas(escena(tray("T", pts, v)), {"unitAspectRatioX": 4, "unitAspectRatioY": 3, "numberOfUnitsX": 24, "numberOfUnitsY": 24, "numberOfUnitsZ": 12})["T"]
        b = leer_columnas(escena(tray("T", pts, v)), {"unitAspectRatioX": 16, "unitAspectRatioY": 9, "numberOfUnitsX": 20, "numberOfUnitsY": 14, "numberOfUnitsZ": 10})["T"]
        self.assertNotEqual(a.posicion(3), b.posicion(3))
        self.assertGreater(a.curva.L, 0)

    # -- guardas de robustez (A3-01) -----------------------------------------------------------------
    def test_un_punto_es_constante(self):
        c = leer_columnas(escena(tray("T", "<pt val='1,2,3' lockedInTime='4'/>", vel("<pt x='4' y='0'/>"))))["T"]
        for f in (-3, 0, 4, 4.5, 100):
            self.assertEqual(c.posicion(f), (1.0, 2.0, 3.0))
        self.assertTrue(c.avisos)

    def test_puntos_coincidentes_no_lanzan(self):
        pts = "<pt val='2,2,2' lockedInTime='1'/><pt val='2,2,2'/><pt val='2,2,2' lockedInTime='9'/>"
        c = leer_columnas(escena(tray("T", pts, vel("<pt x='1' y='0'/>", "<pt x='9' y='1'/>"))))["T"]
        for f in range(0, 12):
            self.assertEqual(c.posicion(f), (2.0, 2.0, 2.0))
        self.assertTrue(any("longitud total nula" in a for a in c.avisos))

    def test_dos_cuerdas_nulas_pesos_medios(self):
        # A, A, A, B: el punto 1 tiene las dos cuerdas nulas (d0 = d1 = 0): w0 = w1 = 0,5 y tangente 0; no hay 0/0
        pts = "<pt val='0,0,0' lockedInTime='1'/><pt val='0,0,0'/><pt val='0,0,0'/><pt val='3,0,0' lockedInTime='9'/>"
        c = leer_columnas(escena(tray("T", pts, vel("<pt x='1' y='0'/>", "<pt x='9' y='1'/>"))))["T"]
        for f in (1, 3, 5, 9):
            self.assertTrue(all(math.isfinite(v) for v in c.posicion(f)))
        self.assertEqual(c.posicion(9), (3.0, 0.0, 0.0))
        self.assertEqual(c.curva.sal[1], [0.0, 0.0, 0.0])

    def test_trayectoria_sin_puntos_y_sin_path3d(self):
        cols = leer_columnas(escena(tray("T", ""), "<column type='2' name='S'/>"))
        self.assertEqual(cols["T"].posicion(3), (0.0, 0.0, 0.0))
        self.assertIsInstance(cols["S"], ColOpaca)


class TestExposicion(unittest.TestCase):
    def col(self, xml):
        return leer_columnas(escena(xml), elementos_validos={2, 3})["D"]

    def test_parse_exposures_tolerante(self):
        self.assertEqual(E.parse_exposures("1-4,7,9-10"), [(1, 4), (7, 7), (9, 10)])
        self.assertEqual(E.parse_exposures("+3,3.5,-3,1-,a,6-3"), [(6, 6)])
        self.assertEqual(E.parse_exposures("1, 3"), [(1, 1)])

    def test_sin_hold_ni_dibujo_fuera(self):
        c = self.col("<column type='0' name='D' id='2'><elementSeq id='2' val='1' exposures='3'/><elementSeq id='2' val='2' exposures='7'/></column>")
        self.assertIsInstance(c, ColExposicion)
        self.assertIsNone(c.dibujo(2))
        self.assertEqual(c.dibujo(3), ("1", 2))
        self.assertIsNone(c.dibujo(5))
        self.assertEqual(c.dibujo(7), ("2", 2))
        self.assertIsNone(c.dibujo(9))

    def test_heldseq_no_muestra_dibujo(self):
        c = self.col("<column type='0' name='D' id='2'><elementSeq id='2' val='1' exposures='1'/><heldSeq exposures='2-3'/></column>")
        self.assertEqual(c.dibujo(1), ("1", 2))
        self.assertIsNone(c.dibujo(3))
        self.assertFalse(c.celda(3)["vacia"])
        self.assertTrue(c.celda(3)["sostenida"])

    def test_elemento_inexistente_se_ignora(self):
        c = self.col("<column type='0' name='D' id='2'><elementSeq id='99' val='1' exposures='1-3'/><elementSeq val='' exposures='5'/></column>")
        self.assertIsNone(c.dibujo(1))
        self.assertTrue(c.avisos)

    def test_solapes_en_orden_de_archivo(self):                                # P30 sección 4
        c = self.col("<column type='0' name='D' id='2'><elementSeq id='2' val='1' exposures='2-5'/><elementSeq id='2' val='2' exposures='2-3'/></column>")
        self.assertEqual(c.dibujo(2), ("1", 2))
        self.assertEqual(c.dibujo(3), ("2", 2))
        self.assertIsNone(c.dibujo(4))
        self.assertIsNone(c.dibujo(5))

    def test_elementseq_sin_id_usa_el_de_la_columna(self):
        c = self.col("<column type='0' name='D' id='3'><elementSeq val='a' exposures='1'/></column>")
        self.assertEqual(c.dibujo(1), ("a", 3))


class TestRobustez(unittest.TestCase):
    def test_mapping_perezoso(self):
        cols = leer_columnas(escena(bez("A", "<pt x='1' y='0'/>"), "<column type='1' name='S'/>", "<column type='10' name='J'/>", "<column type='77' name='X'/>"))
        self.assertEqual(list(cols), ["A", "S", "J", "X"])
        self.assertEqual(len(cols), 4)
        self.assertIn("S", cols)
        self.assertIs(cols["A"], cols["A"])
        self.assertEqual(cols["S"].tipo, 1)
        self.assertEqual(cols["J"].avisos, [])
        self.assertTrue(cols["X"].avisos)
        with self.assertRaises(KeyError):
            cols["no_existe"]
        self.assertEqual(cols["S"].evaluar(3), None)

    def test_nombres_repetidos_y_sin_nombre(self):
        cols = leer_columnas(escena(bez("A", "<pt x='1' y='1'/>"), bez("A", "<pt x='1' y='2'/>"), "<column type='3'/>"))
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols["A"].valor(1), 2.0)
        self.assertEqual(len(cols.avisos), 2)

    def test_sin_columns_o_metricas_raras(self):
        self.assertEqual(len(leer_columnas(ET.fromstring("<scene/>"))), 0)
        c = leer_columnas(escena(tray("T", "<pt val='0,0,0' lockedInTime='1'/><pt val='1,0,0'/>")), {"numberOfUnitsY": 0, "unitAspectRatioY": "x"})["T"]
        self.assertEqual(len(c.posicion(3)), 3)
        self.assertTrue(any("inválida" in a for a in c.avisos))

    def test_basura_no_lanza(self):
        malas = [
            "<column type='abc' name='A'/>",
            bez("B", "<pt y='3'/>", "<pt x='zz' y='1'/>", "<pt x='1-' y='q'/>", "<pt x='1e999,nan' y='1' rhx='inf'/>", "<pt x='5' y='nan' lhy='x'/>"),
            tray("C", "<pt val='1,2' lockedInTime='x'/><pt val='a,b,c' tension='zz'/><pt/><pt val='1,1,1' lockedInTime='nan'/>", vel("<pt x='1'/>", "<pt x='9' y='1' rhx='z'/>"), "constantZ='true' useVeloX='no'"),
            tray("D", "<pt val='1,1,1' lockedInTime='1'/><pt val='2,2,2' lockedInTime='2'/>", "<velocity><points><pt x='1-100000000' y='1'/></points></velocity>"),
            "<column type='0' name='E' id='x'><elementSeq id='y' val='1' exposures='1-99999999999'/><elementSeq val='q' exposures='5-4,,,'/><otro/></column>",
            "<column type='2' name='F'><path3D><points/></path3D><velocity/></column>",
        ]
        cols = leer_columnas(escena(*malas))
        for nombre in cols:
            c = cols[nombre]
            for f in (-1, 0, 1, 2.5, 5, 1e9, float("nan"), float("inf"), -float("inf")):
                r = c.evaluar(f)
                if isinstance(r, tuple) and len(r) == 3 and isinstance(r[0], float):
                    self.assertTrue(all(isinstance(v, float) for v in r))
                elif isinstance(r, float):
                    self.assertIsInstance(r, float)


if __name__ == "__main__":
    unittest.main()
