"""Modelo de dibujo editable (v1): un dibujo como trazos con linea, grosor y color a cada lado.

Especificacion y decision: docs/formato/modelo-de-dibujo.md

    from pegcraft import dibujo
    d = dibujo.desde_tvg(bytes_del_tvg)        # forma JSON (dict)
    texto = dibujo.a_svg(d)                    # forma SVG: apariencia resuelta + datos del trazo
    d2 = dibujo.desde_svg(texto)               # ida y vuelta: d2 == d
    dibujo.validar(d)                          # [] si esta bien formado
"""
from .modelo import ARTS, VERSION, a_modelo_lector, canonico, desde_lector, desde_tvg, nucleo, validar
from .svg import NS, a_svg, desde_svg

__all__ = ["ARTS", "VERSION", "NS", "desde_tvg", "desde_lector", "a_modelo_lector", "validar", "nucleo", "canonico", "a_svg", "desde_svg"]
