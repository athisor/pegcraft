"""Pruebas del núcleo del lector con escenas sintéticas mínimas (nombres inventados, sin archivos externos).

    python -I -m unittest discover -s tests -p "test_nucleo*.py"
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pegcraft.lector import abrir, buscar, dibujos_de_reads, resumen, xstage_de
from pegcraft.lector.escena import Escena, limpiar_cache
from pegcraft.lector.xml import parsear_bytes

# Escena sintética:
#   Top: Fuente(PEG) -> Caja(grupo, entrada 0) ; Caja salida 0 -> Final ; Caja salida 1 -> Final entrada 1
#   Caja: Entra(MULTIPORT_IN) -> Hoja(READ) -> Sale(MULTIPORT_OUT, llamado "sin-nombre") entrada 0
#         Sale no tiene cable en la entrada 1.
#   Apagada: grupo apagado con un hijo propio sin marca.
XSTAGE = """<?xml version="1.0" encoding="UTF-8"?>
<project>
 <elements>
  <element id="2" elementName="Elem" elementFolder="Elem.2">
   <drawings><dwg name="1" /><dwg name="2" /></drawings>
  </element>
 </elements>
 <options>
  <metrics unitAspectRatioX="4" unitAspectRatioY="3" numberOfUnitsX="24" numberOfUnitsY="24" numberOfUnitsZ="12" />
  <framerate val="24" />
  <pixelPerModelUnitForVectorLayers val="0.5" />
 </options>
 <scenes>
  <scene name="Top" id="x" nbframes="10" startFrame="1" stopFrame="10">
   <columns>
    <column type="0" name="Col1" id="2"><elementSeq exposures="1" id="2" val="1" /></column>
    <column type="3" name="Col2" id="3" />
   </columns>
   <rootgroup name="Top">
    <nodeslist>
     <module name="Fuente" type="PEG" pos="10,20,1" publishUnderTab="Fuente">
      <attrs><scale><x val="2" /></scale><note val="a&#10;b" /></attrs>
     </module>
     <group name="Caja" pos="30,40,2">
      <nodeslist>
       <module name="Entra" type="MULTIPORT_IN" pos="0,0,3" />
       <module name="Hoja" type="READ" pos="5,5,4">
        <attrs><drawing><element col="Col1" /></drawing></attrs>
       </module>
       <module name="sin-nombre" type="MULTIPORT_OUT" pos="9,9,5" />
      </nodeslist>
      <linkedlist>
       <link in="Hoja" out="Entra" />
       <link in="sin-nombre" out="Hoja" />
      </linkedlist>
     </group>
     <module name="Final" type="COMPOSITE" pos="50,60,6" />
     <group name="Apagada" pos="1,1,7">
      <options><disabled val="true" /></options>
      <nodeslist>
       <module name="Hijo" type="READ" pos="1,1,8" />
      </nodeslist>
     </group>
     <module name="Otro" type="DeformationCompositeModule" pos="2,2,9">
      <options><disabled val="true" /></options>
     </module>
    </nodeslist>
    <linkedlist>
     <link in="Caja" out="Fuente" />
     <link in="Final" out="Caja" />
     <link in="Final" inport="1" out="Caja" outport="1" />
    </linkedlist>
    <backdrops>
     <backdrop bottomRight="35,45" topLeft="0,0">
      <background color="#112233FF" />
      <title color="#000000FF" font="Arial" size="14" text="Marco" />
     </backdrop>
    </backdrops>
   </rootgroup>
  </scene>
 </scenes>
</project>
"""


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ruta = Path(cls.tmp.name) / "prueba.xstage"
        cls.ruta.write_text(XSTAGE, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        limpiar_cache()
        self.e = abrir(self.ruta)


class TestXml(unittest.TestCase):
    def test_rechaza_doctype(self):
        with self.assertRaises(ValueError):
            parsear_bytes(b'<!DOCTYPE x [<!ENTITY a "b">]><x a="&a;"/>')
        with self.assertRaises(ValueError):
            parsear_bytes(b'<?xml version="1.0"?><!doctype x><x/>')

    def test_bom(self):
        self.assertEqual(parsear_bytes(b"\xef\xbb\xbf<x a='1'/>").get("a"), "1")

    def test_saltos_en_atributo(self):
        r = parsear_bytes(b'<x><y val="a\nb\r\nc"/><z t=\'1\n2\'/></x>')
        self.assertEqual(r.find("y").get("val"), "a\nb\r\nc")
        self.assertEqual(r.find("z").get("t"), "1\n2")

    def test_saltos_entre_etiquetas_intactos(self):
        r = parsear_bytes(b'<x>\n <y a="1"/>\n</x>')
        self.assertEqual(r.find("y").get("a"), "1")

    def test_mal_formado(self):
        with self.assertRaises(ValueError):
            parsear_bytes(b"<x><y></x>")


class TestCarga(Base):
    def test_nodos_en_preorden(self):
        self.assertEqual(list(self.e.nodos), [
            "Top/Fuente", "Top/Caja", "Top/Caja/Entra", "Top/Caja/Hoja", "Top/Caja/sin-nombre",
            "Top/Final", "Top/Apagada", "Top/Apagada/Hijo", "Top/Otro",
        ])

    def test_campos_de_nodo(self):
        n = self.e.nodos["Top/Caja"]
        self.assertEqual((n.tipo, n.nombre, n.grupo, n.pos, n.apagado), ("GROUP", "Caja", "Top", (30.0, 40.0, 2.0), False))
        f = self.e.nodos["Top/Fuente"]
        self.assertEqual((f.tipo, f.publish_tab, f.grupo), ("PEG", "Fuente", "Top"))
        self.assertEqual(self.e.nodos["Top/Caja/Hoja"].grupo, "Top/Caja")

    def test_apagado(self):
        self.assertTrue(self.e.nodos["Top/Apagada"].apagado)
        self.assertFalse(self.e.nodos["Top/Apagada/Hijo"].apagado)          # bandera propia
        self.assertTrue(self.e.apagado_efectivo("Top/Apagada/Hijo"))        # heredada
        self.assertFalse(self.e.apagado_efectivo("Top/Caja/Hoja"))

    def test_cables_literales(self):
        c = [(x.grupo, x.origen, x.puerto_origen, x.destino, x.puerto_destino) for x in self.e.cables]
        self.assertIn(("Top", "Top/Caja", 1, "Top/Final", 1), c)
        self.assertIn(("Top/Caja", "Top/Caja/Entra", 0, "Top/Caja/Hoja", 0), c)       # puertos por omisión 0
        self.assertEqual(len(c), 5)

    def test_backdrop(self):
        (b,) = self.e.backdrops
        self.assertEqual((b.grupo, b.titulo, b.color, b.rect), ("Top", "Marco", "#112233FF", (0.0, 0.0, 35.0, 45.0)))
        # dentro del rectángulo por posición (x, y): también caen los dos nodos de coordenadas pequeñas
        self.assertEqual(sorted(b.nodos), ["Top/Apagada", "Top/Caja", "Top/Fuente", "Top/Otro"])

    def test_elementos_y_escena(self):
        self.assertEqual(self.e.elementos[2].dibujos, ("1", "2"))
        self.assertEqual((self.e.elementos[2].nombre, self.e.elementos[2].carpeta), ("Elem", "Elem.2"))
        self.assertEqual((self.e.n_fotogramas, self.e.fps, self.e.pixel_por_unidad), (10, 24.0, 0.5))
        self.assertEqual(self.e.metricas["numberOfUnitsZ"], 12.0)
        self.assertEqual(self.e.metricas_texto["unitAspectRatioX"], "4")
        self.assertEqual(self.e.avisos, [])

    def test_atributos(self):
        self.assertEqual(self.e.atributo("Top/Fuente", "scale", "x"), "2")
        self.assertEqual(self.e.atributo("Top/Fuente", "scale/x"), "2")
        self.assertEqual(self.e.atributo("Top/Fuente", "note"), "a\nb")
        self.assertIsNone(self.e.atributo("Top/Fuente", "no", "existe"))
        self.assertIsNone(self.e.atributo("Top/NoExiste", "scale", "x"))
        self.assertEqual(self.e.atributo_elem("Top/Fuente", "scale", "x").get("val"), "2")

    def test_rutas_equivalentes(self):
        for r in ("Top/Caja/Hoja", "/Caja/Hoja", "Caja/Hoja", "/Top/Caja/Hoja"):
            self.assertEqual(self.e.fuente(r), ("Top/Fuente", 0))

    def test_columnas_perezosas(self):
        self.assertIn("Col1", self.e.columnas)
        self.assertEqual(self.e.columnas["Col1"].nombre, "Col1")

    def test_metricas_por_omision_con_aviso(self):
        r = parsear_bytes(XSTAGE.replace('numberOfUnitsZ="12"', "").encode())
        e = Escena(Path("x.xstage"), r)
        self.assertEqual(e.metricas["numberOfUnitsZ"], 12.0)
        self.assertNotIn("numberOfUnitsZ", e.metricas_texto)
        self.assertTrue(any("numberOfUnitsZ" in a for a in e.avisos))
        sin = parsear_bytes(XSTAGE.replace("<metrics", "<otras").encode())
        e = Escena(Path("x.xstage"), sin)
        self.assertEqual(e.metricas["unitAspectRatioX"], 4.0)
        self.assertTrue(e.avisos)

    def test_sin_escena(self):
        with self.assertRaises(ValueError):
            Escena(Path("x.xstage"), parsear_bytes(b"<project/>"))


class TestGrafo(Base):
    def test_entradas_literales(self):
        self.assertEqual(self.e.entradas("Top/Final"), {0: ("Top/Caja", 0), 1: ("Top/Caja", 1)})
        self.assertEqual(self.e.puertos_composite("Top/Final"), [0, 1])
        self.assertEqual(self.e.puertos_composite("Top/Fuente"), [])

    def test_fuente_a_traves_de_multiport_in(self):
        # Hoja <- Entra(MULTIPORT_IN) <- entrada 0 del grupo <- Fuente
        self.assertEqual(self.e.fuentes("Top/Caja/Hoja"), [("Top/Fuente", 0)])

    def test_salida_de_grupo_por_tipo_aunque_se_llame_distinto(self):
        # P12: el MULTIPORT_OUT se llama "sin-nombre"
        self.assertEqual(self.e.fuentes("Top/Final", 0), [("Top/Caja/Hoja", 0)])

    def test_salida_de_grupo_sin_fuente_interior(self):
        self.assertEqual(self.e.fuentes("Top/Final", 1), [("Top/Caja", 1)])

    def test_sin_cable(self):
        self.assertEqual(self.e.fuentes("Top/Fuente"), [])
        self.assertIsNone(self.e.fuente("Top/Fuente"))

    def test_salidas_resueltas(self):
        self.assertEqual(self.e.salidas("Top/Fuente"), [(0, "Top/Caja/Hoja", 0)])
        self.assertEqual(self.e.salidas("Top/Caja/Hoja"), [(0, "Top/Final", 0)])
        self.assertEqual(self.e.salidas("Top/Final"), [])

    def test_vecinos(self):
        self.assertEqual(self.e.vecinos("Top/Final"), [("Top/Caja/Hoja", "READ"), ("Top/Caja", "GROUP")])
        self.assertEqual(self.e.vecinos("Top/Final", cruzar_grupos=False), [("Top/Caja", "GROUP")])
        todos = self.e.vecinos("Top/Final", profundidad=None)
        self.assertEqual([r for r, _ in todos], ["Top/Caja/Hoja", "Top/Caja", "Top/Fuente"])
        self.assertEqual(self.e.vecinos("Top/Fuente", "abajo", None), [("Top/Caja/Hoja", "READ"), ("Top/Final", "COMPOSITE")])
        with self.assertRaises(ValueError):
            self.e.vecinos("Top/Final", "lado")

    def test_ciclo_no_cuelga(self):
        x = XSTAGE.replace('<link in="Caja" out="Fuente" />', '<link in="Caja" out="Fuente" /><link in="Fuente" out="Caja" />')
        e = Escena(Path("c.xstage"), parsear_bytes(x.encode()))
        e.vecinos("Top/Final", profundidad=None)
        e.fuentes("Top/Fuente")
        self.assertIsInstance(e.fuentes("Top/Caja/Hoja"), list)

    def test_ciclo_de_grupo_corta_por_profundidad(self):
        # grupo cuya salida alimenta su propia entrada: la resolución no puede recursar sin fin
        x = XSTAGE.replace('<link in="Caja" out="Fuente" />', '<link in="Caja" out="Caja" />')
        x = x.replace('<link in="sin-nombre" out="Hoja" />', '<link in="sin-nombre" out="Entra" />')
        e = Escena(Path("c.xstage"), parsear_bytes(x.encode()))
        self.assertEqual(e.fuentes("Top/Final", 0), [("Top/Caja", 0)])   # sin fuente interior real
        self.assertTrue(any("profundidad" in a for a in e.avisos))


class TestResumen(Base):
    def test_resumen(self):
        r = resumen(self.e)
        self.assertEqual(r["formato"], "harmony_native")
        self.assertEqual(r["nodos"], 9)
        self.assertEqual(r["por_tipo"], {
            "COMPOSITE": 1, "DeformationCompositeModule": 1, "GROUP": 2, "MULTIPORT_IN": 1,
            "MULTIPORT_OUT": 1, "PEG": 1, "READ": 2})
        self.assertEqual(r["grupos"], [{"nodos": 3, "reads": 1, "ruta": "Top/Caja"},
                                       {"nodos": 1, "reads": 1, "ruta": "Top/Apagada"}])
        self.assertEqual((r["elementos"], r["columnas_de_dibujo"], r["fotogramas"]), (1, 1, 10))
        self.assertEqual((r["apagados"], r["composites"], r["backdrops"]), (2, 2, 1))
        self.assertEqual(r["avisos"], [])

    def test_dibujos_de_reads(self):
        d = dibujos_de_reads(self.e)
        self.assertEqual([x["ruta"] for x in d], ["Top/Caja/Hoja", "Top/Apagada/Hijo"])
        self.assertEqual(d[0]["columna"], "Col1")
        self.assertEqual((d[0]["elemento"], d[0]["carpeta"], d[0]["n_dibujos"]), ("Elem", "Elem.2", 2))
        self.assertEqual(d[0]["dibujos"], ["1", "2"])
        self.assertIsNone(d[1]["columna"])
        self.assertEqual(len(dibujos_de_reads(self.e, max=1)), 1)

    def test_buscar(self):
        self.assertEqual([x["ruta"] for x in buscar(self.e, tipos=["READ"])], ["Top/Caja/Hoja", "Top/Apagada/Hijo"])
        self.assertEqual([x["ruta"] for x in buscar(self.e, texto="^hoja$")], ["Top/Caja/Hoja"])
        self.assertNotIn("Top/Apagada", [x["ruta"] for x in buscar(self.e, apagados=False)])
        self.assertEqual(len(buscar(self.e, max=2)), 2)
        fin = buscar(self.e, texto="final")[0]
        self.assertTrue(fin["entradas"])


class TestAbrir(Base):
    def test_cache_por_mtime_y_tamano(self):
        self.assertIs(abrir(self.ruta), self.e)
        self.assertIs(abrir(self.tmp.name), self.e)            # carpeta con un .xstage
        nueva = Path(self.tmp.name) / "otra.xstage"
        nueva.write_text(XSTAGE + "\n", encoding="utf-8")
        otra = abrir(nueva)
        self.assertIsNot(otra, self.e)
        nueva.write_text(XSTAGE + "\n\n", encoding="utf-8")
        os.utime(nueva, ns=(time.time_ns(), time.time_ns() + 5_000_000))
        self.assertIsNot(abrir(nueva), otra)                    # cambió: se relee
        nueva.unlink()

    def test_cache_de_dos(self):
        limpiar_cache()
        a = abrir(self.ruta)
        d2 = Path(self.tmp.name) / "b.xstage"
        d3 = Path(self.tmp.name) / "c.xstage"
        d2.write_text(XSTAGE, encoding="utf-8")
        d3.write_text(XSTAGE, encoding="utf-8")
        abrir(d2)
        abrir(d3)                                               # expulsa la más antigua (a)
        self.assertIsNot(abrir(self.ruta), a)
        d2.unlink()
        d3.unlink()

    def test_xstage_de(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            with self.assertRaises(FileNotFoundError):
                xstage_de(t)
            with self.assertRaises(FileNotFoundError):
                xstage_de(t / "nada")
            (t / "uno.xstage").write_text("<project/>")
            self.assertEqual(xstage_de(t), t / "uno.xstage")
            (t / "dos.xstage").write_text("<project/>")
            with self.assertRaises(ValueError):
                xstage_de(t)
            (t / f"{t.name}.xstage").write_text("<project/>")
            self.assertEqual(xstage_de(t), t / f"{t.name}.xstage")
            self.assertEqual(xstage_de(t / "uno.xstage"), t / "uno.xstage")


if __name__ == "__main__":
    unittest.main()
