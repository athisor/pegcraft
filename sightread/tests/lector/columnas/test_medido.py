"""Pruebas contra lo que Harmony 24 evaluó (caja negra) en escenas sintéticas: fixtures `fixtures/<caso>/columnas.xml` (solo las columnas, los elementos y las
métricas de la escena) + `esperado.json` (valores medidos). Procedencia: P30 (exposición), P31-P33 (Bézier), P34 (trayectoria 3D).

Correr (PowerShell 5.1), desde la raíz del repo:
    python -I -m unittest discover -s tests\\lector\\columnas -v
Criterios: función <= 1e-4 (<= 1,5e-4 en la validación ciega s10, donde Harmony redondeó a 4 decimales un tramo recortado de pendiente casi vertical), trayectoria <= 5e-5 campos,
exposición 0 diferencias.
"""
import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parents[3]))
from sightread.lector.columnas import ColExposicion, ColFuncion, ColTrayectoria3D, leer_columnas  # noqa: E402
from sightread.lector.columnas.base import Metricas  # noqa: E402

FX = AQUI / "fixtures"


def cargar(caso):
    raiz = ET.parse(FX / caso / "columnas.xml").getroot()
    metricas = {k: float(v) for k, v in raiz.find("options/metrics").attrib.items()}
    cols = leer_columnas(raiz.find("scenes/scene"), metricas, elementos_validos={int(e.get("id")) for e in raiz.iter("element")})
    return cols, json.loads((FX / caso / "esperado.json").read_text(encoding="utf-8")), metricas


class TestFuncionMedida(unittest.TestCase):
    def _probar(self, caso, tope):
        cols, esp, _ = cargar(caso)
        peor, n = 0.0, 0
        for nombre, valores in esp["columnas"].items():
            col = cols[nombre]
            self.assertIsInstance(col, ColFuncion)
            for f, v in valores.items():
                err = abs(col.valor(int(f)) - v)
                peor = max(peor, err)
                n += 1
                self.assertLess(err, tope, f"{caso}/{nombre} f{f}: {col.valor(int(f))} vs {v}")
        self.assertGreater(n, 100)
        return peor

    def test_e02_corner_straight_smooth(self):
        """corner, plano, straight y smooth: manijas relativas, alineación de interiores y recorte (P31, P32)."""
        self.assertLess(self._probar("bezier_e02", 1e-4), 1e-4)       # medido: 4,7e-5

    def test_validacion_ciega_s10(self):
        """8 columnas al azar de 5 a 7 puntos irregulares, continuidad mezclada, manijas que desbordan y algún constSeg (P32)."""
        # medido: 1,38e-4 (solo en tramos recortados al borde con pendiente casi vertical: es el redondeo a 4 decimales de Harmony)
        self.assertLess(self._probar("bezier_s10", 1.5e-4), 1.5e-4)

    def test_puntos_ordenados_por_x_y_lista_de_cuadros(self):
        cols, _, _ = cargar("bezier_e02")
        xs = [p.x for p in cols["C_d3_corner"].puntos]
        self.assertEqual(len(xs), 3)
        self.assertEqual(xs, sorted(xs))


class TestTrayectoriaMedida(unittest.TestCase):
    def _probar(self, caso):
        cols, esp, metricas = cargar(caso)
        met, _ = Metricas.de_dict(metricas)
        for nombre, matriz in esp["columnas"].items():
            col = cols[nombre]
            self.assertIsInstance(col, ColTrayectoria3D)
            peor = 0.0
            for i, m in enumerate(matriz):
                q = col.posicion(i + 1)
                h = (m[0] / met.KX, m[1] / met.KY, m[2] / met.KZ)
                peor = max(peor, max(abs(h[k] - q[k]) for k in range(3)))
            self.assertLess(peor, 5e-5, f"{caso}/{nombre}: error {peor}")
            self.assertEqual(col.avisos, [])

    def test_s11_validacion_seis_llaves_y_punto_de_control(self):
        self._probar("path3d_s11")

    def test_s12_con_manijas_de_velocity(self):
        self._probar("path3d_s12")

    def test_velocity_es_una_funcion(self):
        cols, _, _ = cargar("path3d_s12")
        self.assertIsInstance(cols["C_val1"].velocidad, ColFuncion)

    def test_unidades_desde_metrics(self):
        m, avisos = Metricas.de_dict({"unitAspectRatioX": 4, "unitAspectRatioY": 3, "numberOfUnitsX": 24, "numberOfUnitsY": 24, "numberOfUnitsZ": 12})
        self.assertEqual(avisos, [])
        self.assertAlmostEqual(m.KX, 1 / 9)
        self.assertAlmostEqual(m.KY, 1 / 12)
        self.assertAlmostEqual(m.KZ, 2 / 9)
        m2, _ = Metricas.de_dict({"unitAspectRatioX": 16, "unitAspectRatioY": 9, "numberOfUnitsX": 20, "numberOfUnitsY": 14, "numberOfUnitsZ": 10})
        self.assertAlmostEqual(m2.KY, 2 / 14)


class TestExposicionMedida(unittest.TestCase):
    def _probar(self, caso):
        cols, esp, _ = cargar(caso)
        n = 0
        for nombre, entradas in esp["columnas"].items():
            col = cols[nombre]
            self.assertIsInstance(col, ColExposicion)
            for f, entrada in enumerate(entradas, 1):
                d = col.dibujo(f)
                self.assertEqual(d[0] if d else "", entrada, f"{caso}/{nombre} f{f}")
                n += 1
        self.assertGreater(n, 1000)

    def test_xV4(self):
        self._probar("expo_xV4")

    def test_xV5(self):
        self._probar("expo_xV5")


if __name__ == "__main__":
    unittest.main()
