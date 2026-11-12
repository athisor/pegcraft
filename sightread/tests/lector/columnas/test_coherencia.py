"""Pruebas de tools/coherencia_path3d.py con escenas mínimas inventadas (sin Harmony)."""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ.parent))
sys.path.insert(0, str(RAIZ / "tools"))
import coherencia_path3d as C  # noqa: E402


def proyecto(y2, attrs_project="source='Harmony Premium 24' version='2402' build='1' creator='harmony'", attrs_col="type='2' name='T' anonymous='false'"):
    return ET.fromstring(
        f"<project {attrs_project}><options><metrics unitAspectRatioX='4' unitAspectRatioY='3' numberOfUnitsX='24' numberOfUnitsY='24' numberOfUnitsZ='12'/></options>"
        f"<scenes><scene name='Top'><columns><column {attrs_col}><path3D><points><pt val='0,0,0' lockedInTime='1'/><pt val='3,2,1' lockedInTime='10'/></points></path3D>"
        f"<velocity><points version='2'><pt x='1' y='0'/><pt x='10' y='{y2}'/></points></velocity></column></columns></scene></scenes></project>")


class TestCoherencia(unittest.TestCase):
    def test_coherente(self):
        r = C.coherencia_de(proyecto("1"))
        self.assertTrue(r["coherente"])
        self.assertEqual((r["columnas_3d"], r["llaves"], r["hist"]["<=1e-4"]), (1, 2, 2))

    def test_incoherente(self):
        r = C.coherencia_de(proyecto("0.8"))
        self.assertFalse(r["coherente"])
        self.assertEqual(r["llaves_sobre_tope"], 1)
        self.assertEqual(r["columnas_sobre_1e-3"], 1)

    def test_detecta_escena_no_guardada_por_harmony(self):
        ok, _ = C.guardada_por_harmony(proyecto("1"))
        self.assertTrue(ok)
        ok, motivo = C.guardada_por_harmony(proyecto("1", attrs_project="build='1' creator='x' source='Harmony 24' version='2402'"))
        self.assertFalse(ok)
        self.assertIn("alfabético", motivo)
        ok, motivo = C.guardada_por_harmony(proyecto("1", attrs_col="anonymous='false' name='T' type='2'"))
        self.assertFalse(ok)
        ok, _ = C.guardada_por_harmony(proyecto("1", attrs_project="source='otra cosa' version='1' build='1' creator='x'"))
        self.assertFalse(ok)

    def test_archivo_ilegible_no_lanza(self):
        r = C.revisar(RAIZ / "no_existe.xstage")
        self.assertIn("error", r)


if __name__ == "__main__":
    unittest.main()
