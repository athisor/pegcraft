"""L1: lectura del XML de una escena (.xstage) con ElementTree.

Solo biblioteca estándar. Hace tres cosas antes de analizar:

* rechaza cualquier ``<!DOCTYPE`` (no hay entidades que expandir: el formato no
  las usa y rechazarlas cierra la puerta a ataques de expansión);
* protege los saltos de línea dentro de valores de atributo (P25): el XML los
  normaliza a espacios al analizar, y el formato los usa de verdad (por ejemplo
  el texto de un script), así que se sustituyen por ``&#10;`` / ``&#13;``;
* acepta un BOM de UTF-8 al principio.

El módulo se llama ``xml`` dentro del paquete; ``import xml.etree`` de la
biblioteca estándar no se ve afectado porque todos los imports del paquete son
relativos y absolutos de ``xml.etree...`` se resuelven en la raíz.
"""
from __future__ import annotations

import codecs
import re
import xml.etree.ElementTree as ET
from pathlib import Path

__all__ = ["leer_xml", "parsear_bytes", "proteger_saltos"]

# Valor de atributo entre comillas que contiene \n o \r. Sin "<" dentro (no es
# legal en un valor de atributo), de modo que un `="` suelto en texto no puede
# tragarse etiquetas vecinas.
_RE_DOBLE = re.compile(rb'="([^"<]*[\r\n][^"<]*)"')
_RE_SIMPLE = re.compile(rb"='([^'<]*[\r\n][^'<]*)'")
_RE_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)


def _escapar(m: re.Match, comilla: bytes) -> bytes:
    v = m.group(1).replace(b"\r", b"&#13;").replace(b"\n", b"&#10;")
    return b"=" + comilla + v + comilla


def _doble(m: re.Match) -> bytes:
    return _escapar(m, b'"')


def _simple(m: re.Match) -> bytes:
    return _escapar(m, b"'")


def proteger_saltos(datos: bytes) -> bytes:
    """Reemplaza ``\\n`` y ``\\r`` dentro de valores de atributo por referencias numéricas (P25)."""
    if b"\n" not in datos and b"\r" not in datos:
        return datos
    datos = _RE_DOBLE.sub(_doble, datos)
    datos = _RE_SIMPLE.sub(_simple, datos)
    return datos


def parsear_bytes(datos: bytes) -> ET.Element:
    """Analiza el contenido de un .xstage y devuelve el elemento raíz.

    Lanza ``ValueError`` si hay un ``<!DOCTYPE`` o si el XML está mal formado.
    """
    if datos.startswith(codecs.BOM_UTF8):
        datos = datos[len(codecs.BOM_UTF8):]
    if _RE_DOCTYPE.search(datos):
        raise ValueError("el archivo contiene <!DOCTYPE: se rechaza")
    datos = proteger_saltos(datos)
    try:
        return ET.fromstring(datos)
    except ET.ParseError as ex:
        raise ValueError(f"XML mal formado: {ex}") from ex


def leer_xml(ruta) -> ET.Element:
    """Lee el archivo en bytes y devuelve la raíz del XML (ver ``parsear_bytes``)."""
    return parsear_bytes(Path(ruta).read_bytes())
