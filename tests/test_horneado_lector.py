"""Camino de horneado SIN el conversor .tvg, sobre los casos sinteticos de tests/fixtures/lector/casos (A7): apilado, matriz causal,
censo de deformadores, fotogramas clave y un `hornear` completo con el conversor sustituido por un SVG vacio.

Comprueba contra los valores esperados de cada caso (esperado.json): Z, cadena de transformadores y matriz (cuando no tiene traslacion).
    python -I -m unittest discover -s tests -p test_horneado_lector.py
"""
import json, os, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lector"))   # constructor de escenas sinteticas (A5)
from pegcraft.bake import apilado, censo, hornear as H, matriz_causal as mc
from pegcraft.compilar import almacen
from pegcraft.keyframes import keyframes
from pegcraft.lector import compat as L
from test_evaluar_ayuda import Escenas, cable, grupo, modulo, peg, read, xstage

ESC = Escenas()


def tearDownModule():
    ESC.cerrar()

CASOS = Path(__file__).resolve().parent / "fixtures" / "lector" / "casos"
NOMBRES = sorted(p.name[:-len(".xstage")] for p in CASOS.glob("*.xstage"))
TOL = 1e-6
# c09 f=11: el esperado de A7 ("constante entre dos llaves iguales") discrepa de la regla de velocity del lector; se mide en Harmony aparte.
DISCUTIDOS = {("c09_puntos_coincidentes", 11)}


def esperado(nombre):
    return json.loads((CASOS / f"{nombre}.esperado.json").read_text(encoding="utf-8"))


def hay_raiz(xs):
    try:
        apilado.orden_apilado_conectores(str(xs), 1)
        return True
    except SystemExit:
        return False


def lecturas(e, f):
    """{ruta: fila esperada} de los READ del fotograma f."""
    return {r: v for r, v in e["evaluacion"][str(f)].items() if v["tipo"] == "READ"}


class Apilado(unittest.TestCase):
    def test_z_y_ids_de_cada_caso(self):
        """Los READ que llegan al composite raiz salen con la Z esperada y solo si tienen dibujo y no estan apagados."""
        vistos = 0
        for nombre in NOMBRES:
            xs = CASOS / f"{nombre}.xstage"
            if not hay_raiz(xs):
                continue
            e = esperado(nombre)
            for f in map(int, e["evaluacion"]):
                if (nombre, f) in DISCUTIDOS:
                    continue
                r = apilado.orden_apilado_conectores(str(xs), f)
                esp = lecturas(e, f)
                for fila in r["orden"]:
                    self.assertIn(fila["id"], esp, f"{nombre} f{f}")
                    self.assertFalse(esp[fila["id"]]["apagado"], f"{nombre} f{f} {fila['id']}")
                    if esp[fila["id"]]["z"] is not None:   # los esperados sin Z calculable (null) no se comparan (ADR-0008)
                        self.assertAlmostEqual(fila["z"], esp[fila["id"]]["z"], delta=TOL, msg=f"{nombre} f{f} {fila['id']}")
                    vistos += 1
        self.assertGreater(vistos, 10)

    def test_composites_anidados_orden_por_puerto(self):
        """c06: Fondo en el puerto 0; el grupo entrega P1+P2 (composite interior) en el 1 y P3 en el 2: atras -> adelante."""
        xs = CASOS / "c06_composites_anidados.xstage"
        for fn in (apilado.orden_apilado, apilado.orden_apilado_conectores):
            r = fn(str(xs), 1)
            self.assertEqual(r["raiz"], "Top/Composite_Top")
            self.assertEqual([o["id"].split("/")[-1] for o in r["orden"]], ["Dibujo_Fondo", "Dibujo_P1", "Dibujo_P2", "Dibujo_P3"])
            self.assertEqual(r["orden"][0]["puertos"], [0])      # el fondo cuelga del puerto 0 del composite raiz

    def test_salida_de_grupo_por_tipo(self):
        """El grupo se cruza por su nodo MULTIPORT_OUT aunque no se llame `Multi-Port-Out` (antes lo parchaba bake/puerto_grupo.py):
        el READ de dentro llega al apilado y su matriz lleva el PEG de fuera (x = A * 3 = 4 en la matriz causal isotropa)."""
        g = grupo("G", [modulo("MULTIPORT_IN", "In"), read("Hoja"), modulo("MULTIPORT_OUT", "sin-nombre")], cable("In", "Hoja") + cable("Hoja", "sin-nombre"))
        nodos = [peg("P1", pos=(3, 0, 0)), g, modulo("COMPOSITE", "Comp"), modulo("DISPLAY", "Pant")]
        ruta = str(ESC.abrir_xml(xstage(nodos, cable("P1", "G") + cable("G", "Comp") + cable("Comp", "Pant"))).ruta)
        for fn in (apilado.orden_apilado, apilado.orden_apilado_conectores):
            self.assertEqual([o["id"] for o in fn(ruta, 1)["orden"]], ["Top/G/Hoja"])
        self.assertAlmostEqual(mc.matrices(ruta, 1, ["Top/G/Hoja"], [])["Top/G/Hoja"][0][2], 4.0)

    def test_grupos_de_los_casos(self):
        """c04: el apilado de un caso con grupo y MULTIPORT trae los READ de dentro."""
        xs = CASOS / "c04_grupo_multiport.xstage"
        self.assertTrue(hay_raiz(xs))
        r = apilado.orden_apilado_conectores(str(xs), 1)
        self.assertTrue(any(o["id"].count("/") >= 2 for o in r["orden"]), r["orden"])

    def test_empate_de_z_manda_el_puerto(self):
        """Dos Z a menos de TOL_Z son la misma Z; a mas, manda la Z."""
        g = apilado.grupos_z([0.0, 5e-6, 1e-4, -2e-3], tol=6e-6)
        self.assertEqual(g[0.0], g[5e-6])
        self.assertLess(g[-2e-3], g[0.0])
        self.assertLess(g[5e-6], g[1e-4])
        g0 = apilado.grupos_z([0.0, 5e-6], tol=0.0)
        self.assertNotEqual(g0[0.0], g0[5e-6])


class MatrizCausal(unittest.TestCase):
    def test_matriz_sin_traslacion_igual_a_la_esperada(self):
        """Sin traslacion ni pivote la matriz causal (isotropa) y la del lector (campos) tienen la misma parte lineal."""
        n = 0
        for nombre in NOMBRES:
            xs = CASOS / f"{nombre}.xstage"
            e = esperado(nombre)
            for f in map(int, e["evaluacion"]):
                if (nombre, f) in DISCUTIDOS:
                    continue
                esp = {r: v for r, v in lecturas(e, f).items() if v["matriz"] is not None and not v["cortada"]}
                if not esp or any(abs(v["canales"].get("sesgo", 0.0) or 0.0) > 1e-9 for v in e["evaluacion"][str(f)].values()):
                    continue      # con sesgo la matriz causal de pegcraft lo aplica (K = tan, SIGNO_SESGO) y la del lector lo ignora (R4)
                m = mc.matrices(str(xs), f, list(esp), [])
                for r, v in esp.items():
                    if any(abs(x) > 1e-12 for x in (v["matriz"][0][2], v["matriz"][1][2])):
                        continue
                    for i in range(2):
                        for j in range(2):
                            self.assertAlmostEqual(m[r][i][j], v["matriz"][i][j], delta=1e-5, msg=f"{nombre} f{f} {r}")
                    n += 1
        self.assertGreater(n, 10)

    def test_camara_por_omision(self):
        """1080/24 = 45 px por campo-Y; div = 45 / pixelPerModelUnitForVectorLayers."""
        c = mc.camara(str(CASOS / "c02_read_peg_estatico.xstage"))
        self.assertAlmostEqual(c["sx"], 45.0); self.assertAlmostEqual(c["sy"], 45.0)
        self.assertAlmostEqual(c["div"], 45.0 / 0.288, places=6)

    def test_aspecto(self):
        self.assertAlmostEqual(mc.aspecto(L.escena(str(CASOS / "c02_read_peg_estatico.xstage"))), 4.0 / 3.0)

    def test_sin_camara_peg_identidad(self):
        """Los casos no tienen CAMERA: camara_peg devuelve None sin avisos."""
        av = []
        self.assertIsNone(mc.camara_peg(str(CASOS / "c03_cadena_dos_peg.xstage"), 1, av))
        self.assertEqual(av, [])


class Censo(unittest.TestCase):
    def test_cadena_de_peg_igual_a_la_esperada(self):
        n = 0
        for nombre in NOMBRES:
            xs = CASOS / f"{nombre}.xstage"
            e = esperado(nombre)
            f = int(sorted(e["evaluacion"], key=int)[0])
            cen = censo.censo(str(xs), f)
            for ruta, v in lecturas(e, f).items():
                cad = [c["ruta"] for c in cen.get(ruta, []) if c["tipo"] == "PEG"]
                esp = [r for r in v["cadena"] if r != ruta]       # el esperado de A7 incluye al READ si tiene transformacion propia
                self.assertEqual(cad, esp, f"{nombre} {ruta}")
                n += 1
        self.assertGreater(n, 10)


class Keyframes(unittest.TestCase):
    def test_dibujo_fijo_un_solo_cambio(self):
        xs = CASOS / "c02_read_peg_estatico.xstage"
        kf = keyframes(str(xs), 1, 24)
        self.assertEqual(len(kf), 1)
        self.assertEqual(kf[0][0], 1)

    def test_hasta_por_omision_es_nbframes(self):
        xs = CASOS / "c07_columnas_tres_tipos.xstage"
        self.assertEqual(L.n_fotogramas(str(xs)), esperado("c07_columnas_tres_tipos")["escena"]["fotogramas"])
        kf = keyframes(str(xs))
        self.assertEqual(kf[0][0], 1)
        self.assertEqual([f for f, _ in kf], sorted({f for f, _ in kf}))


class HornearSinTvg(unittest.TestCase):
    """`hornear` completo con una copia del caso que lleva .tvg vacios y el conversor reemplazado por un SVG vacio."""

    def _hornear(self, nombre, f, **kw):
        tmp = Path(tempfile.mkdtemp(prefix="hornear_test_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        esc = tmp / "escena"
        (esc / "elements" / "Dibujo_A").mkdir(parents=True)
        for d in ("1", "2"):
            (esc / "elements" / "Dibujo_A" / f"Dibujo_A-{d}.tvg").write_bytes(b"")
        xs = esc / f"{nombre}.xstage"
        shutil.copy(CASOS / f"{nombre}.xstage", xs)

        def falso(tvg, esc_, svg, gradientes=True):
            Path(svg).write_text("<svg/>", encoding="utf-8")
            return None, None
        with mock.patch.object(H, "convertir_tvg", falso), mock.patch.object(almacen, "ACTIVO", False):
            ruta, res = H.hornear(str(xs), f, str(tmp / "sal"), gradientes=False, **kw)
        return json.loads(Path(ruta).read_text(encoding="utf-8")), res

    def test_c06_piezas_en_orden_de_puerto(self):
        j, res = self._hornear("c06_composites_anidados", 1)
        self.assertEqual(j["version"], 2)
        self.assertEqual([p["id"].split("/")[-1] for p in j["piezas"]], ["Dibujo_Fondo", "Dibujo_P1", "Dibujo_P2", "Dibujo_P3"])
        self.assertEqual(j["apilado"]["raiz"], "Top/Composite_Top")
        for p in j["piezas"]:
            self.assertEqual(p["matriz_campo"], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
            self.assertTrue(p["dibujo"].startswith("dibujos/"))
            self.assertEqual(p["opacidad"], 1.0)

    def test_c03_matriz_y_z_de_la_cadena(self):
        e = esperado("c03_cadena_dos_peg")
        f = int(sorted(e["evaluacion"], key=int)[0])
        j, _ = self._hornear("c03_cadena_dos_peg", f)
        esp = lecturas(e, f)
        self.assertEqual(len(j["piezas"]), len([v for v in esp.values() if not v["apagado"]]))
        for p in j["piezas"]:
            self.assertAlmostEqual(p["z"], esp[p["id"]]["z"], delta=TOL)

    def test_sin_tvg_avisa_y_omite(self):
        tmp = Path(tempfile.mkdtemp(prefix="hornear_test_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        xs = tmp / "c02.xstage"
        shutil.copy(CASOS / "c02_read_peg_estatico.xstage", xs)
        with mock.patch.object(almacen, "ACTIVO", False):
            ruta, res = H.hornear(str(xs), 1, str(tmp / "sal"), gradientes=False)
        j = json.loads(Path(ruta).read_text(encoding="utf-8"))
        self.assertEqual(j["piezas"], [])
        self.assertTrue(any(a.startswith("sin tvg") for a in j["avisos"]))


if __name__ == "__main__":
    unittest.main()
