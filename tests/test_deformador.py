"""deformador (spike parametrico): evaluador contra bake/deformadores.deformar_svg, ida y vuelta JSON, refinado.py. Sin Harmony ni escenas."""
import os, sys, json, tempfile, unittest
import numpy as np
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pegcraft.bake import deformadores as D
from pegcraft.deformador import evaluador as EV, refinado as RF, esquema as ES

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-1875 -1875 3750 3750"><g id="colour">'
       '<path d="M 100.000 20.000 L 220.000 20.000 C 250.000 30.000 280.000 60.000 300.000 90.000 L 300.000 -40.000 Z" fill="#123456"/>'
       '<path d="M 50.000 -10.000 C 80.000 -30.000 120.000 -30.000 150.000 -10.000 Z"/></g></svg>')


def _nodo(tipo, rep, act, **kw):
    d = {"ruta": "Top/x/" + tipo, "tipo": tipo, "reposo": rep, "pose": act}
    d.update(kw)
    return d


def spec(pose_curva=None):
    rep_c = {"offset/x": 2.0, "offset/y": 0.0, "length0": 0.5, "orientation0": 0.0, "length1": 0.5, "orientation1": 0.0}
    act_c = {"offset/x": 2.0, "offset/y": 0.8, "length0": 0.5, "orientation0": 25.0, "length1": 0.6, "orientation1": 40.0} if pose_curva is None else pose_curva
    rep_o = {"offset/x": 0.0, "offset/y": 0.0, "orientation": 0.0}
    return {"version": 1, "read": "Top/x/R", "fotograma": 1, "A": 4.0 / 3.0, "div": 156.25,
            "segmentos": [{"pegs": [], "pre": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                           "nodos": [_nodo("OffsetModule", rep_o, dict(rep_o)), _nodo("CurveModule", rep_c, act_c)]}]}


class TestEvaluador(unittest.TestCase):
    def _aplastado(self, sp):
        with tempfile.TemporaryDirectory() as t:
            a, b = os.path.join(t, "a.svg"), os.path.join(t, "b.svg")
            open(a, "w", encoding="utf-8").write(SVG)
            D.deformar_svg(a, b, EV.construir(sp))
            return open(b, encoding="utf-8").read()

    def test_texto_identico_al_aplastado(self):
        sp = spec()
        self.assertEqual(EV.deformar(EV.Plantilla(SVG), sp), self._aplastado(sp))

    def test_json_ida_y_vuelta(self):
        sp = spec()
        sp2 = json.loads(json.dumps(sp))
        self.assertEqual(EV.deformar(EV.Plantilla(SVG), sp2), EV.deformar(EV.Plantilla(SVG), sp))

    def test_pose_igual_reposo_es_identidad(self):
        rep = {"offset/x": 2.0, "offset/y": 0.0, "length0": 0.5, "orientation0": 0.0, "length1": 0.5, "orientation1": 0.0}
        pl = EV.Plantilla(SVG)
        Q = EV.deformar_puntos(pl, spec(rep))
        self.assertLess(float(np.abs(Q - pl.P).max()), 1e-6)

    def test_pose_distinta_mueve(self):
        pl = EV.Plantilla(SVG)
        self.assertGreater(float(np.abs(EV.deformar_puntos(pl, spec()) - pl.P).max()), 1.0)

    def test_plantilla_se_reutiliza(self):
        pl = EV.Plantilla(SVG)
        a = EV.deformar(pl, spec())
        b = EV.deformar(pl, spec({"offset/x": 2.0, "offset/y": 0.3, "length0": 0.5, "orientation0": 5.0, "length1": 0.5, "orientation1": 5.0}))
        self.assertNotEqual(a, b)
        self.assertEqual(EV.deformar(pl, spec()), a)

    def test_piezas_deformadas_nombres(self):
        with tempfile.TemporaryDirectory() as t:
            e = {"piezas": [{"id": "A", "dibujo": "dibujos/Cola-2__def_Cola.svg", "recorte": [{"mattes": [{"id": "B", "dibujo": "dibujos/M-1__def_M.svg"}]}]},
                            {"id": "C", "dibujo": "dibujos/Z-1.svg"}]}
            p = os.path.join(t, "escena.json"); json.dump(e, open(p, "w"))
            self.assertEqual(ES.piezas_deformadas(p), {"A": ("dibujos/Cola-2__def_Cola.svg", "dibujos/Cola-2.svg"), "B": ("dibujos/M-1__def_M.svg", "dibujos/M-1.svg")})


class TestRefinado(unittest.TestCase):
    """El parche del spike (refinado.py) parte del modelo antiguo (muestreo): se apaga el nativo mientras corren."""
    def setUp(self):
        self._ref, D.REFINADO = D.REFINADO, False

    def tearDown(self):
        D.REFINADO = self._ref

    def test_parche_se_restaura(self):
        ini, pun = D.Deformador.__init__, D.Deformador.puntos
        with RF.parche():
            self.assertIsNot(D.Deformador.puntos, pun)
        self.assertIs(D.Deformador.__init__, ini)
        self.assertIs(D.Deformador.puntos, pun)
        self.assertFalse(hasattr(D.Deformador, "_puntos_orig"))

    def test_identidad_y_cercano_al_muestreado(self):
        pl = EV.Plantilla(SVG)
        with RF.parche():
            Qi = EV.deformar_puntos(pl, spec({"offset/x": 2.0, "offset/y": 0.0, "length0": 0.5, "orientation0": 0.0, "length1": 0.5, "orientation1": 0.0}))
            Qf = EV.deformar_puntos(pl, spec())
        self.assertLess(float(np.abs(Qi - pl.P).max()), 1e-4)
        Qm = EV.deformar_puntos(pl, spec())
        self.assertLess(float(np.abs(Qf - Qm).max()), 3.0)     # el muestreo de 160 puntos/segmento difiere poco en un eje corto sin KinematicOutput

    def test_independiente_del_muestreo(self):
        pl = EV.Plantilla(SVG)
        ant = D.MUESTRAS
        try:
            with RF.parche():
                D.MUESTRAS = 16; a = EV.deformar_puntos(pl, spec())
                D.MUESTRAS = 160; b = EV.deformar_puntos(pl, spec())
        finally:
            D.MUESTRAS = ant
        self.assertLess(float(np.abs(a - b).max()), 0.05)


class TestRefinadoNativo(unittest.TestCase):
    """bake/deformadores.py trae la proyeccion continua (PEGCRAFT_DEF_REFINADO, def. si): oraculo contra el spike (refinado.parche) y apagado."""
    def _con(self, refinado, muestras=None, sp=None):
        ref, mg = D.REFINADO, D.MUESTRAS_GRUESO
        try:
            D.REFINADO = refinado
            if muestras:
                D.MUESTRAS_GRUESO = muestras
            return EV.deformar_puntos(EV.Plantilla(SVG), sp or spec())
        finally:
            D.REFINADO, D.MUESTRAS_GRUESO = ref, mg

    def test_igual_al_spike(self):
        pl = EV.Plantilla(SVG)
        ref0 = D.REFINADO
        try:
            D.REFINADO = False          # el parche del spike parte del modelo antiguo
            with RF.parche():
                ref = EV.deformar_puntos(pl, spec())
        finally:
            D.REFINADO = ref0
        # nativo: 16 muestras gruesas en vez de 160; la celda fina da el mismo t
        self.assertLess(float(np.abs(self._con(True) - ref).max()), 0.1)

    def test_grueso_16_igual_160(self):
        self.assertLess(float(np.abs(self._con(True, 16) - self._con(True, 160)).max()), 0.1)   # unidades tvg (1 px ~ 2): subpixel

    def test_apagado_es_el_muestreo_de_antes(self):
        a = self._con(False)
        self.assertLess(float(np.abs(a - self._con(False, 16)).max()), 1e-9)   # apagado no usa MUESTRAS_GRUESO
        self.assertLess(float(np.abs(a - self._con(True)).max()), 3.0)         # eje corto sin rigido: ambos cercanos

    def test_rigido_punta_analitica(self):
        sp = spec()
        sp["segmentos"][0]["nodos"][1]["cinematico"] = True
        a, b = self._con(False, sp=sp), self._con(True, sp=sp)
        self.assertTrue(np.isfinite(b).all())
        self.assertLess(float(np.abs(a - b).max()), 5.0)   # misma transformacion rigida; solo cambia la tangente de la punta

    def test_clave_del_almacen_distingue_modelo(self):
        self.assertEqual(D.MODELO, ("|ref%d" % D.MUESTRAS_GRUESO) if D.REFINADO else "")


class TestAvisosNoModelado(unittest.TestCase):
    """deformadores.avisos_no_modelados: solo avisos, sin tocar el resultado (nodos sinteticos con los valores de un caso medido)."""
    def _nodo(self, tipo, ruta, **kw):
        d = {"ruta": ruta, "tipo": tipo, "delta": 1.0, "rep": {"orientation": 0.0}}
        d.update(kw)
        return d

    def _caso(self, nodos, extra=()):
        seg = [{"pegs": [], "nodos": nodos}]
        return {"Top/R": list(nodos) + list(extra)}, {"Top/R": seg}

    def test_modelado_no_avisa(self):
        cen, segs = self._caso([self._nodo("OffsetModule", "Top/g/Offset", localreferential="false"),
                                self._nodo("CurveModule", "Top/g/Curve", localreferential="false", influencetype="INFINITE_INFLUENCE")],
                               [self._nodo("DeformationCompositeModule", "Top/g/Comp", vals={"outputkinematicchainselector": "RIGHTMOST", "outputmatrixonly": "false"}, puertos_usados=[0])])
        self.assertEqual(D.avisos_no_modelados(cen, segs), [])

    def test_cada_categoria(self):
        cen, segs = self._caso([self._nodo("OffsetModule", "Top/g/Offset", localreferential="true", rep={"orientation": 30.0}),   # nodo nuevo de Harmony: localreferential=true
                                self._nodo("CurveModule", "Top/g/Curve", localreferential="false", influencetype="FINITE_INFLUENCE")],
                               [self._nodo("DeformationCompositeModule", "Top/g/Comp", vals={"outputmatrixonly": "true"}, puertos_usados=[0, 1]),
                                self._nodo("KinematicOutputModule", "Top/g/Kin", fuera_de_defecto=["algo"])])
        txt = "\n".join(D.avisos_no_modelados(cen, segs))
        for k in ("influencetype != INFINITE_INFLUENCE", "localreferential != false", "restingorientation != 0", "mas de un puerto", "modo de salida distinto", "KinematicOutputModule con parametros"):
            self.assertIn(k, txt)

    def test_nodo_fuera_de_la_cadena_activa_no_avisa(self):
        n = self._nodo("CurveModule", "Top/g/Curve", influencetype="FINITE_INFLUENCE")
        self.assertEqual(D.avisos_no_modelados({"Top/R": [n]}, {}), [])

    def test_apagado(self):
        ant = D.AVISOS_NO_MODELADO
        try:
            D.AVISOS_NO_MODELADO = False
            cen, segs = self._caso([self._nodo("CurveModule", "Top/g/Curve", influencetype="X")])
            self.assertEqual(D.avisos_no_modelados(cen, segs), [])
        finally:
            D.AVISOS_NO_MODELADO = ant


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(RAIZ, "trabajo", "deform_param", "base", "f6", "escena.json")
PARAMS = os.path.join(RAIZ, "trabajo", "deform_param", "params_f6.json")


@unittest.skipUnless(os.path.isfile(BASE) and os.path.isfile(PARAMS), "faltan los artefactos de <datos de trabajo omitidos> (horneado de PLANO fN)")
class TestOraculo1220(unittest.TestCase):
    def setUp(self):   # los artefactos del spike se hornearon con el muestreo de 160 puntos: el oraculo exacto se hace con el modelo apagado
        self._ref, D.REFINADO = D.REFINADO, False

    def tearDown(self):
        D.REFINADO = self._ref

    def test_f6_svg_identicos_al_aplastado(self):
        """Oraculo del spike: reposo + parametros reproducen byte a byte el SVG aplastado de hornear en PLANO fN (88 piezas)."""
        base = os.path.dirname(BASE)
        with open(PARAMS, encoding="utf-8") as fh:
            specs = json.load(fh)
        mapa = ES.piezas_deformadas(BASE)
        self.assertGreater(len(mapa), 50)
        for i in list(mapa)[:12]:
            dd, rp = mapa[i]
            with open(os.path.join(base, rp), encoding="utf-8") as fh:
                svg = fh.read()
            with open(os.path.join(base, dd), encoding="utf-8") as fh:
                esperado = fh.read()
            self.assertEqual(EV.deformar(EV.Plantilla(svg), specs[i]), esperado, i)


if __name__ == "__main__":
    unittest.main()
