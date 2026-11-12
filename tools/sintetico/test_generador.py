"""Pruebas del generador y del calculo de esperados: python -I -m unittest discover -s tools/sintetico"""
import json
import math
import re
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import esperado as E
import generador as G

CASOS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "lector" / "casos"
RUTA_ABS = re.compile(r"\b[A-Za-z]:[\\/]{1,2}[\w.\-]{2,}|\\\\[\w.\-]{2,}\\|/Users/|/home/")

MINIMA = {"nombre": "minima", "nodos": [
    {"tipo": "PEG", "nombre": "Pieza_A", "attrs": {"rotation/anglez": 45}},
    {"tipo": "READ", "nombre": "Pieza_B"},
    {"tipo": "COMPOSITE", "nombre": "Composite"}],
    "enlaces": [{"origen": "Pieza_A", "destino": "Pieza_B"}, {"origen": "Pieza_B", "destino": "Composite"}]}


def esp(caso):
    return json.loads((CASOS / f"{caso}.esperado.json").read_text(encoding="utf-8"))


class TestGenerador(unittest.TestCase):
    def test_determinista(self):
        self.assertEqual(G.a_bytes(MINIMA), G.a_bytes(json.loads(json.dumps(MINIMA))))

    def test_estructura_basica(self):
        datos = G.a_bytes(MINIMA)
        self.assertNotIn(b"\r", datos)
        self.assertNotIn(b"checksumValidation", datos)
        self.assertNotIn(b"<metas", datos)
        r = ET.fromstring(datos)
        self.assertEqual([h.tag for h in r], ["elements", "options", "timelineMarkers", "scenes", "symbols", "timeline"])
        sc = r.find("scenes/scene")
        self.assertEqual([h.tag for h in sc], ["columns", "options", "rootgroup", "unconnectedComposite", "timelineOrderer"])
        self.assertEqual([h.tag for h in sc.find("rootgroup")], ["options", "nodeslist", "linkedlist"])
        self.assertTrue(datos.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<project '))
        # sangria de 1 espacio por nivel
        self.assertIn(b"\n <elements>\n  <element ", datos)

    def test_angle_replica_anglez_y_read_recibe_columna(self):
        r = ET.fromstring(G.a_bytes(MINIMA))
        peg = next(m for m in r.iter("module") if m.get("name") == "Pieza_A")
        self.assertEqual(peg.find("attrs/rotation/anglez").get("val"), "45")
        self.assertEqual(peg.find("attrs/angle").get("val"), "45")
        read = next(m for m in r.iter("module") if m.get("name") == "Pieza_B")
        col = read.find("attrs/drawing/element").get("col")
        self.assertIn(col, {c.get("name") for c in r.iter("column")})

    def test_enlaces_orden_y_puertos(self):
        sp = {"nombre": "e", "nodos": [{"tipo": "COMPOSITE", "nombre": "C"}, {"tipo": "PEG", "nombre": "P"}],
              "enlaces": [{"origen": "P", "destino": "C", "puerto_origen": 1, "puerto_destino": 2},
                          {"origen": "P", "destino": "C", "explicito": True}]}
        t = G.a_bytes(sp).decode()
        self.assertIn('<link in="C" inport="2" out="P" outport="1"/>', t)
        self.assertIn('<link in="C" inport="0" out="P" outport="0"/>', t)

    def test_saltos_y_entidades(self):
        sp = {"nombre": "s", "codificacion": {"bom": True, "entidades_numericas": True}, "nodos": [
            {"tipo": "WRITE", "nombre": "W", "attrs": {"scriptEditor": {"val": "a\nb"}}},
            {"tipo": "WRITE", "nombre": "Xñ&", "attrs": {"scriptEditor": {"val": "a\nb", "salto": "entidad"}}}]}
        d = G.a_bytes(sp)
        self.assertTrue(d.startswith(b"\xef\xbb\xbf<?xml"))
        t = d.decode("utf-8-sig")
        self.assertIn('scriptEditor val="a\nb"', t)
        self.assertIn('scriptEditor val="a&#10;b"', t)
        self.assertIn('name="X&#241;&amp;"', t)
        self.assertTrue(all(ord(c) < 128 for c in t))

    def test_errores_de_especificacion(self):
        mal = {"nombre": "m", "nodos": [{"tipo": "PEG", "nombre": "A"}], "enlaces": [{"origen": "A", "destino": "Z"}]}
        with self.assertRaises(ValueError):
            G.a_bytes(mal)
        mal = {"nombre": "m", "nodos": [{"tipo": "PEG", "nombre": "A", "attrs": {"scale/x": {"col": "NoExiste"}}}]}
        with self.assertRaises(ValueError):
            G.a_bytes(mal)
        mal = {"nombre": "m", "nodos": [{"tipo": "PEG", "nombre": "A"}, {"tipo": "PEG", "nombre": "A"}]}
        with self.assertRaises(ValueError):
            G.a_bytes(mal)

    def test_verificar_detecta_cambios(self):
        d = Path(tempfile.mkdtemp())
        sp = d / "x.json"
        sp.write_text(json.dumps(MINIMA), encoding="utf-8")
        self.assertTrue(G.procesar(sp))
        self.assertTrue(G.procesar(sp, verificar=True))
        (d / "x.xstage").write_bytes((d / "x.xstage").read_bytes() + b" ")
        self.assertFalse(G.procesar(sp, verificar=True))
        self.assertEqual(G.main(["--dir", str(d), "--verificar"]), 1)
        shutil.rmtree(d)


class TestFixtures(unittest.TestCase):
    def test_todos_los_casos_regeneran_byte_a_byte(self):
        specs = sorted(p for p in CASOS.glob("*.json") if not p.name.endswith(".esperado.json"))
        self.assertGreaterEqual(len(specs), 16)
        for p in specs:
            with self.subTest(caso=p.stem):
                self.assertTrue(G.procesar(p, verificar=True))
                self.assertTrue(E.procesar(p, verificar=True))

    def test_fixtures_limpios(self):
        for p in CASOS.iterdir():
            with self.subTest(archivo=p.name):
                datos = p.read_bytes()
                self.assertLess(len(datos), 200_000)
                texto = datos.decode("utf-8-sig")
                self.assertNotIn("checksumValidation", texto)
                self.assertIsNone(RUTA_ABS.search(texto))
                if p.suffix == ".xstage":
                    ET.fromstring(datos)

    def test_origen_declarado(self):
        for p in CASOS.glob("*.esperado.json"):
            e = json.loads(p.read_text(encoding="utf-8"))
            self.assertIn(e["origen"], ("regla", "paridad"), p.name)

    def test_hay_20_casos_y_los_nuevos(self):
        nombres = {p.name[:-len(".esperado.json")] for p in CASOS.glob("*.esperado.json")}
        self.assertGreaterEqual(len(nombres), 20)
        for n in ("c17_peg_traslacion_pivote", "c18_cadena_trasl_rot_esc_sesgo", "c19_velocity_fuera_de_rango", "c20_grupo_apagado_anidado"):
            self.assertIn(n, nombres)

    def test_medicion_de_harmony_declarada(self):
        """La seccion `medicion` (origen harmony) convive con regla/paridad y sobrevive a regenerar."""
        for p in CASOS.glob("*.esperado.json"):
            e = json.loads(p.read_text(encoding="utf-8"))
            m = e["medicion"]
            self.assertIn(m["estado"], ("pendiente", "medido"), p.name)
            if m["estado"] == "medido":
                self.assertEqual(m["origen"], "harmony", p.name)
                self.assertEqual(e["origen_por_bloque"]["medicion"], "harmony", p.name)
                self.assertIn("error_lectura", m)
                self.assertIn("evaluacion", e)                          # no se borra regla/paridad
                self.assertIn(e["origen"], ("regla", "paridad"))

    def test_regenerar_conserva_la_medicion(self):
        spec = CASOS / "c10_peg_apagado.json"
        previo = json.loads((CASOS / "c10_peg_apagado.esperado.json").read_text(encoding="utf-8"))
        if previo["medicion"]["estado"] != "medido":
            self.skipTest("c10 aun sin medicion")
        with tempfile.TemporaryDirectory() as d:
            copia = Path(d) / spec.name
            shutil.copy(spec, copia)
            shutil.copy(CASOS / "c10_peg_apagado.esperado.json", Path(d) / "c10_peg_apagado.esperado.json")
            self.assertTrue(E.procesar(copia, verificar=True))        # regenerar da lo mismo, medicion incluida
            E.procesar(copia)
            nuevo = json.loads((Path(d) / "c10_peg_apagado.esperado.json").read_text(encoding="utf-8"))
            self.assertEqual(nuevo["medicion"], previo["medicion"])


class TestEsperado(unittest.TestCase):
    def test_cadena_con_rotacion_y_escala(self):
        e = esp("c03_cadena_dos_peg")["evaluacion"]
        m = e["7"]["Top/Dibujo_A"]["matriz"]                # R(15) * S(2,1): a mitad de camino entre 0 y 30
        c, s = math.cos(math.radians(15)), math.sin(math.radians(15))
        for got, want in zip(m[0] + m[1], [2 * c, -s, 0, 2 * s, c, 0]):
            self.assertAlmostEqual(got, want, places=8)
        self.assertEqual(e["7"]["Top/Dibujo_A"]["cadena"], ["Top/Peg_Hijo", "Top/Peg_Padre"])

    def test_fuentes_a_traves_de_grupos(self):
        e = esp("c04_grupo_multiport")
        self.assertEqual(e["fuentes"]["Top/Grupo_1/Peg_G"]["0"], [["Top/Peg_Raiz", 0]])
        self.assertEqual(e["fuentes"]["Top/Composite"]["0"], [["Top/Grupo_1/Dibujo_G", 0]])
        self.assertEqual(e["evaluacion"]["1"]["Top/Grupo_1/Dibujo_G"]["padre"], "Grupo_1")

    def test_salida_vacia_y_outport(self):
        self.assertEqual(esp("c05_salida_grupo_vacia")["fuentes"]["Top/Composite"]["1"], [["Top/Grupo_1", 1]])
        f = esp("c06_composites_anidados")["fuentes"]["Top/Composite_Top"]
        self.assertEqual(f["1"], [["Top/Grupo_Puertas/Comp_Interno", 0]])
        self.assertEqual(f["2"], [["Top/Grupo_Puertas/Dibujo_P3", 0]])

    def test_ylocal_manda(self):
        e = esp("c15_y_distinto_ylocal")["evaluacion"]
        self.assertEqual(e["1"]["Top/Peg_A"]["canales"]["escala.x"], 0.5)
        self.assertEqual(e["5"]["Top/Dibujo_A"]["z"], 0.0)

    def test_apagados_cuentan_en_z_y_herencia(self):
        e = esp("c10_peg_apagado")["evaluacion"]["1"]["Top/Dibujo_A"]
        self.assertEqual(e["z"], 0.75)
        e = esp("c11_grupo_apagado")["evaluacion"]["1"]["Top/Grupo_Apagado/Dibujo_G"]
        self.assertFalse(e["apagado"])
        self.assertTrue(e["apagado_efectivo"])

    def test_sesgo_expuesto_y_ignorado_en_matriz(self):
        e = esp("c16_sesgo_no_cero")["evaluacion"]["3"]["Top/Peg_A"]
        self.assertEqual(e["canales"]["sesgo"], 10.0)
        self.assertEqual(e["matriz"], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    def test_trayectoria_un_punto_y_coincidentes_son_paridad(self):
        self.assertEqual(esp("c08_trayectoria_un_punto")["evaluacion"]["6"]["Top/Peg_A"]["canales"]["posicion.z"], 0.1)
        self.assertEqual(esp("c08_trayectoria_un_punto")["origen"], "paridad")
        self.assertEqual(esp("c09_puntos_coincidentes")["evaluacion"]["11"]["Top/Peg_A"]["canales"]["posicion.x"], 1.0)

    def test_texto_con_saltos(self):
        a = esp("c13_saltos_linea_atributo")["atributos"]
        self.assertEqual(a["Top/Escritura_1"]["scriptEditor"], "linea uno\nlinea dos\n\nlinea cuatro")
        self.assertEqual(a["Top/Escritura_2"]["scriptEditor"], "alfa\nbeta\r\ngamma")


if __name__ == "__main__":
    unittest.main()
