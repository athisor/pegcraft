"""El color aditivo de un GLOW es el del nodo GLOW, no el del dibujo (13-11-2026)."""
import unittest
from types import SimpleNamespace

from pegcraft.bake import apilado


class _Grafo:
    """COMPOSITE -> GLOW -> READ minimo, con la interfaz que usa recorrer_conectores."""

    def __init__(self):
        self.nodos = {"C": SimpleNamespace(tipo="COMPOSITE", apagado=False),      # misma interfaz que sightread.lector.Escena
                      "G": SimpleNamespace(tipo="GLOW", apagado=False),
                      "R": SimpleNamespace(tipo="READ", apagado=False)}

    def puertos_composite(self, nodo):
        return [0]

    def fuentes(self, nodo, port=0):
        return {"C": [("G", 0)], "G": [("R", 0)]}.get(nodo, [])

    def entradas(self, nodo):
        return {"C": {0: ("G", 0)}, "G": {0: ("R", 0)}}.get(nodo, {})

    def atributo(self, nodo, *k):
        d = {
            ("compositeMode",): "compositePassthrough",
            ("multiplicative",): "false", ("colourGain",): "1",
            ("color", "alpha"): "105",
            ("color", "red"): "126", ("color", "green"): "222", ("color", "blue"): "255",
        }
        return d.get(k)


class TestGlowColor(unittest.TestCase):
    def test_la_hoja_lleva_el_color_del_glow(self):
        hojas, _, _ = apilado.recorrer_conectores(_Grafo(), "C")
        self.assertEqual(len(hojas), 1)
        h = hojas[0]
        self.assertTrue(h.get("glow"))
        self.assertEqual(h["glow_color"], [126.0, 222.0, 255.0])
        self.assertAlmostEqual(h["glow_gain"], 105 / 255)


if __name__ == "__main__":
    unittest.main()
