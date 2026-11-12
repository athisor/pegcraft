"""Avisos de efectos no modelados (12-11-2026): BLEND_MODE_MODULE, GLOW (radio > 0, varios) y PointConstraint2 con volumemin/volumemax fuera del defecto.
Los avisos no cambian el render. Sintetico (grafo y XML falsos) + codigos de compilar/avisos.py.
python -m unittest discover -s tests -p test_avisos_efectos.py"""
import os, sys, unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from pegcraft.bake import apilado, matriz_causal as mc
from pegcraft.compilar import avisos


class TestEfectos(unittest.TestCase):
    def test_multiply_se_avisa_con_su_modo(self):
        av = apilado.avisos_efectos({"Top/Oso/NN_Blending": {"tipo": "BLEND_MODE_MODULE", "modo": "eMULTIPLY", "radio": None, "multiplicativo": False}})
        self.assertEqual(len(av), 1); self.assertIn("eMULTIPLY", av[0]); self.assertIn("Top/Oso/NN_Blending", av[0])
        self.assertEqual(avisos.codigo(av[0]), "BLEND_MODE_NO_MODELADO")

    def test_blend_normal_no_avisa(self):
        self.assertEqual(apilado.avisos_efectos({"a": {"tipo": "BLEND_MODE_MODULE", "modo": "eNORMAL_BLEND", "radio": None, "multiplicativo": False}}), [])

    def test_glow_radio_cero_unico_no_avisa(self):
        self.assertEqual(apilado.avisos_efectos({"g": {"tipo": "GLOW", "modo": None, "radio": "0", "multiplicativo": False}}), [])

    def test_glow_con_radio(self):
        av = apilado.avisos_efectos({"g": {"tipo": "GLOW", "modo": None, "radio": "2.5", "multiplicativo": False}})
        self.assertEqual([avisos.codigo(a) for a in av], ["GLOW_NO_MODELADO"]); self.assertIn("radio=2.5", av[0])

    def test_glow_radio_ilegible(self):
        av = apilado.avisos_efectos({"g": {"tipo": "GLOW", "modo": None, "radio": None, "multiplicativo": False}})
        self.assertEqual([avisos.codigo(a) for a in av], ["GLOW_NO_MODELADO"])

    def test_varios_glow(self):
        g = {"tipo": "GLOW", "modo": None, "radio": "0", "multiplicativo": False}
        av = apilado.avisos_efectos({"Top/Glow": g, "Top/Glow_1": g, "Top/Glow_2": g})
        self.assertEqual([avisos.codigo(a) for a in av], ["GLOW_MULTIPLE"]); self.assertIn("3 activos", av[0])


def _pc2(attrs_xml):
    """Fakes minimos para llegar al aviso de _constraints_pc2: un PointConstraint2 con dos PEG hermanos (L0 = 0 -> sale tras avisar)."""
    attrs = ET.fromstring("<attrs>" + attrs_xml + "</attrs>")
    el = SimpleNamespace(find=lambda r: attrs if r == "attrs" else None)
    nodos = {"PC": SimpleNamespace(type="PointConstraint2"), "E0": SimpleNamespace(type="PEG"), "E1": SimpleNamespace(type="PEG")}
    g = SimpleNamespace(nodes=nodos, resolve_source=lambda pc, p: [("E0", 0), ("E1", 0)][p])
    doc = SimpleNamespace(nodes={"PC": SimpleNamespace(element=el), "E0": SimpleNamespace(element=ET.fromstring("<m/>")), "E1": SimpleNamespace(element=ET.fromstring("<m/>"))})
    C = SimpleNamespace(ruta_nodo=lambda r: r)
    L = SimpleNamespace(cadena_de=lambda g, r, modo: [])
    J = SimpleNamespace(_num=lambda doc, e, f: (float(e.get("val")), None))
    av = []
    mc._constraints_pc2(g, doc, 4 / 3, 1, lambda r: np.eye(3), C, L, J, av)
    return av


_BASE = '<transformtype val="TRANSLATE"/><primaryport val="RIGHT"/>'


class TestPC2Volumen(unittest.TestCase):
    def test_defecto_no_avisa(self):
        self.assertEqual(_pc2(_BASE + '<volumemin val="25"/><volumemax val="200"/><volumemod val="75"/>'), [])

    def test_sin_atributos_no_avisa(self):
        self.assertEqual(_pc2(_BASE), [])

    def test_volumemin_fuera_del_defecto(self):
        av = _pc2(_BASE + '<volumemin val="10"/><volumemax val="200"/>')
        self.assertEqual(len(av), 1); self.assertIn("volumemin=10", av[0]); self.assertNotIn("volumemax", av[0])
        self.assertEqual(avisos.codigo(av[0]), "PC2_NO_MEDIDO")

    def test_volumemax_fuera_del_defecto(self):
        av = _pc2(_BASE + '<volumemax val="400"/>')
        self.assertIn("volumemax=400", av[0])

    def test_otro_parametro_sigue_avisando(self):
        self.assertIn("balance=10", _pc2(_BASE + '<balance val="10"/>')[0])


if __name__ == "__main__":
    unittest.main()
