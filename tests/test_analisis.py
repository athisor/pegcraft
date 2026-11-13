"""`python -m pegcraft analizar` y pegcraft.analisis: lo que pegcraft no conoce, sobre escenas sinteticas (nombres inventados).
Los casos raros (tipo de nodo, atributo, columna) se generan EDITANDO el XML de una escena sintetica ya hecha, nunca copiando firmas (ADR-0012).
python -m unittest discover -s tests -p test_analisis.py"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.dont_write_bytecode = True
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "sightread" / "tests" / "lector"))      # constructor de escenas sinteticas
from pegcraft.analisis import CATEGORIAS, lote
from pegcraft.analisis.escena import analizar_escena, elegir_fotogramas, normalizar
from pegcraft.bake import apilado
from test_evaluar_ayuda import cable, modulo, peg, read, xstage

COL_RARAS = ('<column type="77" name="Rara" id="9" /><column type="1" name="Sonido" id="10" />')


def escena_base(raro=False):
    """P1 -> Hoja -> [Mezcla] -> [Inventado] -> Comp -> Pant. Con raro=True se le editan: un nodo de tipo inventado, un BLEND_MODE eMULTIPLY, un atributo con
    valor fuera de defecto que nadie lee en P1 y dos columnas raras."""
    p1 = peg("P1", extra_attrs='<rarezaInventada val="3" defaultValue="0" />' if raro else '<rarezaInventada val="0" defaultValue="0" />')
    nodos, cables = [p1, read("Hoja")], cable("P1", "Hoja")
    ultimo = "Hoja"
    if raro:
        nodos += [modulo("BLEND_MODE_MODULE", "Mezcla", '<blendMode val="eMULTIPLY" />'), modulo("NodoInventadoZZ", "Inv", '<cosa val="1" />')]
        cables += cable("Hoja", "Mezcla") + cable("Mezcla", "Inv")
        ultimo = "Inv"
    nodos += [modulo("COMPOSITE", "Comp"), modulo("DISPLAY", "Pant")]
    cables += cable(ultimo, "Comp") + cable("Comp", "Pant")
    return xstage(nodos, cables, columnas=COL_RARAS if raro else "")


def claves(r, cat):
    return {h["clave"] for h in r["hallazgos"] if h["categoria"] == cat}


class TestEscena(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        (cls.dir / "limpia").mkdir(); (cls.dir / "rara").mkdir(); (cls.dir / "rota").mkdir()
        (cls.dir / "limpia" / "a.xstage").write_text(escena_base(False), encoding="utf-8")
        (cls.dir / "rara" / "b.xstage").write_text(escena_base(True), encoding="utf-8")
        (cls.dir / "rota" / "c.xstage").write_text("esto no es xml <<<", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_escena_limpia_no_tiene_nada_desconocido(self):
        r = analizar_escena(self.dir / "limpia" / "a.xstage")
        cats = {h["categoria"] for h in r["hallazgos"]} - {"dibujo_faltante"}     # el .tvg sintetico no existe en disco
        self.assertEqual(cats, set(), r["hallazgos"])
        self.assertEqual(r["fotogramas"], [1, 12, 24])

    def test_tipo_de_nodo_inventado(self):
        r = analizar_escena(self.dir / "rara" / "b.xstage")
        self.assertIn("NodoInventadoZZ", claves(r, "nodo_tipo_no_soportado"))
        self.assertIn("NodoInventadoZZ tratado como transparente", claves(r, "efecto_no_soportado"))
        self.assertIn("BLEND_MODE_MODULE eMULTIPLY", claves(r, "efecto_no_soportado"))
        h = next(h for h in r["hallazgos"] if h["clave"] == "NodoInventadoZZ")
        self.assertEqual(h["nodos"], ["Top/Inv"])

    def test_atributo_fuera_de_defecto_no_leido(self):
        self.assertIn("PEG.rarezaInventada", claves(analizar_escena(self.dir / "rara" / "b.xstage"), "atributo_no_leido"))
        self.assertNotIn("PEG.rarezaInventada", claves(analizar_escena(self.dir / "limpia" / "a.xstage"), "atributo_no_leido"))   # en su defecto no cuenta

    def test_columnas_opacas(self):
        k = claves(analizar_escena(self.dir / "rara" / "b.xstage"), "columna_opaca")
        self.assertTrue(any(c.startswith("tipo 77") for c in k), k)
        self.assertIn("tipo 1 (sonido)", k)

    def test_dibujo_faltante(self):
        self.assertIn("tvg inexistente en disco", claves(analizar_escena(self.dir / "limpia" / "a.xstage"), "dibujo_faltante"))

    def test_escena_que_revienta_es_un_hallazgo(self):
        r = analizar_escena(self.dir / "rota" / "c.xstage")
        self.assertTrue(claves(r, "error_lectura"), r)
        self.assertTrue(all(c.startswith("abrir:") for c in claves(r, "error_lectura")))

    def test_las_categorias_usadas_estan_declaradas(self):
        for f in ("limpia/a", "rara/b", "rota/c"):
            for h in analizar_escena(self.dir / (f + ".xstage"))["hallazgos"]:
                self.assertIn(h["categoria"], CATEGORIAS)

    def test_no_deja_el_espia_puesto(self):
        from sightread.lector.escena import Escena
        antes = Escena.atributo_elem
        analizar_escena(self.dir / "rara" / "b.xstage")
        self.assertIs(Escena.atributo_elem, antes)

    def test_tipos_modelados_cubre_lo_que_el_horneado_conoce(self):
        for t in list(apilado.FILTRO) + ["READ", "PEG", "COMPOSITE", "GROUP", "CUTTER", "GLOW", "OffsetModule", "CurveModule", "StaticConstraint"]:
            self.assertIn(t, apilado.TIPOS_MODELADOS)
        self.assertNotIn("NodoInventadoZZ", apilado.TIPOS_MODELADOS)

    def test_fotogramas_y_normalizar(self):
        self.assertEqual(elegir_fotogramas(100), [1, 50, 100])
        self.assertEqual(elegir_fotogramas(1), [1])
        self.assertEqual(elegir_fotogramas(10, "3:5"), [3, 4, 5])
        self.assertEqual(elegir_fotogramas(10, "2,9,40"), [2, 9])
        self.assertEqual(normalizar("OffsetModule con restingorientation != 0 en Top/Gr/Of [a, b] 0123456789abcdef"), "OffsetModule con restingorientation != N en <ruta> [...] <id>")


class TestLote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TestEscena.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_descubrir_y_filtrar(self):
        todas = lote.descubrir([self.dir])
        self.assertEqual([p.name for p in todas], ["a.xstage", "b.xstage", "c.xstage"])
        self.assertEqual([p.name for p in lote.filtrar_planos(todas, "rara")], ["b.xstage"])
        lista = self.dir / "lista.txt"
        lista.write_text(str(todas[0]) + "\n", encoding="utf-8")
        self.assertEqual([p.name for p in lote.filtrar_planos(todas, str(lista))], ["a.xstage"])
        with self.assertRaises(FileNotFoundError):
            lote.descubrir([self.dir / "nada"])

    def test_cli_escribe_log_incremental_y_resumen(self):
        base = self.dir / "log" / "prueba"
        r = subprocess.run([sys.executable, "-m", "pegcraft", "analizar", str(self.dir), "--log", str(base)], cwd=RAIZ, capture_output=True, text=True,
                           encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(r.returncode, 0, r.stderr)
        lineas = r.stdout.splitlines()
        self.assertEqual([l.split()[1] for l in lineas if l.startswith("escena ")], ["1/3", "2/3", "3/3"])
        self.assertTrue(lineas[-1].startswith("fin 3 escenas"), lineas[-1])
        ev = [json.loads(l) for l in (base.with_suffix(".jsonl")).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["t"] for e in ev if e["t"] != "hallazgo"], ["inicio", "escena", "escena", "escena", "fin"])
        esc = [e for e in ev if e["t"] == "escena"]
        self.assertEqual(sum(1 for e in esc if e["errores"]), 1)       # la rota no detuvo el lote
        self.assertTrue(all("t_s" in e for e in esc))
        res = json.loads(base.with_suffix(".resumen.json").read_text(encoding="utf-8"))
        self.assertTrue(res["terminado"]); self.assertEqual(res["escenas"], 3)
        self.assertIn("nodo_tipo_no_soportado", res["por_categoria"])
        self.assertIn("NodoInventadoZZ", {h["clave"] for h in res["top"]})
        md = base.with_suffix(".md").read_text(encoding="utf-8")
        self.assertIn("NodoInventadoZZ", md); self.assertNotIn("(parcial)", md)

    def test_planos_limita_las_escenas(self):
        r = subprocess.run([sys.executable, "-m", "pegcraft", "analizar", str(self.dir), "--planos", "rara", "--log", str(self.dir / "l2" / "x")], cwd=RAIZ,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("escena 1/1", r.stdout)

    def test_ruta_inexistente_da_error_claro(self):
        r = subprocess.run([sys.executable, "-m", "pegcraft", "analizar", str(self.dir / "nada"), "--log", str(self.dir / "l3")], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2); self.assertIn("no existe", r.stderr)


SECRETOS = ["MarmotaSecreta", "CajaPrivada", "MezclaOculta", "ColumnaPrivadaX9", "EP99_Privado", "plano_secreto_0420", "plano_roto_0777", "FraseSecretaNoCompartir"]


class TestCompartible(unittest.TestCase):
    """`--compartible`: ni rutas, ni nombres de escena, nodo o columna, ni mensajes de excepcion; si tipos, atributos, conteos y versiones."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name) / "EP99_Privado"
        d.mkdir()
        p = peg("MarmotaSecreta", extra_attrs='<rarezaInventada val="3" defaultValue="0" />')
        nodos = [p, read("CajaPrivada"), modulo("BLEND_MODE_MODULE", "MezclaOculta", '<blendMode val="eMULTIPLY" />'), modulo("NodoInventadoZZ", "OtroNombreSecreto"),
                 modulo("COMPOSITE", "Comp"), modulo("DISPLAY", "Pant")]
        cables = cable("MarmotaSecreta", "CajaPrivada") + cable("CajaPrivada", "MezclaOculta") + cable("MezclaOculta", "OtroNombreSecreto") + cable("OtroNombreSecreto", "Comp") + cable("Comp", "Pant")
        cols = '<column type="77" name="ColumnaPrivadaX9" id="9" />'
        txt = xstage(nodos, cables, columnas=cols).replace("<project>", '<project version="1603" build="14965" creator="harmony">', 1)
        (d / "plano_secreto_0420.xstage").write_text(txt, encoding="utf-8")
        (d / "plano_roto_0777.xstage").write_text("FraseSecretaNoCompartir <<< esto no es xml", encoding="utf-8")
        cls.dir = d
        cls.base = Path(cls.tmp.name) / "log" / "x"
        lote.analizar([d], cls.base, compartible=True, salida=lambda s: None)
        cls.arch = cls.base.with_name("x_compartible.json")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_no_se_cuela_ningun_nombre_ni_ruta(self):
        texto = self.arch.read_text(encoding="utf-8")
        for s in SECRETOS + ["OtroNombreSecreto", str(self.dir), self.tmp.name, "\\\\", ":/", ":\\"]:
            self.assertNotIn(s, texto, s)
        self.assertNotIn(".xstage", texto)

    def test_el_privado_si_los_tiene(self):          # la prueba anterior no es vacua: el log completo lleva los nombres
        self.assertIn("MarmotaSecreta", self.base.with_suffix(".jsonl").read_text(encoding="utf-8"))

    def test_contenido(self):
        j = json.loads(self.arch.read_text(encoding="utf-8"))
        self.assertEqual(j["formato"], "pegcraft-compartible-1")
        import pegcraft
        self.assertEqual(j["pegcraft"], pegcraft.__version__); self.assertTrue(j["sightread"])
        self.assertEqual(j["harmony"], {"1603 build 14965": 1})
        self.assertEqual((j["escenas"], j["escenas_con_hallazgos"]), (2, 2))
        self.assertEqual({k for h in j["hallazgos"] for k in h}, {"categoria", "clave", "n", "escenas"})
        por = {(h["categoria"], h["clave"]): h for h in j["hallazgos"]}
        self.assertEqual(por[("nodo_tipo_no_soportado", "NodoInventadoZZ")]["escenas"], 1)
        self.assertIn(("efecto_no_soportado", "BLEND_MODE_MODULE eMULTIPLY"), por)
        self.assertIn(("atributo_no_leido", "PEG.rarezaInventada"), por)
        self.assertTrue(any(c == "columna_opaca" and k.startswith("tipo 77") for c, k in por))
        self.assertIn(("error_lectura", "abrir: ValueError"), por)         # el tipo de la excepcion si; el mensaje no
        self.assertFalse(self.base.with_name("x_compartible.json.parcial").exists())

    def test_depurar_quita_nombres_y_comillas(self):
        from pegcraft.analisis.compartible import depurar
        self.assertEqual(depurar("columna_aviso", "valor no numerico en 'texto raro' de Zorro3", ["Zorro3"]), "valor no numerico en <texto> de <nombre>")
        self.assertEqual(depurar("nodo_tipo_no_soportado", "COMPOSITE", ["COMPOSITE"]), "COMPOSITE")      # un tipo conocido no se toca aunque coincida con un nombre
        self.assertEqual(depurar("tvg_no_reconocido", "leyendo F:\\datos\\x.tvg", []), "leyendo <ruta>datos\\x.tvg")  # publicar: permitir (ruta falsa de prueba)


class TestVerificar(unittest.TestCase):
    """`analizar --verificar`: un archivo bueno pasa; uno contaminado falla diciendo campo y motivo, sin repetir el texto hallado."""

    @classmethod
    def setUpClass(cls):
        TestCompartible.setUpClass.__func__(cls)
        cls.bueno = json.loads(cls.arch.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _con(self, mutar):
        j = json.loads(json.dumps(self.bueno))
        mutar(j)
        p = Path(self.tmp.name) / "m.json"
        p.write_text(json.dumps(j), encoding="utf-8")
        return p

    def _motivos(self, p, **kw):
        from pegcraft.analisis.verificar import verificar
        return verificar(p, **kw)

    def test_archivo_bueno_pasa(self):
        self.assertEqual(self._motivos(self.arch), [])
        self.assertEqual(self._motivos(self.arch, escenas=self.dir), [])         # tampoco coincide con ningun nombre de la carpeta

    def test_contaminados(self):
        casos = {
            "unidad": lambda j: j["hallazgos"][0].update(clave="falla en C:\\Datos\\plano.tvg"),  # publicar: permitir (ruta falsa de prueba)
            "unc": lambda j: j["hallazgos"][0].update(clave="falla en \\\\servidor\\x"),  # publicar: permitir (ruta falsa de prueba)
            "home": lambda j: j["hallazgos"][0].update(clave="falla en /home/maria/x", categoria="aviso_otro"),  # publicar: permitir (ruta falsa de prueba)
            "barra": lambda j: j["hallazgos"][0].update(clave="a/b", categoria="aviso_otro"),
            "url": lambda j: j["hallazgos"][0].update(clave="ver https://ejemplo.org/x", categoria="aviso_otro"),
            "correo": lambda j: j["hallazgos"][0].update(clave="de maria@ejemplo.org", categoria="aviso_otro"),  # publicar: permitir (correo falso de prueba)
            "largo": lambda j: j["hallazgos"][0].update(clave="palabra " * 30, categoria="aviso_otro"),
            "vocabulario": lambda j: j["hallazgos"][0].update(clave="con espacios y ñ", categoria="nodo_tipo_no_soportado"),
            "categoria": lambda j: j["hallazgos"][0].update(categoria="inventada"),
            "campo_extra": lambda j: j["hallazgos"][0].update(ejemplo="algo"),
            "raiz_extra": lambda j: j.update(escena="x"),
            "harmony": lambda j: j.update(harmony={"C:\\Users\\maria": 1}),  # publicar: permitir (ruta falsa de prueba)
            "version": lambda j: j.update(pegcraft="1.0 de Maria Perez"),
        }
        for nombre, mutar in casos.items():
            with self.subTest(nombre):
                pr = self._motivos(self._con(mutar))
                self.assertTrue(pr, nombre)
                for campo, motivo in pr:
                    for s in ("Datos", "servidor", "maria", "ejemplo.org", "Perez", "plano.tvg"):
                        self.assertNotIn(s, campo + motivo)          # dice campo y motivo, no el texto hallado

    def test_nombres_de_las_escenas(self):
        pr = self._motivos(self._con(lambda j: j["hallazgos"][0].update(clave="NodoInventadoZZ junto a MarmotaSecreta", categoria="aviso_otro")), escenas=self.dir)
        self.assertTrue(any("nombre de las escenas" in m for _, m in pr), pr)
        pr = self._motivos(self._con(lambda j: j["hallazgos"][0].update(clave="en plano_secreto_0420", categoria="aviso_otro")), escenas=self.dir)
        self.assertTrue(any("nombre de las escenas" in m for _, m in pr), pr)
        sin = self._motivos(self._con(lambda j: j["hallazgos"][0].update(clave="en MarmotaSecreta", categoria="aviso_otro")))      # sin --escenas no se compara
        self.assertFalse(any("nombre de las escenas" in m for _, m in sin), sin)

    def test_json_ilegible(self):
        p = Path(self.tmp.name) / "roto.json"; p.write_text("{no", encoding="utf-8")
        self.assertEqual(self._motivos(p)[0][0], "$")

    def test_cli_verificar_codigos_de_salida(self):
        cmd = [sys.executable, "-m", "pegcraft", "analizar", "--verificar"]
        ok = subprocess.run(cmd + [str(self.arch), "--escenas", str(self.dir)], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr); self.assertIn("OK", ok.stdout)
        mal = subprocess.run(cmd + [str(self._con(lambda j: j["hallazgos"][0].update(clave="C:\\Users\\maria\\x", categoria="aviso_otro")))], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")  # publicar: permitir (ruta falsa de prueba)
        self.assertEqual(mal.returncode, 1); self.assertIn("$.hallazgos[0].clave", mal.stdout); self.assertNotIn("maria", mal.stdout + mal.stderr)

    def test_compartible_se_niega_a_dejar_un_archivo_contaminado(self):
        from unittest import mock
        base = Path(self.tmp.name) / "log2" / "y"
        with mock.patch("pegcraft.analisis.compartible.depurar", lambda cat, clave, sens: "falla en C:\\Users\\maria\\x"):  # publicar: permitir (ruta falsa de prueba)
            with self.assertRaises(lote.CompartibleContaminado):
                lote.analizar([self.dir / "plano_secreto_0420.xstage"], base, compartible=True, salida=lambda s: None)
        self.assertFalse(base.with_name("y_compartible.json").exists())
        self.assertFalse(base.with_name("y_compartible.json.parcial").exists())
        self.assertTrue(base.with_suffix(".jsonl").exists())               # el log privado si queda


if __name__ == "__main__":
    unittest.main()
