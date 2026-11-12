"""Pruebas del lector de paletas (`sightread.plt`). Todo se construye en la prueba: ningun archivo real."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sightread import plt as P

CAB = "ToonBoomAnimationInc PaletteFile 2"
LISTA = "ToonBoomAnimationInc PaletteList 1"


def solid(nombre, cid, rgba, ficha=None):
    f = ficha if ficha is not None else nombre
    return "Solid    %-26s 0x%s %3d %3d %3d %3d" % (f, cid, *rgba)


def plt(*filas, eol="\n"):
    return (eol.join([CAB, *filas]) + eol).encode("utf-8")


GRAD = ["Gradient Cielo                      0x0d00000000000011 Linear ",
        "{        0.0 148 148 238 255,",
        "        50.0  10  20  30 128,",
        "       100.0 229 229 229 255 }"]


class TestLeer(unittest.TestCase):
    def test_solid_basico(self):
        p = P.leer(plt(solid("Piel", "0d00000000000001", (179, 110, 85, 255))))
        c = p.colores()
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["tipo"], "Solid")
        self.assertEqual(c[0]["id"], "0d00000000000001")
        self.assertEqual(c[0]["nombre"], "Piel")
        self.assertEqual(c[0]["rgba"], (179, 110, 85, 255))

    def test_nombres_con_comillas(self):
        filas = [solid("", "0d00000000000002", (1, 2, 3, 4), ficha='"Piel clara"'),
                 solid("", "0d00000000000003", (0, 0, 0, 0), ficha='""'),
                 solid("", "0d00000000000004", (9, 9, 9, 9), ficha='"Pañuelo"'),
                 solid("", "0d00000000000005", (9, 9, 9, 9), ficha="Chasquilla_Pañuelo")]
        c = P.leer(plt(*filas)).colores()
        self.assertEqual([x["nombre"] for x in c], ["Piel clara", "", "Pañuelo", "Chasquilla_Pañuelo"])
        self.assertEqual(c[1]["rgba"], (0, 0, 0, 0))

    def test_variante_otra_maquetacion(self):
        # PLT-v0 §3.5: un espacio tras Solid y ficha con comillas rellena a 29
        fila = 'Solid "New 1_2"                    0x0d0000000000000a 255   0   0 255'
        c = P.leer(plt(fila)).colores()
        self.assertEqual(c[0]["nombre"], "New 1_2")
        self.assertEqual(c[0]["rgba"], (255, 0, 0, 255))

    def test_crlf_y_sin_salto_final(self):
        datos = plt(solid("A", "0d00000000000001", (1, 2, 3, 255)), solid("B", "0d00000000000002", (4, 5, 6, 255)), eol="\r\n")
        self.assertEqual([x["nombre"] for x in P.leer(datos).colores()], ["A", "B"])
        self.assertEqual(len(P.leer(datos.rstrip(b"\r\n")).colores()), 2)

    def test_gradiente(self):
        c = P.leer(plt(*GRAD)).colores()
        self.assertEqual(len(c), 1)
        g = c[0]
        self.assertEqual((g["tipo"], g["extra"], g["id"], g["nombre"]), ("Gradient", "Linear", "0d00000000000011", "Cielo"))
        self.assertIsNone(g["rgba"])
        self.assertEqual(g["paradas"], [(0.0, (148, 148, 238, 255)), (50.0, (10, 20, 30, 128)), (100.0, (229, 229, 229, 255))])

    def test_gradiente_radial_y_fila_siguiente(self):
        radial = ["Gradient Sol 0x0d00000000000012 Radial ", "{        0.0 255 255   0 255,", "       100.0 255   0   0   0 }"]
        c = P.leer(plt(*radial, solid("Despues", "0d00000000000013", (1, 1, 1, 255)))).colores()
        self.assertEqual([x["tipo"] for x in c], ["Gradient", "Solid"])
        self.assertEqual(c[0]["extra"], "Radial")
        self.assertEqual(len(c[0]["paradas"]), 2)
        self.assertEqual(c[1]["nombre"], "Despues")

    def test_texture_y_cadena(self):
        filas = ['"TB_Pencil_Texture|"',
                 "Texture  Lapiz1                    0x0400000000000001 Tile",
                 "Texture  Img                       0x0d00000000000099 Stretch"]
        p = P.leer(plt(*filas))
        c = p.colores()
        self.assertEqual([(x["tipo"], x["extra"]) for x in c], [("Texture", "Tile"), ("Texture", "Stretch")])
        self.assertEqual(p.conteo["Cadena"], 1)
        self.assertEqual(p.conteo["Texture"], 2)

    def test_linea_desconocida_no_rompe(self):
        p = P.leer(plt("cosa rara", solid("A", "0d00000000000001", (1, 2, 3, 255)), "Solid truncada"))
        self.assertEqual(len(p.colores()), 1)
        self.assertEqual(p.conteo["Desconocida"], 2)

    def test_solo_cabecera_y_sin_cabecera(self):
        self.assertEqual(P.leer(plt()).colores(), [])
        with self.assertRaises(P.PaletaIlegible):
            P.leer(b"no es una paleta\n")
        with self.assertRaises(P.PaletaIlegible):
            P.leer(b"")

    def test_ids_en_mayusculas_se_normalizan(self):
        c = P.leer(plt("Solid    X                          0x0D0000000000ABCD   1   2   3 255")).colores()
        self.assertEqual(c[0]["id"], "0d0000000000abcd")

    def test_orden_se_conserva(self):
        filas = [solid("n%d" % i, "0d%014x" % (100 - i), (i, i, i, 255)) for i in range(5)]
        self.assertEqual([x["nombre"] for x in P.leer(plt(*filas)).colores()], ["n0", "n1", "n2", "n3", "n4"])


def escribir(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(datos if isinstance(datos, bytes) else datos.encode("utf-8"))


def lista(*entradas, eol="\n"):
    return eol.join([LISTA, *entradas]) + eol


class TestEscena(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.esc = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def test_declarada_y_destino_absoluto_ignorado(self):
        escribir(self.esc / "palette-library" / "Rig.plt", plt(solid("Piel", "0d00000000000001", (1, 2, 3, 255))))
        escribir(self.esc / "PALETTE_LIST", lista('palette-library/Rig LINK "/otra/maquina/palette-library/Rig.plt"'))
        ps = P.paletas(self.esc)
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0]["archivo"], self.esc / "palette-library" / "Rig.plt")
        self.assertTrue(ps[0]["declarada"])
        self.assertEqual((ps[0]["ambito"], ps[0]["clave"]), ("escena", "Rig"))
        self.assertEqual(P.paleta_tvg(self.esc)["0d00000000000001"], {"nombre": "Piel", "rgba": (1, 2, 3, 255), "paleta": "Rig"})

    def test_no_declarada_no_se_carga(self):
        escribir(self.esc / "palette-library" / "Rig.plt", plt(solid("A", "0d00000000000001", (1, 2, 3, 255))))
        escribir(self.esc / "palette-library" / "Huerfana.plt", plt(solid("B", "0d00000000000002", (4, 5, 6, 255))))
        escribir(self.esc / "PALETTE_LIST", lista('palette-library/Rig LINK "x"'))
        ps = {p["clave"]: p for p in P.paletas(self.esc)}
        self.assertTrue(ps["Rig"]["declarada"])
        self.assertFalse(ps["Huerfana"]["declarada"])
        self.assertEqual(list(P.paleta_tvg(self.esc)), ["0d00000000000001"])

    def test_declarada_sin_archivo(self):
        escribir(self.esc / "PALETTE_LIST", lista('palette-library/Falta LINK "x"'))
        ps = P.paletas(self.esc)
        self.assertEqual(len(ps), 1)
        self.assertIsNone(ps[0]["archivo"])
        self.assertTrue(ps[0]["declarada"])
        self.assertEqual(P.paleta_tvg(self.esc), {})

    def test_orden_de_la_lista_y_primera_gana(self):
        escribir(self.esc / "palette-library" / "A.plt", plt(solid("DeA", "0d00000000000001", (1, 1, 1, 255))))
        escribir(self.esc / "palette-library" / "B.plt", plt(solid("DeB", "0d00000000000001", (2, 2, 2, 255)), solid("Solo B", "0d00000000000002", (3, 3, 3, 255), ficha='"Solo B"')))
        escribir(self.esc / "PALETTE_LIST", lista('palette-library/B LINK "x"', 'palette-library/A LINK "x"'))
        self.assertEqual([p["clave"] for p in P.paletas(self.esc)], ["B", "A"])
        t = P.paleta_tvg(self.esc)
        self.assertEqual(t["0d00000000000001"]["nombre"], "DeB")
        self.assertEqual(set(t), {"0d00000000000001", "0d00000000000002"})

    def test_clave_repetida_y_crlf(self):
        escribir(self.esc / "palette-library" / "A.plt", plt(solid("A", "0d00000000000001", (1, 1, 1, 255))))
        escribir(self.esc / "PALETTE_LIST", lista('palette-library/A LINK "x"', 'palette-library/A LINK "y"', eol="\r\n"))
        self.assertEqual(len(P.paletas(self.esc)), 1)

    def test_clave_con_espacios_y_destino_sin_comillas(self):
        escribir(self.esc / "palette-library" / "Rig Uno.plt", plt(solid("A", "0d00000000000001", (1, 1, 1, 255))))
        escribir(self.esc / "PALETTE_LIST", lista("palette-library/Rig Uno LINK /otra/maquina/palette-library/Rig Uno.plt"))
        ps = P.paletas(self.esc)
        self.assertEqual(ps[0]["clave"], "Rig Uno")
        self.assertIsNotNone(ps[0]["archivo"])

    def test_elemento(self):
        escribir(self.esc / "palette-library" / "Esc.plt", plt(solid("Esc", "0d00000000000001", (1, 1, 1, 255))))
        escribir(self.esc / "PALETTE_LIST", lista('palette-library/Esc LINK "x"'))
        el = self.esc / "elements" / "dib1"
        escribir(el / "palette-library" / "Loc.plt", plt(solid("Loc", "0d00000000000002", (2, 2, 2, 255)), solid("Pisa", "0d00000000000001", (9, 9, 9, 255))))
        escribir(el / "PALETTE_LIST", lista('palette-library/Loc LINK "x"'))
        otro = self.esc / "elements" / "dib2"
        escribir(otro / "palette-library" / "Otra.plt", plt(solid("Otra", "0d00000000000003", (3, 3, 3, 255))))
        escribir(otro / "PALETTE_LIST", lista('palette-library/Otra LINK "x"'))
        self.assertEqual({p["ambito"] for p in P.paletas(self.esc)}, {"escena", "elemento:dib1", "elemento:dib2"})
        self.assertEqual(set(P.paleta_tvg(self.esc)), {"0d00000000000001"})
        t = P.paleta_tvg(self.esc, "dib1")
        self.assertEqual(set(t), {"0d00000000000001", "0d00000000000002"})
        self.assertEqual(t["0d00000000000001"]["nombre"], "Esc")      # la paleta de la escena gana
        self.assertNotIn("0d00000000000003", t)

    def test_clave_hacia_la_paleta_de_la_escena(self):
        escribir(self.esc / "palette-library" / "Esc.plt", plt(solid("Esc", "0d00000000000001", (1, 1, 1, 255))))
        el = self.esc / "elements" / "dib1"
        el.mkdir(parents=True)
        escribir(el / "PALETTE_LIST", lista('../../palette-library/Esc LINK "x"'))
        ps = [p for p in P.paletas(self.esc) if p["ambito"] == "elemento:dib1" and p["declarada"]]
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0]["clave"], "Esc")
        self.assertEqual(set(P.paleta_tvg(self.esc, "dib1")), {"0d00000000000001"})

    def test_escena_como_ruta_de_xstage(self):
        escribir(self.esc / "palette-library" / "A.plt", plt(solid("A", "0d00000000000001", (1, 1, 1, 255))))
        escribir(self.esc / "PALETTE_LIST", lista('palette-library/A LINK "x"'))
        escribir(self.esc / "escena.xstage", "<x/>")
        self.assertEqual(set(P.paleta_tvg(self.esc / "escena.xstage")), {"0d00000000000001"})

    def test_paleta_tvg_solo_solid_y_plt_roto(self):
        escribir(self.esc / "palette-library" / "A.plt", plt(*GRAD, solid("S", "0d00000000000001", (1, 1, 1, 255))))
        escribir(self.esc / "palette-library" / "Mala.plt", b"basura")
        escribir(self.esc / "PALETTE_LIST", lista('palette-library/Mala LINK "x"', 'palette-library/A LINK "x"'))
        self.assertEqual(set(P.paleta_tvg(self.esc)), {"0d00000000000001"})

    def test_capitalizacion_distinta(self):
        # La lista nombra "rig" y en disco el archivo es "Rig.plt"; la carpeta es "Palette-Library" (en Linux importa)
        escribir(self.esc / "Palette-Library" / "Rig.plt", plt(solid("A", "0d00000000000001", (1, 1, 1, 255))))
        escribir(self.esc / "PALETTE_LIST", lista('palette-library/rig LINK "x"'))
        ps = [p for p in P.paletas(self.esc) if p["declarada"]]
        self.assertEqual(len(ps), 1)
        self.assertIsNotNone(ps[0]["archivo"])
        self.assertEqual(set(P.paleta_tvg(self.esc)), {"0d00000000000001"})

    def test_capitalizacion_exacta_gana(self):
        from sightread import rutas
        escribir(self.esc / "Sub" / "x.TXT", "a")
        self.assertEqual(rutas.buscar(self.esc, "sub/X.txt").name.lower(), "x.txt")
        self.assertIsNone(rutas.buscar(self.esc, "sub/otro.txt"))
        self.assertEqual(rutas.buscar(self.esc, "Sub", "..", "Sub/x.TXT").name.lower(), "x.txt")

    def test_sin_nada(self):
        self.assertEqual(P.paletas(self.esc), [])
        self.assertEqual(P.paleta_tvg(self.esc), {})


if __name__ == "__main__":
    unittest.main()
