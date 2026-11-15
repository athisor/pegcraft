"""Subcomando `ver` y portabilidad del nombre del ejecutable."""
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pegcraft import config, ver as V
from pegcraft.medir import render as R


class TestVer(unittest.TestCase):
    def test_nombre_exe_segun_plataforma(self):
        self.assertEqual(config.NOMBRE_EXE.endswith(".exe"), sys.platform == "win32")
        self.assertTrue(config.NOMBRE_EXE.startswith("pegcraft-render"))

    def test_aviso_sin_offline(self):
        self.assertNotIn("--offline", R.AVISO_SIN_BINARIO)
        self.assertIn("--manifest-path crates/pegcraft-render/Cargo.toml", R.AVISO_SIN_BINARIO)

    def test_falta_binario_mensaje_claro(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(config, "EXE", Path(t) / "no_existe"):
            with self.assertRaises(SystemExit) as cm:
                V.ver(Path(t) / "e.xstage", 1, Path(t) / "o.png")
        self.assertIn("cargo build --release --manifest-path", str(cm.exception))

    def test_hornea_a_temporal_y_renderiza(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            exe = t / "fake"; exe.write_bytes(b"")
            xs = t / "e.xstage"; xs.write_text("<x/>")
            vistos = {}

            def hornea(x, f, salida, **kw):
                vistos["salida"] = Path(salida)
                (Path(salida) / "escena.json").write_text("{}")
                return str(Path(salida) / "escena.json"), {"avisos": 0}

            def dibuja(js, png, bg, extra):
                vistos["json"] = js
                return str(png)

            with mock.patch.object(config, "EXE", exe), mock.patch("pegcraft.bake.hornear.hornear", hornea), mock.patch.object(R, "renderizar", dibuja):
                out = V.ver(xs, 3, t / "sub" / "o.png")
            self.assertEqual(out, str(t / "sub" / "o.png"))
            self.assertFalse(vistos["salida"].exists())          # la carpeta temporal se borra

    def test_pyproject(self):
        d = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(d["project"]["scripts"]["pegcraft"], "pegcraft.__main__:main")
        self.assertEqual(sorted(x.lower() for x in d["project"]["dependencies"]), ["numpy", "pillow"])


if __name__ == "__main__":
    unittest.main()
