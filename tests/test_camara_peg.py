"""PEG de camara (12-11-2026): bake/matriz_causal.camara_peg. Sintetico (X y E falsos) + copia real de PLANO si existe.
python -m unittest discover -s tests -p test_camara_peg.py"""
import os, sys, glob, unittest
from types import SimpleNamespace
from unittest import mock
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pegcraft.bake import matriz_causal as mc, apilado
from pegcraft.compilar import avisos


class _XFalso:
    """Imita las funciones de xstage/api.py que usa camara_peg."""
    def __init__(self, nombre_peg="Top/Cam-Raro", fila=None, offset_z=12.0, cuelga=(), tipo_fuente="PEG", offset_x=0.0, offset_y=0.0):
        self.n, self.fila, self.oz, self.cuelga, self.tf = nombre_peg, fila or {}, offset_z, cuelga, tipo_fuente
        self.ox, self.oy = offset_x, offset_y

    def nodo_buscar(self, xs, **kw):
        return {"nodos": [{"ruta": "Top/Camera", "tipo": "CAMERA", "entradas": [f"0<-{self.n}:0"]}]}

    def nodo_vecinos(self, xs, nodo, **kw):
        if nodo == "Top/Camera":
            return {"vecinos": [{"ruta": self.n, "tipo": self.tf}]}
        return {"vecinos": [{"ruta": c, "tipo": "PEG"} for c in self.cuelga]}

    def peg_volcar(self, xs, peg, desde, hasta, max):
        b = {"f": desde, "posicion.x": 0.0, "posicion.y": 0.0, "posicion.z": 0.0, "escala.x": 1.0, "escala.y": 1.0, "rotacion": 0.0}
        b.update(self.fila)
        return {"filas": [b]}

    def nodo_atributo(self, xs, nodo, atributo, fotograma):
        if atributo == "offset.x":
            return {"valor_en_fotograma": str(self.ox)}
        if atributo == "offset.y":
            return {"valor_en_fotograma": str(self.oy)}
        if self.oz is None:
            raise SystemExit("sin offset.z")
        return {"valor_en_fotograma": str(self.oz)}


def _mods_falso(uy="24"):
    doc = SimpleNamespace(root=SimpleNamespace(find=lambda p: SimpleNamespace(get=lambda k: {"numberOfUnitsY": uy, "unitAspectRatioX": "4", "unitAspectRatioY": "3"}.get(k))))
    E = SimpleNamespace(abrir=lambda x: doc, xstage_de=lambda x: x)
    return lambda: (None, E)


def _llamar(x, uy="24", **kw):
    av = []
    with mock.patch.object(apilado, "X", x), mock.patch.object(mc, "_mods", _mods_falso(uy)):
        return mc.camara_peg("falso.xstage", 1, av, **kw), av


class TestCamaraPegSintetico(unittest.TestCase):
    def setUp(self):
        os.environ.pop("PEGCRAFT_CAMARA_PEG", None)

    def test_identidad_es_none(self):
        r, av = _llamar(_XFalso())
        self.assertIsNone(r); self.assertEqual(av, [])

    def test_por_tipo_no_por_nombre(self):
        r, av = _llamar(_XFalso("Top/Otro-Nombre", {"posicion.z": -8.0, "posicion.x": -6.0, "posicion.y": 1.0}))
        self.assertEqual(r["ruta"], "Top/Otro-Nombre"); self.assertEqual((r["x"], r["y"], r["z"]), (-6.0, 1.0, -8.0))
        self.assertAlmostEqual(r["d"], 12.0); self.assertAlmostEqual(r["A"], 4 / 3); self.assertEqual(av, [])

    def test_fuente_no_peg(self):
        r, av = _llamar(_XFalso(tipo_fuente="COMPOSITE"))
        self.assertIsNone(r); self.assertTrue(any("no de un PEG" in a for a in av))

    def test_rotacion_avisa(self):
        r, av = _llamar(_XFalso(fila={"escala.x": 0.88, "escala.y": 0.88, "rotacion": 5.0}))
        self.assertEqual(r["rot"], 5.0); self.assertTrue(any("NO se aplica" in a for a in av))

    def test_offset_distinto_avisa_reencuadre_y_usa_offset(self):
        r, av = _llamar(_XFalso(fila={"posicion.z": -3.0}, offset_z=10.0))
        self.assertEqual(r["d"], 10.0); self.assertEqual(r["d0"], 12.0)
        self.assertTrue(any("zoom de reencuadre asumido" in a for a in av))

    def test_reencuadre_con_peg_identidad_devuelve_dict(self):
        # PLANO: offset.z=9,39 con PEG identidad -> zoom 12/9,39 en z=0 (antes: None, sin zoom)
        r, av = _llamar(_XFalso(offset_z=9.392438855))
        self.assertIsNotNone(r); self.assertAlmostEqual(mc.escala_camara(r, 0.0), 12 / 9.392438855, places=6)
        self.assertAlmostEqual(mc.escala_camara(r, 0.0), 1.2776, places=3)
        self.assertEqual(sum("reencuadre" in a for a in av), 1)
        self.assertEqual(avisos.codigo(av[0]), "CAMARA_ZOOM_REENCUADRE")

    def test_offset_igual_a_unidades_sin_cambio(self):
        # 12 = 12 (banco y camara EPISODIO): identidad -> None y sin aviso; no identidad -> formula de siempre d/(d+cz-z)/cs
        r, av = _llamar(_XFalso(offset_z=12.0)); self.assertIsNone(r); self.assertEqual(av, [])
        r, av = _llamar(_XFalso(fila={"posicion.z": -8.085, "escala.x": 0.9, "escala.y": 0.9}, offset_z=12.0))
        self.assertEqual(av, []); self.assertEqual(r["d0"], r["d"])
        self.assertAlmostEqual(mc.escala_camara(r, 1.5), 12 / (12 - 8.085 - 1.5) / 0.9, places=9)

    def test_escala_camara_forzada_como_antes(self):
        r, _ = _llamar(_XFalso(fila={"posicion.z": -3.0}, offset_z=10.0))
        self.assertAlmostEqual(mc.escala_camara(r, 0.0, 12.0), 12 / (12 - 3.0))   # PEGCRAFT_PERSP_D fuerza d y d0
        self.assertAlmostEqual(mc.escala_camara(r, 0.0, 0.0), 1.0)                 # 0 = sin perspectiva

    def test_sin_offset_usa_unidades(self):
        r, av = _llamar(_XFalso(fila={"posicion.z": -3.0}, offset_z=None), uy="20")
        self.assertEqual(r["d"], 10.0); self.assertTrue(any("sin offset.z" in a for a in av))

    def test_cuelga_de_otro_peg_avisa(self):
        r, av = _llamar(_XFalso(fila={"escala.x": 0.9, "escala.y": 0.9}, cuelga=("Top/Padre",)))
        self.assertTrue(any("cuelga" in a for a in av))

    def test_apagado_por_entorno(self):
        os.environ["PEGCRAFT_CAMARA_PEG"] = "no"
        try:
            r, av = _llamar(_XFalso(fila={"posicion.z": -3.0}))
        finally:
            os.environ.pop("PEGCRAFT_CAMARA_PEG", None)
        self.assertIsNone(r)

    def test_offset_xy_cero_no_cambia_nada(self):
        # ox=oy=0 (todo el banco y EPISODIO): identidad -> None; no identidad -> sin aviso de offset y centro = (A*x, y) como antes
        r, av = _llamar(_XFalso()); self.assertIsNone(r); self.assertEqual(av, [])
        r, av = _llamar(_XFalso(fila={"posicion.x": -6.0, "posicion.y": 1.0, "posicion.z": -3.0}))
        self.assertEqual(av, [])
        cx, cy = mc.centro_camara(r)
        self.assertAlmostEqual(cx, 4 / 3 * -6.0); self.assertAlmostEqual(cy, 1.0)

    def test_offset_xy_con_peg_identidad_devuelve_dict_y_avisa(self):
        # PLANO: PEG identidad pero offset.x/y != 0 -> centro = (A*cs*ox, cs*oy)
        r, av = _llamar(_XFalso(offset_x=-1.1657, offset_y=-0.2220, offset_z=12.0))
        self.assertIsNotNone(r); self.assertEqual((r["ox"], r["oy"]), (-1.1657, -0.2220))
        cx, cy = mc.centro_camara(r)
        self.assertAlmostEqual(cx, 4 / 3 * -1.1657); self.assertAlmostEqual(cy, -0.2220)
        self.assertEqual(sum("offset.x/y" in a for a in av), 1)
        self.assertEqual(avisos.codigo(av[0]), "CAMARA_OFFSET_XY")

    def test_offset_xy_se_multiplica_por_escala_de_camara(self):
        # PLANO: cs = 0,9417 -> x += cs*ox, y += cs*oy ; la traslacion final (t - c) se escala luego con escala_camara
        r, av = _llamar(_XFalso(fila={"posicion.x": 0.5, "posicion.y": 0.1, "posicion.z": 0.165, "escala.x": 0.9417, "escala.y": 0.9417},
                                offset_x=5.3596, offset_y=1.3125, offset_z=8.4308))
        cx, cy = mc.centro_camara(r)
        self.assertAlmostEqual(cx, 4 / 3 * (0.5 + 0.9417 * 5.3596)); self.assertAlmostEqual(cy, 0.1 + 0.9417 * 1.3125)
        self.assertTrue(any("CAMARA_OFFSET_XY" == avisos.codigo(a) for a in av))

    def test_offset_xy_apagado_por_entorno(self):
        os.environ["PEGCRAFT_CAMARA_OFFSET"] = "no"
        try:
            r, av = _llamar(_XFalso(offset_x=2.0, offset_y=1.0))
            r2, av2 = _llamar(_XFalso(fila={"posicion.x": -6.0}, offset_x=2.0, offset_y=1.0))
        finally:
            os.environ.pop("PEGCRAFT_CAMARA_OFFSET", None)
        self.assertIsNone(r); self.assertEqual(av, [])
        self.assertEqual((r2["ox"], r2["oy"]), (0.0, 0.0)); self.assertAlmostEqual(mc.centro_camara(r2)[0], 4 / 3 * -6.0)

    def test_offset_xy_apagado_por_camara_peg(self):
        os.environ["PEGCRAFT_CAMARA_PEG"] = "no"
        try:
            r, av = _llamar(_XFalso(offset_x=2.0, offset_y=1.0))
        finally:
            os.environ.pop("PEGCRAFT_CAMARA_PEG", None)
        self.assertIsNone(r)

    def test_formula_zoom(self):
        # s = d/(d+cz-z)/cs ; PLANO: d=12, cz=-8.085 -> 3.0655 (medido 3,065)
        self.assertAlmostEqual(12 / (12 - 8.08505), 3.0652, places=3)


_COPIA = glob.glob(r"<datos de trabajo omitidos>")


@unittest.skipUnless(_COPIA, "sin la copia de PLANO")
class TestCamaraPeg0560(unittest.TestCase):
    def test_real(self):
        os.environ.pop("PEGCRAFT_CAMARA_PEG", None)
        av = []
        r = mc.camara_peg(_COPIA[0], 34, av)
        self.assertEqual(r["ruta"], "Top/Camera-P")
        self.assertAlmostEqual(r["z"], -8.085, places=2); self.assertAlmostEqual(r["x"], -6.119, places=2)
        self.assertEqual(r["escala"], 1.0); self.assertEqual(r["d"], 12.0); self.assertEqual(av, [])
        self.assertAlmostEqual(r["d"] / (r["d"] + r["z"]), 3.065, places=2)

    def test_real_apagado(self):
        os.environ["PEGCRAFT_CAMARA_PEG"] = "no"
        try:
            self.assertIsNone(mc.camara_peg(_COPIA[0], 34, []))
        finally:
            os.environ.pop("PEGCRAFT_CAMARA_PEG", None)


if __name__ == "__main__":
    unittest.main()
