"""Adaptador ``compat``: sin topes de READ (A8-01) y reglas de PEG apagado (A8-02, A8-03).

    python -I -m unittest discover -s tests/lector -p "test_compat.py"
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sightread.lector import compat
from sightread.lector.escena import limpiar_cache
from sightread.sintetico import generador as G


def escena_con_reads(n):
    nodos = [{"tipo": "READ", "nombre": f"Pieza_{i:04d}"} for i in range(n)] + [{"tipo": "COMPOSITE", "nombre": "Comp"}]
    enlaces = [{"origen": f"Pieza_{i:04d}", "destino": "Comp", "puerto_destino": i} for i in range(n)]
    cols = [{"nombre": f"Col_Pieza_{i:04d}", "tipo": 0, "elemento": 2, "secuencias": [{"cuadros": "1-24", "dibujo": "1"}]} for i in range(n)]
    return {"nombre": "muchos", "nodos": nodos, "enlaces": enlaces, "columnas": cols,
            "elementos": [{"id": 2, "nombre": "Dibujo_A", "carpeta": "Dibujo_A", "dibujos": ["1"]}]}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.n = 0
        limpiar_cache()

    @classmethod
    def tearDownClass(cls):
        limpiar_cache()
        cls.tmp.cleanup()

    def xstage(self, spec):
        type(self).n += 1
        p = Path(self.tmp.name) / f"e{self.n}.xstage"
        p.write_bytes(G.a_bytes(spec))
        return p


class SinTopes(Base):
    def test_los_topes_ya_no_existen(self):
        self.assertIsNone(compat.MAX_NODOS)
        self.assertIsNone(compat.MAX_READS)

    def test_dibujos_de_reads_no_recorta_a_500(self):
        xs = self.xstage(escena_con_reads(778))                 # el tamaño de plano A
        self.assertEqual(len(compat.dibujos_de_reads(xs)), 778)

    def test_nodos_evaluados_no_recorta_a_500_ni_a_2000(self):
        for n in (778, 2105):
            filas = compat.nodos_evaluados(self.xstage(escena_con_reads(n)), 1)
            self.assertEqual(len(filas), n)
            self.assertEqual(len({f["ruta"] for f in filas}), n)

    def test_el_tope_explicito_sigue_funcionando(self):
        xs = self.xstage(escena_con_reads(60))
        self.assertEqual(len(compat.nodos_evaluados(xs, 1, max=10)), 10)
        self.assertEqual(len(compat.dibujos_de_reads(xs, max=10)), 10)


sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_evaluar_ayuda import cable, modulo, peg, read, xstage          # noqa: E402
from sightread.lector.evaluar import Evaluador                           # noqa: E402


def cadena_dos_pegs(**kw):
    """P1 (apagado, z=2, trasladado, escalado) -> P2 (z=3, traslación 1) -> Hoja -> Comp."""
    p1 = peg("P1", pos=(10, 4, 2), esc=(2, 2), rot=30, apagado=True)
    p2 = peg("P2", pos=(1, 0, 3))
    nodos = [p1, p2, read("Hoja"), modulo("COMPOSITE", "Comp")]
    return xstage(nodos, cable("P1", "P2") + cable("P2", "Hoja") + cable("Hoja", "Comp"), **kw)


class PegApagado(Base):
    def abrir(self, texto):
        type(self).n += 1
        p = Path(self.tmp.name) / f"p{self.n}.xstage"
        p.write_text(texto, encoding="utf-8")
        return p

    def test_valores_por_omision_de_cada_modo(self):
        e = compat.escena(self.abrir(cadena_dos_pegs()))
        self.assertEqual(Evaluador(e).peg_apagado, "cuenta")
        self.assertEqual(Evaluador(e, modo="harmony").peg_apagado, "identidad")
        with self.assertRaises(ValueError):
            Evaluador(e, peg_apagado="otro")

    def test_cadena_con_peg_apagado_en_ambos_valores(self):
        xs = self.abrir(cadena_dos_pegs())
        self.assertAlmostEqual(compat.nodos_evaluados(xs, 1)[0]["z"], 5.0, delta=1e-9)                              # omisión de paridad: cuenta
        self.assertAlmostEqual(compat.nodos_evaluados(xs, 1, peg_apagado="cuenta")[0]["z"], 5.0, delta=1e-9)
        ident = compat.nodos_evaluados(xs, 1, peg_apagado="identidad")[0]
        self.assertAlmostEqual(ident["z"], 3.0, delta=1e-9)
        # la matriz de la cadena con P1 apagado = la de una cadena sin P1: solo traslación de P2 (1, 0)
        m = ident["matriz"]
        self.assertAlmostEqual(m[0][2], 1.0, delta=1e-9)
        self.assertAlmostEqual(m[1][2], 0.0, delta=1e-9)
        self.assertAlmostEqual(m[0][0], 1.0, delta=1e-9)
        cuenta = compat.nodos_evaluados(xs, 1, peg_apagado="cuenta")[0]["matriz"]
        self.assertNotAlmostEqual(cuenta[0][0], 1.0, delta=1e-3)                                                    # P1 sí transformaba

    def test_identidad_no_activa_el_resto_del_modo_harmony(self):
        """Con paridad + identidad el sesgo sigue sin aplicarse (R4) aunque el PEG apagado sea identidad."""
        p = peg("P1", sesgo=20, esc=(2, 1))
        txt = xstage([p, read("Hoja"), modulo("COMPOSITE", "Comp")], cable("P1", "Hoja") + cable("Hoja", "Comp"))
        xs = self.abrir(txt)
        par = compat.nodos_evaluados(xs, 1, peg_apagado="identidad")[0]["matriz"]
        har = Evaluador(compat.escena(xs), modo="harmony").nodos(1)[0]["matriz"]
        self.assertAlmostEqual(par[0][1], 0.0, delta=1e-9)             # sin sesgo en paridad
        self.assertNotAlmostEqual(har[0][1], 0.0, delta=1e-3)          # con sesgo en harmony

    def test_harmony_acepta_cuenta_explicito(self):
        xs = self.abrir(cadena_dos_pegs())
        e = compat.escena(xs)
        self.assertAlmostEqual(Evaluador(e, modo="harmony").nodos(1)[0]["z"], 3.0, delta=1e-9)
        self.assertAlmostEqual(Evaluador(e, modo="harmony", peg_apagado="cuenta").nodos(1)[0]["z"], 5.0, delta=1e-9)

    def test_peg_de_camara_apagado(self):
        cam = peg("Cam", pos=(3, 2, 1), esc=(2, 4), rot=15, apagado=True)
        vivo = peg("CamOn", pos=(3, 2, 1), esc=(2, 4), rot=15)
        xs = self.abrir(xstage([cam, vivo, read("Hoja"), modulo("COMPOSITE", "Comp")], cable("Hoja", "Comp")))
        ident = {"f": 1, "posicion.x": 0.0, "posicion.y": 0.0, "posicion.z": 0.0, "escala.x": 1.0, "escala.y": 1.0, "rotacion": 0.0}
        self.assertEqual(compat.fila_peg(xs, "Top/Cam", 1, peg_apagado="identidad"), ident)
        crudo = compat.fila_peg(xs, "Top/Cam", 1)                                    # omisión de paridad: canales crudos
        self.assertEqual((crudo["posicion.x"], crudo["escala.y"], crudo["rotacion"]), (3.0, 4.0, 15.0))
        self.assertEqual(compat.fila_peg(xs, "Top/Cam", 1, peg_apagado="cuenta"), crudo)
        self.assertEqual(compat.fila_peg(xs, "Top/CamOn", 1, peg_apagado="identidad"), crudo)   # un PEG encendido no cambia

    def test_volcar_peg_en_modo_harmony_respeta_el_apagado(self):
        xs = self.abrir(cadena_dos_pegs())
        filas = Evaluador(compat.escena(xs), modo="harmony").volcar_peg("Top/P1", 1, 3)
        self.assertTrue(all(f["posicion.z"] == 0.0 and f["escala.x"] == 1.0 and f["rotacion"] == 0.0 for f in filas))
        self.assertEqual([f["f"] for f in filas], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
