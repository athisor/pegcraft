"""Un READ dentro de un grupo apagado no se dibuja (planos con grupos de personajes apagados: 0,86 -> 0,31 al dibujarlos).
El lector separa `apagado` (bandera propia) de `dibujable` (= no apagado_efectivo); el horneado usa el efectivo."""
import unittest

from pegcraft.bake.apilado import apagado


class ApagadoGrupo(unittest.TestCase):
    def test_bandera_propia(self):
        self.assertTrue(apagado({"apagado": True, "dibujable": False}))

    def test_grupo_ancestro_apagado(self):
        self.assertTrue(apagado({"apagado": False, "dibujable": False}))

    def test_dibujable(self):
        self.assertFalse(apagado({"apagado": False, "dibujable": True}))

    def test_fila_sin_dibujable(self):
        self.assertFalse(apagado({"apagado": False}))
        self.assertTrue(apagado({"apagado": True}))


if __name__ == "__main__":
    unittest.main()
