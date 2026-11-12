"""censo.py: seguimiento del puerto del TransformationSwitch (sin Harmony ni escenas)."""
import os, sys, unittest
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pegcraft.bake import censo as C

COL = ('<column type="0" name="Drawing-Cuello"><elementSeq exposures="1-73" val="2"/>'
       '<elementSeq exposures="74,80-82" val="7"/></column><column type="0" name="Otra"><elementSeq exposures="1" val="9"/></column>')


class TestCensoSwitch(unittest.TestCase):
    def test_exposicion(self):
        self.assertEqual(C._exposicion(COL, "Drawing-Cuello", 6), "2")
        self.assertEqual(C._exposicion(COL, "Drawing-Cuello", 81), "7")
        self.assertIsNone(C._exposicion(COL, "Drawing-Cuello", 75))
        self.assertIsNone(C._exposicion(COL, "NoExiste", 1))

    def test_modo(self):
        ant = os.environ.get("PEGCRAFT_SWITCH")
        try:
            os.environ["PEGCRAFT_SWITCH"] = "0"
            self.assertIsNone(C._modo_switch())
            os.environ["PEGCRAFT_SWITCH"] = "cuello"
            rx = C._modo_switch()
            self.assertTrue(rx.search("Top/Flamenco/Deformation-Flamenco_Cuello/Transformation-Switch"))
            self.assertFalse(rx.search("Top/Flamenco/Deformation-Flamenco_Craneo/Transformation-Switch"))
            os.environ["PEGCRAFT_SWITCH"] = "todos"
            self.assertTrue(C._modo_switch().search("x"))
        finally:
            if ant is None:
                os.environ.pop("PEGCRAFT_SWITCH", None)
            else:
                os.environ["PEGCRAFT_SWITCH"] = ant

    def test_grupos_deformadores(self):
        from pegcraft.bake import deformadores as D
        O = lambda d: {"tipo": "OffsetModule", "delta": d}
        K = lambda d: {"tipo": "CurveModule", "delta": d}
        cad = [K(0), O(0), K(3), K(2), O(0)]            # del mas cercano (hijo, en reposo) al mas lejano (padre, activo)
        self.assertEqual(len(D.grupos(list(reversed(cad)))), 2)
        act = D.activos(cad)
        self.assertEqual([n["delta"] for n in act], [0, 2, 3])   # solo el padre; el hijo en reposo es la identidad
        self.assertEqual(D.activos([K(0), O(0)]), [])

    def test_segmentos(self):
        from pegcraft.bake import deformadores as D
        O = lambda d: {"tipo": "OffsetModule", "delta": d}
        K = lambda d: {"tipo": "CurveModule", "delta": d}
        P = lambda r: {"tipo": "PEG", "ruta": r}
        cad = [P("a"), K(0), O(0), P("b"), K(3), O(0), P("c")]   # hijo en reposo, PEG b, padre activo
        sg = D.segmentos(cad)
        self.assertEqual(len(sg), 1)
        self.assertEqual(sg[0]["pegs"], ["a", "b"])             # los PEG del grupo en reposo pasan al segmento siguiente


if __name__ == "__main__":
    unittest.main()
