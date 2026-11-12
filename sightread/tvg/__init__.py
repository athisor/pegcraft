"""Lector .tvg de sala limpia (ADR-0013 §2): ``decodificar``, ``a_svg`` y ``TvgIlegible``. Solo biblioteca estandar.

modelo = decodificar(bytes) ->
    {"disp": "D1"|"D2",
     "paleta": {id_hex16: {nombre, rgba: (r,g,b,a), paleta}},
     "artes": {"underlay"|"colour"|"line"|"overlay": {"capas": [{"trazos": [trazo]}]}},
     "tgco": {id_hex16: [(a,b,c,d,e,f), ...]},
     "avisos": [str]}
trazo = {"puntos": [(x, y)], "anclas": [bool], "cerrado": bool, "perfil": [...]|None, "ref": int|None,
         "estilo": {"der": id|None, "izq": id|None, "lapiz": id|None, "ancho": float, "invisible": bool} }
"""
from .modelo import decodificar
from .registros import TvgIlegible
from .svg import a_svg

__all__ = ["decodificar", "a_svg", "TvgIlegible"]
