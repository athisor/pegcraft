"""Evaluador contra los valores esperados de los casos sintéticos (tests/fixtures/lector/casos/*.esperado.json).

Compara lo evaluable: canales, cadena, Z, matriz, dibujo, padre, apagado. Los valores ``null`` del esperado ("sin referencia") se saltan.
Excepción documentada: en ``cadena`` el esperado incluye al READ propio cuando tiene transformación propia; el Evaluador
nunca lo incluye en la cadena (R6, A4-03), así que aquí se compara sin el READ propio.

    python -I -m unittest discover -s tests -p "test_evaluar*.py"
"""
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pegcraft.lector import abrir
from pegcraft.lector.evaluar import Evaluador

CASOS = Path(__file__).resolve().parents[1] / "fixtures" / "lector" / "casos"
TOL = 1e-6
# c09, f=11: el esperado dice "entre dos llaves iguales la posición es constante" (x=1). Con la columna `velocity` del propio caso
# (fracción 10/12 de una trayectoria de largo 1, P34) la posición es x=0,8333. Sin medición en Harmony se deja fuera y se informa.
ESPERADO_DISCUTIDO = {("c09_puntos_coincidentes", 11)}


def _cerca(a, b, tol=TOL):
    return abs(float(a) - float(b)) <= tol


class FixturesEvaluar(unittest.TestCase):
    def test_hay_casos(self):
        self.assertGreaterEqual(len(list(CASOS.glob("*.esperado.json"))), 10)

    def test_casos(self):
        for esp_path in sorted(CASOS.glob("*.esperado.json")):
            caso = esp_path.name[: -len(".esperado.json")]
            esp = json.loads(esp_path.read_text(encoding="utf-8"))
            e = abrir(CASOS / (caso + ".xstage"))
            ev = Evaluador(e)
            for fs, nodos in esp["evaluacion"].items():
                f = int(fs)
                for ruta, x in nodos.items():
                    with self.subTest(caso=caso, f=f, ruta=ruta):
                        fila = {n["ruta"]: n for n in ev.nodos(f, tipos=(x["tipo"],), solo_con_dibujo=False)}[ruta]
                        self.assertEqual(fila["padre"], x["padre"])
                        self.assertEqual(fila["apagado"], x["apagado"])
                        self.assertEqual(fila["dibujable"], not x["apagado_efectivo"])
                        if x["z"] is not None:
                            self.assertTrue(_cerca(fila["z"], x["z"]), (fila["z"], x["z"]))
                        if x["matriz"] is not None:
                            for i in range(2):
                                for j in range(3):
                                    self.assertTrue(_cerca(fila["matriz"][i][j], x["matriz"][i][j]), (fila["matriz"], x["matriz"]))
                        elif x["cortada"]:
                            self.assertIsNone(fila["matriz"])
                        if x["canales"] is not None and (caso, f) not in ESPERADO_DISCUTIDO:
                            c = ev.canales(ruta, f)
                            for k, v in x["canales"].items():
                                self.assertTrue(_cerca(c[k], v), (k, c[k], v))
                        esperada = [r for r in x["cadena"] if not (x["tipo"] == "READ" and r == ruta)]
                        self.assertEqual(list(ev.cadena(ruta)), esperada)
                        if x["tipo"] == "READ" and x.get("dibujo") is not None:
                            d = ev.dibujo(ruta, f)
                            self.assertIsNotNone(d)
                            self.assertEqual({"elemento_id": d.elemento_id, "elemento": d.elemento, "carpeta": d.carpeta, "dibujo": d.dibujo,
                                              "ruta_relativa": d.ruta_relativa}, x["dibujo"])
                            self.assertEqual(fila["dibujo"], x["dibujo"]["dibujo"])


if __name__ == "__main__":
    unittest.main()
