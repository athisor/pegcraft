"""Modo "harmony" del Evaluador (medido en Harmony): casos A4-01, A4-03, A4-05 y la regla de unidades A4-02 convertidos a escenas
sintéticas. Valores esperados calculados a mano / tomados de las mediciones (tolerancia de la medición: 5e-6).

    python -I -m unittest discover -s tests/lector -p "test_evaluar_harmony.py"
"""
import math
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sightread.lector.evaluar import Evaluador
from test_evaluar_ayuda import Escenas, cable, grupo, modulo, peg, read, xstage

ESC = Escenas()
KX, KY = 1 / 9, 1 / 12          # 4:3, 24x24x12 (P34)


def tearDownModule():
    ESC.cerrar()


def cadena(*pegs, r=None, **kw):
    nodos = list(pegs) + [r or read("Hoja"), modulo("COMPOSITE", "Comp")]
    nombres = ["P1", "P2", "P3"][: len(pegs)] + ["Hoja"]
    cables = "".join(cable(a, b) for a, b in zip(nombres, nombres[1:])) + cable("Hoja", "Comp")
    return xstage(nodos, cables, **kw)


def fila(texto, modo, f=1):
    return Evaluador(ESC.abrir_xml(texto), modo=modo).nodos(f)[0]


class Modo(unittest.TestCase):
    def test_modo_invalido(self):
        with self.assertRaises(ValueError):
            Evaluador(ESC.abrir_xml(cadena(peg("P1"))), modo="otro")

    def test_por_omision_es_paridad(self):
        self.assertEqual(Evaluador(ESC.abrir_xml(cadena(peg("P1")))).modo, "paridad")


class Q1PegApagado(unittest.TestCase):
    """A4-01: un PEG con marca propia de apagado es una identidad (no transforma ni suma Z)."""

    def textos(self):
        p1 = peg("P1", pos=(1, 0.5, 2), rot=20)
        p2 = peg("P2", pos=(2, 1, 3), rot=30, esc=(2, 3), apagado=True)
        p3 = peg("P3", pos=(-1, 0.25, 5), rot=-10, esc=(1.5, 1.5))
        ref = xstage([peg("P1", pos=(1, 0.5, 2), rot=20), p3, read("Hoja"), modulo("COMPOSITE", "Comp")],
                     cable("P1", "P3") + cable("P3", "Hoja") + cable("Hoja", "Comp"))
        return cadena(p1, p2, p3), ref

    def test_harmony_equivale_a_la_cadena_sin_p2(self):
        con, sin = self.textos()
        a, b = fila(con, "harmony"), fila(sin.replace("P3", "P3"), "paridad")
        # la cadena de referencia (sin P2) en paridad usa la misma geometría que en harmony cuando no hay sesgo y KX=KY: se compara en harmony
        b = fila(sin, "harmony")
        self.assertAlmostEqual(a["z"], 7.0, delta=1e-9)
        self.assertAlmostEqual(a["z"], b["z"], delta=1e-9)
        for i in range(2):
            for j in range(3):
                self.assertAlmostEqual(a["matriz"][i][j], b["matriz"][i][j], delta=1e-9)

    def test_paridad_cuenta_el_apagado(self):
        con, _ = self.textos()
        self.assertAlmostEqual(fila(con, "paridad")["z"], 10.0, delta=1e-9)       # R7 (convención de compatibilidad: el PEG apagado suma su Z)

    def test_los_tres_apagados_dan_identidad(self):
        t = cadena(peg("P1", pos=(1, 0.5, 2), apagado=True), peg("P2", pos=(2, 1, 3), apagado=True), peg("P3", pos=(5, 5, 5), apagado=True))
        f = fila(t, "harmony")
        self.assertEqual(f["z"], 0.0)
        self.assertEqual(f["matriz"], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    def test_el_apagado_propio_del_peg_no_el_de_grupo(self):
        """A4-04: la marca de un grupo no cambia la matriz; solo decide si se dibuja."""
        g = grupo("G", [modulo("MULTIPORT_IN", "In"), peg("Pg", pos=(1, 0, 4)), modulo("MULTIPORT_OUT", "Out")],
                  cable("In", "Pg") + cable("Pg", "Out"), apagado=True)
        t = xstage([peg("P1", pos=(2, 0, 1)), g, read("Hoja"), modulo("COMPOSITE", "Comp")],
                   cable("P1", "G") + cable("G", "Hoja") + cable("Hoja", "Comp"))
        f = fila(t, "harmony")
        self.assertAlmostEqual(f["z"], 5.0, delta=1e-9)                # el PEG de un grupo apagado sigue transformando
        self.assertTrue(f["dibujable"])                                # el READ está fuera del grupo
        dentro = xstage([grupo("G", [read("Hoja")], "", apagado=True), modulo("COMPOSITE", "Comp")], "")
        for modo in ("paridad", "harmony"):
            self.assertFalse(fila(dentro, modo)["dibujable"])


class Q3ReadPropio(unittest.TestCase):
    """A4-03 y A4-02: READ con offset/pivote/rotación/escala; matriz medida en espacio de matriz y convertida a campos con F = D⁻¹·M·D."""

    def test_todo_el_read(self):
        # medido (espacio de matriz): [[1.732, -1.5, 0.3353], [1.0, 2.598, -0.4191]], z = 4·KZ  (offset 1,5/-0,5/4, pivote 1/2, rot 30, esc 2/3)
        r = read("Hoja", pos=(1.5, -0.5, 4), rot=30, esc=(2, 3), piv=(1, 2))
        f = fila(xstage([r, modulo("COMPOSITE", "Comp")], cable("Hoja", "Comp")), "harmony")
        m_matriz = [[1.732, -1.5, 0.3353], [1.0, 2.598, -0.4191]]
        esperada = [[m_matriz[0][0], m_matriz[0][1] * KY / KX, m_matriz[0][2] / KX],
                    [m_matriz[1][0] * KX / KY, m_matriz[1][1], m_matriz[1][2] / KY]]
        for i in range(2):
            for j in range(3):
                self.assertAlmostEqual(f["matriz"][i][j], esperada[i][j], delta=5e-3)
        self.assertAlmostEqual(f["matriz"][0][1], -1.125, delta=1e-3)       # ejemplo medido (A4-03)
        self.assertAlmostEqual(f["z"], 4.0, delta=1e-9)

    def test_posicion_bajo_padre_girado_no_es_isotropa(self):
        """Hijo con posición x=1 bajo un padre girado 90°: sube 1,333 campos en y (no 1) con 4:3."""
        t = cadena(peg("P1", rot=90), peg("P2", pos=(1, 0, 0)))
        f = fila(t, "harmony")
        self.assertAlmostEqual(f["matriz"][1][2], 4 / 3, delta=1e-9)
        self.assertAlmostEqual(f["matriz"][0][2], 0.0, delta=1e-9)
        self.assertAlmostEqual(fila(t, "paridad")["matriz"][1][2], 1.0, delta=1e-9)

    def test_metrica_isotropa_coincide_con_paridad(self):
        t = cadena(peg("P1", pos=(1, 2, 0), rot=33, esc=(2, 1.5)), peg("P2", pos=(0.5, -1, 0), rot=-12), metricas=(1, 1, 24, 24, 12))
        a, b = fila(t, "harmony"), fila(t, "paridad")
        for i in range(2):
            for j in range(3):
                self.assertAlmostEqual(a["matriz"][i][j], b["matriz"][i][j], delta=1e-9)


class Q5aSesgo(unittest.TestCase):
    """A4-05: K(θ) = [[1, sin θ], [0, cos θ]], orden R·K·S; el READ sesga igual."""

    def lineal(self, f):
        return [row[:2] for row in f["matriz"]]

    def esperado(self, rot, sesgo, esc):
        t, k = math.radians(rot), math.radians(sesgo)
        R = [[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]]
        K = [[1, math.sin(k)], [0, math.cos(k)]]
        S = [[esc[0], 0], [0, esc[1]]]
        mm = lambda a, b: [[sum(a[i][m] * b[m][j] for m in range(2)) for j in range(2)] for i in range(2)]   # noqa: E731
        return mm(mm(R, K), S)

    def test_peg_con_sesgo(self):
        t = cadena(peg("P1", rot=20, sesgo=15, esc=(2, 1.5)), metricas=(1, 1, 24, 24, 12))
        f = fila(t, "harmony")
        e = self.esperado(20, 15, (2, 1.5))
        for i in range(2):
            for j in range(2):
                self.assertAlmostEqual(f["matriz"][i][j], e[i][j], delta=1e-9)
        self.assertEqual(f["avisos"], [])

    def test_read_con_sesgo(self):
        r = read("Hoja", rot=-30, sesgo=25, esc=(1, 3))
        f = fila(xstage([r, modulo("COMPOSITE", "Comp")], cable("Hoja", "Comp"), metricas=(1, 1, 24, 24, 12)), "harmony")
        e = self.esperado(-30, 25, (1, 3))
        for i in range(2):
            for j in range(2):
                self.assertAlmostEqual(f["matriz"][i][j], e[i][j], delta=1e-9)

    def test_paridad_ignora_el_sesgo(self):
        t = cadena(peg("P1", rot=20, sesgo=15, esc=(2, 1.5)), metricas=(1, 1, 24, 24, 12))
        f = fila(t, "paridad")
        e = self.esperado(20, 0, (2, 1.5))
        for i in range(2):
            for j in range(2):
                self.assertAlmostEqual(f["matriz"][i][j], e[i][j], delta=1e-9)
        self.assertTrue(any("sesgo" in a for a in f["avisos"]))


class Dibujable(unittest.TestCase):
    def test_campo_en_ambos_modos(self):
        t = xstage([read("A"), read("B", apagado=True), modulo("COMPOSITE", "Comp")], "")
        for modo in ("paridad", "harmony"):
            filas = {n["ruta"]: n for n in Evaluador(ESC.abrir_xml(t), modo=modo).nodos(1)}
            self.assertTrue(filas["Top/A"]["dibujable"])
            self.assertFalse(filas["Top/B"]["dibujable"])
            self.assertTrue(filas["Top/B"]["apagado"])


if __name__ == "__main__":
    unittest.main()
