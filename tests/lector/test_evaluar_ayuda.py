"""Constructor de escenas sintéticas mínimas para las pruebas del evaluador (nombres inventados, sin rutas). No contiene pruebas."""
import tempfile
from pathlib import Path

from pegcraft.lector import abrir
from pegcraft.lector.escena import limpiar_cache


def _a(tag, v):
    return f'<{tag} val="{v}" />'


def peg(nombre, pos=(0, 0, 0), rot=0, esc=(1, 1), sesgo=0, piv=(0, 0), apagado=False, tipo="PEG", extra_attrs=""):
    """PEG (o READ con ``tipo="READ"``, que usa ``offset`` en vez de ``position``) con canales por valor."""
    pre = "offset" if tipo == "READ" else "position"
    attrs = (f"<{pre}><separate val=\"true\" />{_a('x', pos[0])}{_a('y', pos[1])}{_a('z', pos[2])}</{pre}>"
             f"<scale><separate val=\"true\" />{_a('x', esc[0])}{_a('y', esc[1])}</scale>"
             f"<rotation><separate val=\"false\" />{_a('anglez', rot)}</rotation>{_a('angle', rot)}{_a('skew', sesgo)}"
             f"<pivot>{_a('x', piv[0])}{_a('y', piv[1])}</pivot>{extra_attrs}")
    return modulo(tipo, nombre, attrs, apagado)


def modulo(tipo, nombre, attrs="", apagado=False, pos="0,0,0"):
    opc = '<options><disabled val="true" /></options>' if apagado else ""
    return f'<module type="{tipo}" name="{nombre}" pos="{pos}">{opc}<attrs>{attrs}</attrs></module>'


def grupo(nombre, nodos, cables="", apagado=False):
    opc = '<options><disabled val="true" /></options>' if apagado else ""
    return f'<group name="{nombre}" pos="0,0,0">{opc}<nodeslist>{"".join(nodos)}</nodeslist><linkedlist>{cables}</linkedlist></group>'


def cable(origen, destino, po=0, pi=0):
    return f'<link out="{origen}" in="{destino}" outport="{po}" inport="{pi}" />'


def read(nombre, col="Col_Dibujo", **kw):
    return peg(nombre, tipo="READ", extra_attrs=f'<drawing><element col="{col}" /></drawing>' + kw.pop("extra", ""), **kw)


def xstage(nodos, cables, columnas="", metricas=(4, 3, 24, 24, 12), nbframes=24):
    aX, aY, nX, nY, nZ = metricas
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<project>
 <elements><element id="2" elementName="Dib_A" elementFolder="Dib_A"><drawings><dwg name="1" /><dwg name="2" /></drawings></element></elements>
 <options>
  <metrics unitAspectRatioX="{aX}" unitAspectRatioY="{aY}" numberOfUnitsX="{nX}" numberOfUnitsY="{nY}" numberOfUnitsZ="{nZ}" />
  <framerate val="24" />
 </options>
 <scenes><scene name="Top" id="x" nbframes="{nbframes}" startFrame="1" stopFrame="{nbframes}">
  <columns>
   <column type="0" name="Col_Dibujo" id="2"><elementSeq exposures="1-{nbframes}" id="2" val="1" /></column>
   {columnas}
  </columns>
  <rootgroup name="Top">
   <nodeslist>{"".join(nodos)}</nodeslist>
   <linkedlist>{cables}</linkedlist>
  </rootgroup>
 </scene></scenes>
</project>
"""


class Escenas:
    """Directorio temporal con escenas; ``abrir_xml(texto)`` devuelve la ``Escena``."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.n = 0

    def abrir_xml(self, texto):
        self.n += 1
        limpiar_cache()
        p = Path(self.tmp.name) / f"e{self.n}.xstage"
        p.write_text(texto, encoding="utf-8")
        return abrir(p)

    def cerrar(self):
        self.tmp.cleanup()
