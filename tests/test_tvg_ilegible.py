"""TVG_ILEGIBLE (12-11-2026): el lector .tvg (sightread.tvg) lanza TvgIlegible; el horneado omite la pieza y avisa, no aborta el cuadro.
Sintetico (conversor falso).
python -m unittest discover -s tests -p test_tvg_ilegible.py"""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pegcraft.bake import hornear as H
from pegcraft.compilar import avisos


class TestConvertirTvg(unittest.TestCase):
    """`convertir_tvg(tvg, esc, svg, gradientes)` -> (error, info); el conversor es `bake.gradientes.convertir` sobre `sightread.tvg` (se reemplaza por uno falso)."""

    def _con(self, falso):
        return mock.patch("pegcraft.bake.gradientes.convertir", falso)

    def test_tvg_ilegible_se_atrapa_y_se_describe(self):
        from sightread.tvg import TvgIlegible

        def malo(tvg, escena, salida, con_gradientes=True):
            Path(salida).write_text("<svg/>")   # un SVG a medias no debe quedar
            raise TvgIlegible("forma F=6 en 765271")
        with tempfile.TemporaryDirectory() as d, self._con(malo):
            svg = Path(d) / "X-1.svg"
            err, info = H.convertir_tvg(Path(d) / "X-1.tvg", "e", svg)
            self.assertIn("TvgIlegible", err); self.assertIn("forma F=6", err); self.assertIsNone(info); self.assertFalse(svg.exists())

    def test_excepcion_del_conversor(self):
        def malo(tvg, escena, salida, con_gradientes=True):
            raise ValueError("raro")
        with tempfile.TemporaryDirectory() as d, self._con(malo):
            err, _ = H.convertir_tvg(Path(d) / "a.tvg", "e", Path(d) / "a.svg", gradientes=False)
            self.assertTrue(err.startswith("ValueError"))

    def test_falla_solo_gradientes_reintenta_sin_ellos(self):
        llamadas = []

        def f(tvg, escena, salida, con_gradientes=True):
            llamadas.append(con_gradientes)
            if con_gradientes:
                raise ValueError("gradiente roto")
            Path(salida).write_text("<svg/>")
            return {"gradientes": [], "avisos": []}
        with tempfile.TemporaryDirectory() as d, self._con(f):
            err, info = H.convertir_tvg(Path(d) / "a.tvg", "e", Path(d) / "a.svg")
            self.assertIsNone(err); self.assertEqual(llamadas, [True, False]); self.assertIn("gradientes a.svg", info["avisos"][0])

    def test_ok_devuelve_none(self):
        with tempfile.TemporaryDirectory() as d, self._con(lambda tvg, escena, salida, con_gradientes=True: {"gradientes": [], "avisos": []}):
            err, info = H.convertir_tvg(Path(d) / "a.tvg", "e", Path(d) / "a.svg")
            self.assertIsNone(err); self.assertEqual(info["gradientes"], [])

    def test_codigo_del_aviso(self):
        self.assertEqual(avisos.codigo("TVG_ILEGIBLE pieza-1.tvg (Top/Fondo/Pieza): TvgIlegible: x; pieza omitida"), "TVG_ILEGIBLE")



if __name__ == "__main__":
    unittest.main()
