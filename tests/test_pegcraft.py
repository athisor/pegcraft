"""Pruebas minimas. Rapidas (sin Harmony ni .xstage): python -m unittest discover -s tests
"""
import os, sys, tempfile, unittest
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from PIL import Image


class TestMetricas(unittest.TestCase):
    def test_identicas(self):
        from pegcraft.medir import metricas as M
        d = tempfile.mkdtemp(); p = os.path.join(d, "a.png")
        im = np.zeros((20, 30, 4), np.uint8); im[5:10, 5:10] = (200, 10, 10, 255)
        Image.fromarray(im).save(p)
        r = M.metricas(p, p, p)
        self.assertEqual(r["px_ok"], 1.0); self.assertEqual(r["px_ok_personajes"], 1.0)
        g = M.metrica_grupo(p, p, caja=(0, 0, 30, 20))
        self.assertEqual(g["iou_alfa"], 1.0)

    def test_distintas(self):
        from pegcraft.medir import metricas as M
        d = tempfile.mkdtemp(); a, b = os.path.join(d, "a.png"), os.path.join(d, "b.png")
        x = np.zeros((10, 10, 4), np.uint8); y = x.copy(); y[:5] = (255, 255, 255, 255)
        Image.fromarray(x).save(a); Image.fromarray(y).save(b)
        self.assertAlmostEqual(M.metricas(a, b)["px_ok"], 0.5)


class TestMatrizCausal(unittest.TestCase):
    def test_regla_4_3(self):
        """Una traslacion de 3 campos en x pesa A=4/3 en el espacio isotropo; el giro se compone ya en espacio isotropo."""
        from pegcraft.bake import matriz_causal as mc
        M = mc._m({"posicion.x": 3.0, "posicion.y": 1.0}, 4 / 3)
        self.assertAlmostEqual(M[0, 2], 4.0); self.assertAlmostEqual(M[1, 2], 1.0)
        R = mc._m({"rotacion": 90.0}, 4 / 3)
        self.assertAlmostEqual(R[0, 1], -1.0); self.assertAlmostEqual(R[1, 0], 1.0)


class TestDeformadores(unittest.TestCase):
    def _nodos(self, dx):
        z = lambda ox: {"offset/x": ox, "offset/y": 0.0, "length0": 1.0, "orientation0": 0.0, "length1": 1.0, "orientation1": 0.0}
        return [{"tipo": "OffsetModule", "act": {"offset/x": 0.0, "offset/y": 0.0, "orientation": 0.0}, "rep": {"offset/x": 0.0, "offset/y": 0.0, "orientation": 0.0}},
                {"tipo": "CurveModule", "act": z(3.0 + dx), "rep": z(3.0)}]

    def test_reposo_es_identidad(self):
        from pegcraft.bake import deformadores as D
        d = D.Deformador(self._nodos(0.0), 1.0, 1.0)
        q = np.array([[0.5, 0.0], [2.0, 0.0]])
        self.assertTrue(np.allclose(d.puntos(q), q, atol=1e-3))

    def test_traslada_con_la_curva(self):
        from pegcraft.bake import deformadores as D
        d = D.Deformador(self._nodos(1.0), 1.0, 1.0)          # el extremo se aleja 1 campo
        out = d.puntos(np.array([[3.0, 0.0]]))
        self.assertAlmostEqual(float(out[0, 0]), 4.0, places=1)


@unittest.skipUnless(os.environ.get("PEGCRAFT_INTEGRACION"), "integracion: PEGCRAFT_INTEGRACION=1")
class TestIntegracion(unittest.TestCase):
    def test_verificar_0530(self):
        from pegcraft.verificar import verificar_0530
        self.assertEqual(verificar_0530(), 0)


if __name__ == "__main__":
    unittest.main()
