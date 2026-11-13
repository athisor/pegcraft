"""Integracion de bake/gradientes con sightread.plt: paleta de la escena sobre la TPAL y degradados con la matriz de modelo["tgco"]."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pegcraft.bake import gradientes as G
from pegcraft.compilar import almacen

CAB = "ToonBoomAnimationInc PaletteFile 2"
GID, SID = "0d00000000000011", "0d00000000000001"


def modelo():
    # Bucles horarios con el color en "izq": rodean una region rellena (CENSO-20; uno antihorario seria el exterior y no se rellena).
    tr = {"puntos": [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)], "anclas": [True] * 5, "cerrado": True, "perfil": None, "ref": None,
          "estilo": {"der": None, "izq": GID, "lapiz": None, "ancho": 0.0, "invisible": False}}
    tr2 = dict(tr, puntos=[(20, 0), (20, 10), (30, 10), (30, 0), (20, 0)], estilo=dict(tr["estilo"], izq=SID))
    return {"disp": "D2", "avisos": [],
            "paleta": {SID: {"nombre": "Piel", "rgba": (1, 2, 3, 255), "paleta": "Local", "tipo": "solido"},
                       GID: {"nombre": "Cielo", "rgba": None, "paleta": "Local", "tipo": "degradado"}},
            "artes": {"colour": {"capas": [{"trazos": [tr, tr2]}]}},
            "tgco": {GID: [(10.0, 0.0, 0.0, 10.0, 0.0, 5.0)]}}


class TestGradientes(unittest.TestCase):
    def test_degradado_y_paleta_de_escena(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "palette-library").mkdir()
            (t / "palette-library" / "Esc.plt").write_text(
                f"{CAB}\nSolid    Piel                       0x{SID} 200 100  50 255\n"
                f"Gradient Cielo                      0x{GID} Linear \n{{        0.0 148 148 238 255,\n       100.0 229 229 229 255 }}\n", encoding="utf-8")
            (t / "PALETTE_LIST").write_text('ToonBoomAnimationInc PaletteList 1\npalette-library/Esc LINK "x"\n', encoding="utf-8")
            (t / "elements" / "dib").mkdir(parents=True)
            tvg = t / "elements" / "dib" / "dib-1.tvg"
            tvg.write_bytes(b"")
            with mock.patch.object(G, "_decodificar", lambda datos: modelo()):
                r = G.convertir(tvg, t, t / "o.svg")
            svg = (t / "o.svg").read_text(encoding="utf-8")
            self.assertIn(f"url(#grad_{GID})", svg)
            self.assertIn("<linearGradient", svg)
            self.assertIn('fill="#c86432"', svg)          # la paleta de la escena (200,100,50) gana sobre la TPAL (1,2,3)
            self.assertEqual(r["gradientes"][0]["id"], GID)
            self.assertEqual(r["avisos"], [])


class TestVersionConversor(unittest.TestCase):
    def test_hash_estable_y_sin_entorno(self):
        almacen._memo.pop("ver", None)
        v = almacen.version_conversor()
        self.assertEqual(len(v), 16)
        self.assertEqual(almacen.version_conversor(), v)


if __name__ == "__main__":
    unittest.main()
