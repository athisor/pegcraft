"""Pruebas de la escena de ejemplo `ejemplos/escena_minima/` (sintetica).

    python -I -m unittest discover -s tests -p "test_ejemplo_minimo.py"
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "sightread" / "sintetico"))
EJ = RAIZ / "ejemplos" / "escena_minima"
_spec = importlib.util.spec_from_file_location("generar_ejemplo", EJ / "generar.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

from pegcraft import config, ver as V
from sightread import plt
from sightread.lector import abrir
from sightread.tvg import a_svg, decodificar


class TestEjemploMinimo(unittest.TestCase):
    def test_esta_al_dia_con_el_generador(self):
        for ruta, datos in G.archivos().items():
            self.assertEqual((EJ / ruta).read_bytes(), datos, ruta)

    def test_sin_firma_ni_nombres_de_produccion(self):
        for f in EJ.rglob("*.tvg"):
            b = f.read_bytes()
            self.assertNotIn(b"CERT", b)
            self.assertNotIn(b"SIGN", b)
        self.assertNotIn("checksumValidation", (EJ / "escena.xstage").read_text(encoding="utf-8"))

    def test_los_dibujos_se_leen_y_dibujan(self):
        tvgs = sorted(EJ.glob("elements/*/*.tvg"))
        self.assertEqual([f.parent.name for f in tvgs], ["Circulo", "Cuadrado", "Fondo", "Triangulo"])
        for f in tvgs:
            m = decodificar(f.read_bytes())
            self.assertEqual(m["avisos"], [])
            s = a_svg(m)
            self.assertIn('<g id="colour">', s)
            self.assertIn('<g id="line">', s)

    def test_paleta_de_la_escena_coincide_con_la_tpal(self):
        de_escena = plt.paleta_tvg(EJ)
        self.assertEqual(len(de_escena), 6)
        for f in EJ.glob("elements/*/*.tvg"):
            for cid, c in decodificar(f.read_bytes())["paleta"].items():
                self.assertEqual(tuple(de_escena[cid]["rgba"]), c["rgba"])

    def test_escena_lee_cuatro_dibujos(self):
        esc = abrir(str(EJ / "escena.xstage"))
        self.assertTrue(esc)

    def test_hornea_y_dibuja(self):
        """El fotograma 1 (el del README) coincide con `esperado_f1.png`: IoU del alfa >= 0,99 y color <= 1/255 en >= 99 % de los pixeles cubiertos."""
        if not Path(config.EXE).is_file():
            self.skipTest("falta el binario de render (cargo build --release --manifest-path crates/pegcraft-render/Cargo.toml)")
        import numpy as np
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            png = V.ver(EJ / "escena.xstage", 1, Path(t) / "o.png")
            with Image.open(png) as im:
                a = np.asarray(im.convert("RGBA"), dtype=np.int16)
        with Image.open(EJ / "esperado_f1.png") as im:
            b = np.asarray(im.convert("RGBA"), dtype=np.int16)
        self.assertEqual(a.shape, b.shape)
        ma, mb = a[..., 3] > 0, b[..., 3] > 0
        self.assertGreater(mb.sum(), 1000)                 # el esperado no es un lienzo vacio
        iou = (ma & mb).sum() / max((ma | mb).sum(), 1)
        self.assertGreaterEqual(iou, 0.99)
        cubiertos = ma | mb
        iguales = (np.abs(a - b).max(axis=-1) <= 1) & cubiertos
        self.assertGreaterEqual(iguales.sum() / cubiertos.sum(), 0.99)


if __name__ == "__main__":
    unittest.main()
