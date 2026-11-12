"""Pruebas contra lo medido en Harmony 24 (A7b-01..A7b-10); sección `medicion` de los fixtures `tests/fixtures/lector/casos/c*.esperado.json` y regla de la
velocity de una trayectoria 3D fuera de rango / normalizada por tramo (c19; sondas s1-s3 reducidas a escenas mínimas).
Correr desde la raíz del repo:  python -I -m unittest discover -s tests\\lector\\columnas -p "test_medicion_a7b.py" -v
"""
import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
from pegcraft.lector import abrir  # noqa: E402
from pegcraft.lector.columnas import leer_columnas  # noqa: E402
from pegcraft.lector.evaluar import Evaluador  # noqa: E402

CASOS = RAIZ / "tests" / "fixtures" / "lector" / "casos"
TOL = 5e-5          # error de lectura de Harmony (z cuantizada 3,4e-5 campos) más el redondeo de la trayectoria


class MedicionHarmony(unittest.TestCase):
    """Matriz (en campos) y Z de cada PEG/READ medidos con getMatrix, contra el Evaluador en modo "harmony"."""

    def test_los_casos_medidos(self):
        archivos = sorted(CASOS.glob("c*.esperado.json"))
        if not archivos:
            self.skipTest("sin fixtures")
        comparados = 0
        for p in archivos:
            caso = p.name[: -len(".esperado.json")]
            medicion = json.loads(p.read_text(encoding="utf-8")).get("medicion", {})
            if medicion.get("estado") != "medido":
                continue
            ev = Evaluador(abrir(str(CASOS / (caso + ".xstage"))), modo="harmony")
            for ruta, nodo in medicion["nodos"].items():
                for f, d in nodo["fotogramas"].items():
                    if "matriz" not in d:
                        continue
                    filas = {r["ruta"]: r for r in ev.nodos(int(f), tipos=("READ", "PEG"), solo_con_dibujo=False)}
                    fila = filas.get(ruta)
                    if fila is None or fila.get("matriz") is None:
                        continue
                    err = max(abs(fila["matriz"][i][j] - d["matriz"][i][j]) for i in range(2) for j in range(3))
                    err = max(err, abs(fila.get("z", 0.0) - d["z"]))
                    self.assertLessEqual(err, TOL, f"{caso} {ruta} f{f}")
                    comparados += 1
        self.assertGreater(comparados, 100)


def escena(puntos, vel, attrs=""):
    pts = "".join(f"<pt val='{v}' lockedInTime='{t}'/>" for t, v in puntos)
    ys = "".join(f"<pt x='{x}' y='{y}'/>" for x, y in vel)
    xml = (f"<scene name='Top'><columns><column type='2' name='T'><path3D {attrs}><points>{pts}</points></path3D>"
           f"<velocity type='3' name='v' anonymous='true'><points version='2'>{ys}</points></velocity></column></columns></scene>")
    return leer_columnas(ET.fromstring(xml))["T"]


COLINEAL = [(1, "0,0,0"), (13, "2,0,0"), (25, "10,0,0")]       # el punto 2 está en la fracción 0,2 de la longitud
C19 = [(1, 0.0), (7, 1.3), (13, 0.5), (19, -0.3), (25, 1.0)]


class VelocityPorTramo(unittest.TestCase):
    def xs(self, c, cuadros):
        return [c.posicion(f)[0] for f in cuadros]

    def test_sin_llave_de_velocity_en_la_llave_fija_manda_la_fraccion_global(self):      # s1
        c = escena(COLINEAL, [(1, 0.0), (25, 1.0)])
        self.assertAlmostEqual(c.posicion(7)[0], 10 * 0.25, places=3)          # v = 0,25 de la longitud total (llave fija en 13 no cuenta)
        self.assertAlmostEqual(c.posicion(13)[0], 2.0, places=6)               # la llave fija manda en su cuadro

    def test_llaves_de_velocity_que_no_coinciden_con_la_fraccion_normalizan_por_tramo(self):   # s2
        c = escena(COLINEAL, [(1, 0.0), (13, 0.5), (25, 1.0)])
        self.assertAlmostEqual(c.posicion(7)[0], 1.0, places=6)               # v = 0,25 -> mitad del tramo 1 (0 a 2)
        self.assertAlmostEqual(c.posicion(19)[0], 6.0, places=6)              # mitad del tramo 2 (2 a 10)

    def test_sobreimpulso_no_extrapola_ni_retrocede(self):                      # c19 / s3
        c = escena(COLINEAL, C19)
        self.assertAlmostEqual(c.posicion(4)[0], 1.0, places=6)               # v 0 -> 1,3 en 7 recorre el tramo 1: mitad en el cuadro 4
        for f in range(7, 20):
            self.assertAlmostEqual(c.posicion(f)[0], 2.0, places=6, msg=f"f{f}")   # se queda en el punto 2 entre el 7 y el 19
        self.assertAlmostEqual(c.posicion(22)[0], 6.0, places=6)              # -0,3 -> 1 entre 19 y 25: mitad en el 22
        self.assertAlmostEqual(c.posicion(25)[0], 10.0, places=6)
        for f in range(1, 26):
            self.assertTrue(0.0 - 1e-9 <= c.posicion(f)[0] <= 10.0 + 1e-9)

    def test_fraccion_global_fuera_de_rango_se_recorta(self):                  # no medido: no extrapola
        c = escena([(1, "0,0,0"), (13, "10,0,0")], [(1, -0.5), (13, 1.5)])
        self.assertAlmostEqual(c.posicion(1)[0], 0.0, places=6)
        self.assertLessEqual(max(c.posicion(f)[0] for f in range(1, 14)), 10.0 + 1e-9)


class BezierSinManijas(unittest.TestCase):
    def test_tramo_de_dos_cuadros_sin_manijas_da_el_punto_medio_con_puntos_en_orden_de_valor(self):
        # Harmony guarda los puntos ordenados por y (no por x) y omite los atributos nulos (P32). Regla medida: manijas
        # ausentes = 0 -> cúbica sin manijas -> el cuadro interior de un tramo de 2 cuadros vale el punto medio exacto.
        pts = ("<pt constSeg='false' x='528' yLocal='-49.5' y='-49.5'/><pt constSeg='true' x='1' yLocal='-100' y='-100'/>"
               "<pt constSeg='true' x='526' yLocal='-50.8' y='-50.8'/><pt constSeg='true' x='530' yLocal='-44.25' y='-44.25'/>"
               "<pt constSeg='true' x='532' yLocal='-17.0' y='-17.0'/>")
        xml = f"<scene name='Top'><columns><column type='3' name='A'><points version='2'>{pts}</points></column></columns></scene>"
        c = leer_columnas(ET.fromstring(xml))["A"]
        self.assertAlmostEqual(c.valor(529), (-49.5 + -44.25) / 2, places=9)
        self.assertEqual(c.valor(527), -50.8)
        self.assertEqual(c.valor(531), -44.25)


if __name__ == "__main__":
    unittest.main()
