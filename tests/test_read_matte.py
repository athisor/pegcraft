"""Puerto 1 del READ = matte propio (13-11-2026).
Sintetico (grafo falso): el READ con cable en el puerto 1 lleva un recorte invertido con ese matte; PEGCRAFT_READ_MATTE=no lo apaga.
python -m unittest discover -s tests -p test_read_matte.py"""
import os, sys, unittest
from types import SimpleNamespace
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pegcraft.bake import apilado


class G:
    """Grafo minimo con la interfaz que usa recorrer_conectores."""
    def __init__(self, nodos, cables, attrs=None):
        self.nodos = {n: SimpleNamespace(tipo=t, apagado=False) for n, t in nodos.items()}      # misma interfaz que sightread.lector.Escena
        self.cables = cables            # {(destino, puerto): [fuente, ...]}
        self.attrs = attrs or {}        # {(nodo, atributo): valor}

    def fuentes(self, nodo, puerto=0):
        return [(s, 0) for s in self.cables.get((nodo, puerto), [])]

    def entradas(self, nodo):
        return {p: (self.cables[(n, p)][0], 0) for (n, p) in sorted(self.cables) if n == nodo}

    def puertos_composite(self, nodo):
        return sorted(self.entradas(nodo))

    def atributo(self, nodo, *ruta):
        return self.attrs.get((nodo, "/".join(ruta)))


def _pupila(attrs=None, matte="Ojo"):
    """Composite <- Ojo (puerto 0), Pupila (puerto 1); Pupila tiene `matte` en su puerto 1."""
    nodos = {"C": "COMPOSITE", "Ojo": "READ", "Pupila": "READ", "CA": "COLOR_ART", "PegP": "PEG"}
    cables = {("C", 0): ["Ojo"], ("C", 1): ["Pupila"], ("Pupila", 0): ["PegP"], ("Pupila", 1): [matte], ("CA", 0): ["Ojo"]}
    return G(nodos, cables, attrs)


class TestReadMatte(unittest.TestCase):
    def setUp(self):
        os.environ.pop("PEGCRAFT_READ_MATTE", None)

    def tearDown(self):
        os.environ.pop("PEGCRAFT_READ_MATTE", None)

    def _hojas(self, g):
        hojas, avisos, _ = apilado.recorrer_conectores(g, "C")
        return {h["id"]: h for h in hojas}, avisos

    def test_read_con_matte_en_puerto_1(self):
        h, _ = self._hojas(_pupila())
        self.assertEqual(list(h), ["Ojo", "Pupila"])          # el matte no se dibuja de nuevo ni cambia el orden
        self.assertEqual(h["Ojo"]["recorte"], [])
        r = h["Pupila"]["recorte"]
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0]["invertido"]); self.assertEqual(r[0]["nodo"], "Pupila")
        self.assertEqual(r[0]["mattes"], [{"id": "Ojo", "capas": list(apilado.TODAS)}])

    def test_matte_por_filtro_de_capa(self):
        h, _ = self._hojas(_pupila(matte="CA"))
        self.assertEqual(h["Pupila"]["recorte"][0]["mattes"], [{"id": "Ojo", "capas": ["colour"]}])

    def test_invert_matte_port(self):
        h, av = self._hojas(_pupila({("Pupila", "invertMattePort"): "true"}))
        self.assertFalse(h["Pupila"]["recorte"][0]["invertido"])
        self.assertTrue(any("invertMattePort" in a for a in av))

    def test_sin_cable_no_cambia(self):
        g = _pupila(); del g.cables[("Pupila", 1)]
        h, _ = self._hojas(g)
        self.assertEqual(h["Pupila"]["recorte"], [])

    def test_apagado_por_entorno(self):
        os.environ["PEGCRAFT_READ_MATTE"] = "no"
        h, _ = self._hojas(_pupila())
        self.assertEqual(h["Pupila"]["recorte"], [])

    def test_se_suma_al_recorte_de_un_cutter(self):
        g = _pupila()
        g.nodos["K"] = SimpleNamespace(tipo="CUTTER", apagado=False); g.nodos["M"] = SimpleNamespace(tipo="READ", apagado=False)
        g.cables[("C", 1)] = ["K"]; g.cables[("K", 0)] = ["Pupila"]; g.cables[("K", 1)] = ["M"]
        h, _ = self._hojas(g)
        self.assertEqual([r["nodo"] for r in h["Pupila"]["recorte"]], ["K", "Pupila"])


if __name__ == "__main__":
    unittest.main()
