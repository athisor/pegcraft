"""Pruebas del Evaluador (modo de compatibilidad «paridad», por omisión) con escenas sintéticas mínimas.

    python -I -m unittest discover -s tests/lector -p "test_evaluar*.py"
"""
import math
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pegcraft.lector.dibujos import DibujoRef
from pegcraft.lector.evaluar import Evaluador
from test_evaluar_ayuda import Escenas, cable, grupo, modulo, peg, read, xstage

ESC = Escenas()


def tearDownModule():
    ESC.cerrar()


def cerca(t, a, b, tol=1e-9):
    t.assertEqual(len(a), len(b))
    for x, y in zip(a, b):
        if isinstance(x, (list, tuple)):
            cerca(t, x, y, tol)
        else:
            t.assertAlmostEqual(x, y, delta=tol)


def cadena_simple(p1, p2=None, r=None, **kw):
    """P1 -> [P2] -> READ -> Composite -> Pantalla."""
    nodos = [p1] + ([p2] if p2 else []) + [r or read("Hoja"), modulo("COMPOSITE", "Comp"), modulo("DISPLAY", "Pant")]
    cables = ""
    nombres = ["P1"] + (["P2"] if p2 else []) + ["Hoja"]
    for a, b in zip(nombres, nombres[1:]):
        cables += cable(a, b)
    cables += cable("Hoja", "Comp") + cable("Comp", "Pant")
    return xstage(nodos, cables, **kw)


class Canales(unittest.TestCase):
    def test_canales_y_defectos(self):
        e = ESC.abrir_xml(cadena_simple(peg("P1", pos=(1, 2, 3), rot=30, esc=(2, 3), sesgo=5, piv=(0.5, -1))))
        c = Evaluador(e).canales("Top/P1", 1)
        self.assertEqual((c["posicion.x"], c["posicion.y"], c["posicion.z"]), (1, 2, 3))
        self.assertEqual((c["escala.x"], c["escala.y"], c["rotacion"], c["sesgo"]), (2, 3, 30, 5))
        self.assertEqual((c["pivote.x"], c["pivote.y"]), (0.5, -1))
        self.assertEqual(c["columnas"], {})

    def test_read_usa_offset(self):
        e = ESC.abrir_xml(cadena_simple(peg("P1"), r=read("Hoja", pos=(1, 2, 3))))
        c = Evaluador(e).canales("Top/Hoja", 1)
        self.assertEqual((c["offset.x"], c["offset.y"], c["offset.z"]), (1, 2, 3))
        self.assertNotIn("posicion.x", c)

    def test_escala_unica_si_no_separada(self):
        attrs = ('<scale><separate val="false" /><xy val="2.5" /><x val="9" /><y val="9" /></scale>')
        e = ESC.abrir_xml(cadena_simple(modulo("PEG", "P1", attrs)))
        c = Evaluador(e).canales("Top/P1", 1)
        self.assertEqual((c["escala.x"], c["escala.y"]), (2.5, 2.5))

    def test_rutas_aceptan_formas(self):
        e = ESC.abrir_xml(cadena_simple(peg("P1", pos=(4, 0, 0))))
        ev = Evaluador(e)
        for r in ("Top/P1", "/P1", "P1"):
            self.assertEqual(ev.canales(r, 1)["posicion.x"], 4)

    def test_valor_prioridad_columna_val_defecto(self):
        col = ('<column type="3" name="Col_X"><points version="2">'
               '<pt constSeg="false" x="1" yLocal="10" y="99" /><pt constSeg="false" x="11" yLocal="20" y="99" /></points></column>')
        attrs = ('<position><separate val="true" /><x col="Col_X" val="7" /><y val="3" defaultValue="1" /><z defaultValue="0.5" /></position>'
                 '<opacity val="80" defaultValue="100" />')
        e = ESC.abrir_xml(cadena_simple(modulo("PEG", "P1", attrs), columnas=col))
        ev = Evaluador(e)
        self.assertAlmostEqual(ev.valor("Top/P1", "position.x", 6), 15.0, delta=1e-6)       # columna, yLocal manda (P33)
        self.assertEqual(ev.valor("Top/P1", "position/y", 6), 3.0)                            # val
        self.assertEqual(ev.valor("Top/P1", "position.z", 6), 0.5)                            # defaultValue
        self.assertEqual(ev.valor("Top/P1", "opacity", 6), 80.0)
        self.assertIsNone(ev.valor("Top/P1", "no.existe", 6))
        self.assertIsNone(ev.valor("Top/NoHay", "opacity", 6))
        self.assertEqual(ev.canales("Top/P1", 6)["columnas"], {"posicion.x": "Col_X"})

    def test_valor_texto_si_no_es_numero(self):
        e = ESC.abrir_xml(cadena_simple(modulo("PEG", "P1", '<nota val="hola" />')))
        self.assertEqual(Evaluador(e).valor("Top/P1", "nota", 1), "hola")


class Cadena(unittest.TestCase):
    def setUp(self):
        self.e = ESC.abrir_xml(cadena_simple(peg("P1", pos=(1, 0, 2)), peg("P2", pos=(0, 1, 3))))
        self.ev = Evaluador(self.e)

    def test_cadena_del_read(self):
        self.assertEqual(self.ev.cadena("Top/Hoja"), ("Top/P2", "Top/P1"))
        self.assertEqual(self.ev.cadena("Top/Hoja", "nunca"), ("Top/P2", "Top/P1"))

    def test_cadena_propio_de_un_peg(self):
        self.assertEqual(self.ev.cadena("Top/P2"), ("Top/P2", "Top/P1"))
        self.assertEqual(self.ev.cadena("Top/P2", "nunca"), ("Top/P1",))
        self.assertEqual(self.ev.cadena("Top/P1", "nunca"), ())

    def test_propio_invalido(self):
        with self.assertRaises(ValueError):
            self.ev.cadena("Top/P1", "siempre")

    def test_transparentes_se_cruzan(self):
        nodos = [peg("P1", pos=(1, 0, 0)), modulo("CurveModule", "Curva"), modulo("PointConstraint2", "Pc"), peg("P2", pos=(0, 1, 0)),
                 read("Hoja"), modulo("COMPOSITE", "Comp")]
        cables = cable("P1", "Curva") + cable("Curva", "Pc") + cable("Pc", "P2") + cable("P2", "Hoja") + cable("Hoja", "Comp")
        ev = Evaluador(ESC.abrir_xml(xstage(nodos, cables)))
        self.assertEqual(ev.cadena("Top/Hoja"), ("Top/P2", "Top/P1"))

    def test_cadena_a_traves_de_grupo(self):
        g = grupo("G", [modulo("MULTIPORT_IN", "In"), peg("Pg", pos=(5, 0, 0)), modulo("MULTIPORT_OUT", "sin-nombre")],
                  cable("In", "Pg") + cable("Pg", "sin-nombre"))
        nodos = [peg("P1"), g, read("Hoja"), modulo("COMPOSITE", "Comp")]
        cables = cable("P1", "G") + cable("G", "Hoja") + cable("Hoja", "Comp")
        ev = Evaluador(ESC.abrir_xml(xstage(nodos, cables)))
        self.assertEqual(ev.cadena("Top/Hoja"), ("Top/G/Pg", "Top/P1"))
        fila = ev.nodos(1)[0]
        self.assertEqual(fila["matriz"][0][2], 5)

    def test_corte_en_read_termina_la_cadena(self):
        nodos = [peg("P0", pos=(7, 0, 9)), read("Otro"), peg("P1", pos=(1, 0, 2)), read("Hoja"), modulo("COMPOSITE", "Comp")]
        cables = cable("P0", "Otro") + cable("Otro", "P1") + cable("P1", "Hoja") + cable("Hoja", "Comp")
        ev = Evaluador(ESC.abrir_xml(xstage(nodos, cables)))
        self.assertEqual(ev.cadena("Top/Hoja"), ("Top/P1",))
        fila = {n["ruta"]: n for n in ev.nodos(1)}["Top/Hoja"]
        self.assertEqual(fila["z"], 2.0)                      # el PEG de más allá del otro READ no cuenta

    def test_read_cuya_entrada_es_composite_no_tiene_matriz(self):
        nodos = [read("Fuente"), modulo("COMPOSITE", "C1"), read("Hoja"), modulo("COMPOSITE", "C2")]
        cables = cable("Fuente", "C1") + cable("C1", "Hoja") + cable("Hoja", "C2")
        fila = {n["ruta"]: n for n in Evaluador(ESC.abrir_xml(xstage(nodos, cables))).nodos(1)}["Top/Hoja"]
        self.assertIsNone(fila["matriz"])
        self.assertEqual(fila["z"], 0.0)

    def test_ciclo_no_cuelga(self):
        nodos = [peg("A"), peg("B"), read("Hoja")]
        cables = cable("A", "B") + cable("B", "A") + cable("B", "Hoja")
        ev = Evaluador(ESC.abrir_xml(xstage(nodos, cables)))
        self.assertEqual(len(ev.cadena("Top/Hoja")) >= 1, True)
        ev.nodos(1)


class MatrizYZ(unittest.TestCase):
    def test_matriz_y_z_paridad(self):
        e = ESC.abrir_xml(cadena_simple(peg("P1", pos=(1, 2, 2), rot=90), peg("P2", pos=(3, 0, 3), esc=(2, 2)),
                                         r=read("Hoja", pos=(0, 0, 0.25))))
        f = Evaluador(e).nodos(1)[0]
        # P1: T(1,2)·R90 ; P2: T(3,0)·S2 ; en campos, sin conversión de unidades
        cerca(self, f["matriz"], [[0, -2, 1], [2, 0, 5]])
        self.assertAlmostEqual(f["z"], 5.25)
        self.assertEqual(f["dibujo"], "1")
        self.assertEqual(f["padre"], None)

    def test_peg_apagado_cuenta_en_paridad(self):
        e = ESC.abrir_xml(cadena_simple(peg("P1", pos=(1, 0, 2), apagado=True), peg("P2", pos=(0, 1, 3))))
        f = Evaluador(e).nodos(1)[0]
        self.assertAlmostEqual(f["z"], 5.0)                         # R7: apagados incluidos
        cerca(self, f["matriz"], [[1, 0, 1], [0, 1, 1]])
        self.assertTrue(f["dibujable"])

    def test_pivote(self):
        e = ESC.abrir_xml(cadena_simple(peg("P1", rot=90, piv=(1, 0))))
        f = Evaluador(e).nodos(1)[0]
        cerca(self, f["matriz"], [[0, -1, 1], [1, 0, -1]], 1e-12)       # T(piv)·R·T(-piv)

    def test_sesgo_ignorado_con_aviso(self):
        e = ESC.abrir_xml(cadena_simple(peg("P1", rot=0, sesgo=20)))
        f = Evaluador(e).nodos(1)[0]
        cerca(self, f["matriz"], [[1, 0, 0], [0, 1, 0]])                # R4
        self.assertTrue(any("sesgo" in a for a in f["avisos"]))

    def test_static_constraint(self):
        st = modulo("StaticConstraint", "Est", '<translate><x val="2" /><y val="3" /><z val="0.5" /></translate>'
                    '<scale><x val="2" /><y val="2" /></scale>')
        e = ESC.abrir_xml(xstage([peg("P1", pos=(1, 0, 1)), st, read("Hoja"), modulo("COMPOSITE", "Comp")],
                                  cable("P1", "Est") + cable("Est", "Hoja") + cable("Hoja", "Comp")))
        ev = Evaluador(e)
        self.assertEqual(ev.cadena("Top/Hoja"), ("Top/Est", "Top/P1"))
        c = ev.canales("Top/Est", 1)
        self.assertEqual((c["posicion.x"], c["posicion.z"], c["escala.x"]), (2, 0.5, 2))
        self.assertNotIn("pivote.x", c)
        f = ev.nodos(1)[0]
        cerca(self, f["matriz"], [[2, 0, 3], [0, 2, 3]])
        self.assertAlmostEqual(f["z"], 1.5)

    def test_orden_de_documento_y_filtros(self):
        nodos = [peg("P1"), read("B"), read("A"), modulo("READ", "SinDib"), modulo("COMPOSITE", "Comp")]
        cables = cable("P1", "B") + cable("P1", "A") + cable("B", "Comp") + cable("A", "Comp", pi=1)
        ev = Evaluador(ESC.abrir_xml(xstage(nodos, cables)))
        self.assertEqual([n["ruta"] for n in ev.nodos(1)], ["Top/B", "Top/A"])
        self.assertEqual([n["ruta"] for n in ev.nodos(1, solo_con_dibujo=False)], ["Top/B", "Top/A", "Top/SinDib"])
        self.assertEqual([n["ruta"] for n in ev.nodos(1, tipos=("PEG", "READ"))], ["Top/P1", "Top/B", "Top/A"])   # el filtro solo omite READ
        self.assertEqual(len(ev.nodos(1, tipos=("PEG", "READ"), solo_con_dibujo=False)), 4)
        self.assertEqual(len(ev.nodos(1, solo_con_dibujo=False, max=2)), 2)

    def test_padre_y_apagado(self):
        g = grupo("G", [grupo("H", [read("Hoja")], "")], "", apagado=True)
        e = ESC.abrir_xml(xstage([g, modulo("COMPOSITE", "Comp")], ""))
        f = Evaluador(e).nodos(1)[0]
        self.assertEqual(f["ruta"], "Top/G/H/Hoja")
        self.assertEqual(f["padre"], "G/H")                           # R9
        self.assertFalse(f["apagado"])                                # R8: solo la marca propia
        self.assertFalse(f["dibujable"])                              # A4-04: apagado_efectivo


class Posicion3D(unittest.TestCase):
    TRAY = ('<column type="2" name="Tray"><path3D useVeloX="true" useVeloY="true" useVeloZ="true" constantZ="false"><points>'
            '<pt val="0,0,0" lockedInTime="1"/><pt val="1,0,0" lockedInTime="5"/><pt val="1,0,0" lockedInTime="9"/><pt val="1,0,0" lockedInTime="13"/>'
            '</points></path3D><velocity type="3" name="Tray-V" anonymous="true"><points version="2">'
            '<pt constSeg="false" x="1" yLocal="0" y="0"/><pt constSeg="false" x="13" yLocal="1" y="1"/></points></velocity></column>')

    def peg_tray(self):
        attrs = '<position><separate val="false" /><attr3dpath col="Tray" /><x val="0" /><y val="0" /><z val="0" /></position>'
        return modulo("PEG", "P1", attrs)

    def test_puntos_repetidos_no_lanzan(self):
        """Regresión A4-08: puntos consecutivos repetidos no deben lanzar ZeroDivisionError (guarda A3-01)."""
        e = ESC.abrir_xml(cadena_simple(self.peg_tray(), columnas=self.TRAY))
        ev = Evaluador(e)
        for f in range(1, 14):
            c = ev.canales("Top/P1", f)
            self.assertTrue(all(math.isfinite(c[k]) for k in ("posicion.x", "posicion.y", "posicion.z")))
        self.assertEqual(ev.canales("Top/P1", 1)["posicion.x"], 0.0)
        self.assertAlmostEqual(ev.canales("Top/P1", 5)["posicion.x"], 1.0)
        self.assertEqual(ev.canales("Top/P1", 1)["columnas"]["posicion.x"], "Tray (3D path)")

    def test_volcar_peg(self):
        ev = Evaluador(ESC.abrir_xml(cadena_simple(self.peg_tray(), columnas=self.TRAY)))
        filas = ev.volcar_peg("Top/P1", 1, 13)
        self.assertEqual([x["f"] for x in filas], list(range(1, 14)))
        self.assertEqual(set(filas[0]), {"f", "posicion.x", "posicion.y", "posicion.z", "escala.x", "escala.y", "rotacion"})


class Dibujos(unittest.TestCase):
    def test_dibujo_ref(self):
        e = ESC.abrir_xml(cadena_simple(peg("P1")))
        d = Evaluador(e).dibujo("Top/Hoja", 3)
        self.assertEqual(d, DibujoRef(2, "Dib_A", "Dib_A", "1", "elements/Dib_A/Dib_A-1.tvg"))

    def test_sin_dibujo(self):
        e = ESC.abrir_xml(cadena_simple(peg("P1"), r=read("Hoja", col="NoExiste")))
        ev = Evaluador(e)
        self.assertIsNone(ev.dibujo("Top/Hoja", 1))
        self.assertEqual(ev.nodos(1), [])
        self.assertIsNone(ev.dibujo("Top/P1", 1))


if __name__ == "__main__":
    unittest.main()
