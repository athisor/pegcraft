"""Pruebas minimas de compilar (unittest): ida y vuelta de tensores, clave de cache estable, exactitud de 2 fotogramas de PLANO.
Correr desde .:  python -m unittest tests.test_compilar -v"""
import json, sys, tempfile, unittest, shutil
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pegcraft.compilar import almacen, plano
from pegcraft.config import XSTAGE_PRUEBA


def _escena(f, dx):
    p = lambda i, dib, ox: {"id": f"Top/A/R{i}", "orden": i, "orden_lista": i, "z": 0.1 * i, "razon": "t", "puertos": [i], "capas": ["colour"],
                            "recorte": [{"nodo": "C", "invertido": False, "mattes": [{"id": "Top/A/M", "dibujo": "dibujos/m.svg", "matriz_campo": [[1, 0, dx], [0, 1, 0]], "capas": ["colour"]}]}] if i == 1 else [],
                            "dibujo": f"dibujos/{dib}.svg", "matriz_campo": [[1.0000001 + i, 0.25, ox + dx], [0.0, 1.0 / 3, 2.5]], "opacidad": 0.5 if i == 1 else 1.0, "avisos": []}
    return {"version": 2, "escena": "x", "fotograma": f, "camara": {"cx": 1}, "tamano": [1920, 1080], "avisos": ["a"], "apilado": {"k": f},
            "piezas": [p(0, "a", 1.5), p(1, "b", 2.5)]}


class TestTensores(unittest.TestCase):
    def test_ida_y_vuelta(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            almacen.RAIZ_ALMACEN = tmp / "alm"; almacen.RAIZ_ALMACEN.mkdir()
            for k in ("ka", "kb", "km"):
                (almacen.RAIZ_ALMACEN / f"{k}.svg").write_text("<svg/>")
            J = {f: _escena(f, 0.1 * f) for f in (5, 6, 7)}
            reg = {"a.svg": {"clave": "ka", "base": "ka", "tvg": None}, "b.svg": {"clave": "kb", "base": "kb", "tvg": None}, "m.svg": {"clave": "km", "base": "km", "tvg": None}}
            plano.escribir(tmp / "p", r"C:\x\esc.xstage", [5, 6, 7], J, {f: reg for f in J})
            P = plano.Plano(tmp / "p")
            for f in J:
                d = P.cuadro(f)
                for a, b in zip(d["piezas"], J[f]["piezas"]):
                    self.assertEqual(a["matriz_campo"], b["matriz_campo"])      # exacto en f64
                    self.assertEqual(a["opacidad"], b["opacidad"]); self.assertEqual(a["z"], b["z"]); self.assertEqual(a["id"], b["id"])
                    self.assertTrue(Path(a["dibujo"]).is_file())
                self.assertEqual(d["apilado"], J[f]["apilado"])
            P32 = plano.Plano(tmp / "p", exacto=False)
            m = P32.cuadro(6)["piezas"][0]["matriz_campo"][0][0]
            self.assertAlmostEqual(m, J[6]["piezas"][0]["matriz_campo"][0][0], places=5)      # el baked F32 pierde ~1e-7
            self.assertEqual(sorted(P.T["baked"].shape), sorted((3, 2 * plano.BK)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestMezcla(unittest.TestCase):
    def test_mezcla_sobrevive_al_plano(self):
        """FASE 0 (12-11-2026): hornear marca mezcla='suma' (GLOW); el plano la perdia. Ahora ida y vuelta, y las piezas sin mezcla no la ganan."""
        tmp = Path(tempfile.mkdtemp())
        try:
            almacen.RAIZ_ALMACEN = tmp / "alm"; almacen.RAIZ_ALMACEN.mkdir()
            for k in ("ka", "kb", "km"):
                (almacen.RAIZ_ALMACEN / f"{k}.svg").write_text("<svg/>")
            J = {f: _escena(f, 0.1 * f) for f in (5, 6)}
            J[5]["piezas"][1]["mezcla"] = "suma"            # pieza 1 con GLOW solo en el cuadro 5
            reg = {"a.svg": {"clave": "ka", "base": "ka", "tvg": None}, "b.svg": {"clave": "kb", "base": "kb", "tvg": None}, "m.svg": {"clave": "km", "base": "km", "tvg": None}}
            plano.escribir(tmp / "p", r"C:\x\esc.xstage", [5, 6], J, {f: reg for f in J}, residual=False)
            P = plano.Plano(tmp / "p")
            self.assertEqual([p.get("mezcla") for p in P.cuadro(5)["piezas"]], [None, "suma"])
            self.assertEqual([p.get("mezcla") for p in P.cuadro(6)["piezas"]], [None, None])
            self.assertNotIn("mezcla", P.cuadro(6)["piezas"][1])      # ausente, no null: el crate distingue «sin campo»
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestClave(unittest.TestCase):
    def test_estable_y_sensible(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "elements" / "E").mkdir(parents=True); (tmp / "palette-library").mkdir()
            tvg = tmp / "elements" / "E" / "E-1.tvg"; tvg.write_bytes(b"abc")
            (tmp / "palette-library" / "p.plt").write_bytes(b"1")
            k1 = almacen.clave_base(tvg, tmp)
            self.assertEqual(k1, almacen.clave_base(tvg, tmp))                       # estable
            self.assertNotEqual(k1, almacen.clave_base(tvg, tmp, gradientes=False))   # depende del flag
            almacen._memo.clear(); (tmp / "palette-library" / "p.plt").write_bytes(b"2")
            self.assertNotEqual(k1, almacen.clave_base(tvg, tmp))                    # cambia con la paleta
            almacen._memo.clear(); tvg.write_bytes(b"abd")
            self.assertNotEqual(k1, almacen.clave_base(tvg, tmp))                    # cambia con el .tvg
            self.assertNotEqual(almacen.clave_deformado("k", [{"a": 1}], 1.3, 155.0), almacen.clave_deformado("k", [{"a": 2}], 1.3, 155.0))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(Path(XSTAGE_PRUEBA).is_file(), "falta PEGCRAFT_XSTAGE_PRUEBA")
class TestExactitud(unittest.TestCase):
    def test_dos_fotogramas_0530(self):
        from pegcraft.compilar import cli as KC
        from pegcraft.bake.hornear import hornear
        tmp = Path(tempfile.mkdtemp())
        try:
            KC.compilar(str(XSTAGE_PRUEBA), [22, 23], str(tmp / "p"))
            P = plano.Plano(tmp / "p")
            for f in (22, 23):
                rj, _ = hornear(str(XSTAGE_PRUEBA), f, str(tmp / f"h{f}"))
                A = json.load(open(rj, encoding="utf-8")); B = P.cuadro(f)
                self.assertEqual(len(A["piezas"]), len(B["piezas"]))
                for a, b in zip(A["piezas"], B["piezas"]):
                    self.assertEqual((a["id"], a["orden"], a["z"], a["opacidad"], a["matriz_campo"], a.get("recorte", [])[:0]),
                                     (b["id"], b["orden"], b["z"], b["opacidad"], b["matriz_campo"], b.get("recorte", [])[:0]))
                    self.assertEqual(Path(b["dibujo"]).read_bytes(), (tmp / f"h{f}" / a["dibujo"]).read_bytes())    # mismo SVG
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
