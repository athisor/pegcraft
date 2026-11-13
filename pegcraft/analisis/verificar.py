"""Verificacion del log compartible: `python -m pegcraft analizar --verificar <archivo_compartible.json> [--escenas <carpeta>]`.

Sale con codigo 1 y dice CAMPO y MOTIVO (nunca el texto hallado) si el archivo:
  - trae algo fuera del formato (campos o categorias desconocidos, tipos de dato equivocados);
  - tiene en cualquier cadena una ruta (unidad:\\, \\\\servidor, /home, /Users, separadores), un nombre de usuario o correo, una URL;
  - tiene una clave fuera del vocabulario de su categoria, o texto libre largo;
  - con `--escenas`: contiene el nombre de un .xstage, de una carpeta, de un nodo, de una columna o de un elemento de esa carpeta.
Lo corre siempre `analizar --compartible` al terminar y borra el archivo si falla. Es para quien manda el log: su agente lo corre antes de abrir un issue.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import CATEGORIAS
from .compartible import FORMATO

MAX_CLAVE = 120
MAX_PALABRAS = 24     # las claves son mensajes enlatados de <= 110 caracteres; mas que eso (o 24 palabras) ya es texto libre
_RAIZ = {"formato", "pegcraft", "sightread", "harmony", "escenas", "escenas_con_hallazgos", "hallazgos"}
_FILA = {"categoria", "clave", "n", "escenas"}
_RX_VERSION = re.compile(r"^[\w.+\-]{1,30}$")
_RX_HARMONY = re.compile(r"^\d{1,6}( build \d{1,8})?$")
# vocabulario de la clave por categoria (las no listadas usan el generico)
_RX_CLAVE = {
    "nodo_tipo_no_soportado": re.compile(r"^[\w\-]{1,60}$"),
    "atributo_no_leido": re.compile(r"^[\w\-]+\.[\w\-]+(/[\w\-]+)*$"),
    "error_lectura": re.compile(r"^[a-z_]+: [A-Za-z_]+$"),
    "columna_opaca": re.compile(r"^tipo -?\d+( \([a-z]+\))?(: .+)?$"),
}
_RX_GENERICA = re.compile(r"^[\w .,:;()<>=!\-+\[\]#%*'\"]+$")
# rutas, usuarios, correos, URLs
_PATRONES = [
    (re.compile(r"[A-Za-z]:[\\/]"), "parece una ruta con unidad"),
    (re.compile(r"\\\\"), "parece una ruta de red"),
    (re.compile(r"(?i)(^|[\s(])/(home|users|mnt|usr|var|tmp|etc|opt|root|volumes)\b"), "parece una ruta de Unix"),
    (re.compile(r"(?i)\b(users|usuarios)[\\/]\w"), "parece una carpeta de usuario"),
    (re.compile(r"\\"), "tiene un separador de ruta"),
    (re.compile(r"(?i)\b(https?|ftp|file)://|\bwww\."), "parece una URL"),
    (re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+"), "parece un correo"),
    (re.compile(r"(^|\s)@\w+"), "parece un nombre de usuario"),
]
_RX_BARRA = re.compile(r"/")
_ALTO = frozenset({"tipo", "nodo", "columna", "desconocido", "desconocida", "tratado", "como", "transparente", "con", "sin", "una", "uno", "los", "las", "del",
                   "que", "por", "para", "esta", "este", "valor", "linea", "paleta", "color", "modelado", "modelada", "efecto", "aplicado", "relleno", "textura",
                   "usada", "dibuja", "degradado", "soportado", "ilegible", "forma", "alternativa"})


def _sospechoso(texto: str, barra_ok: bool = False) -> str | None:
    if any(ord(c) < 32 for c in texto):
        return "tiene saltos de linea o caracteres de control (texto libre)"
    for rx, motivo in _PATRONES:
        if rx.search(texto):
            return motivo
    if not barra_ok and _RX_BARRA.search(texto):
        return "tiene un separador de ruta"
    return None


def _tokens(sensibles) -> list[str]:
    from ..bake.apilado import TIPOS_MODELADOS
    base = set(CATEGORIAS) | set(TIPOS_MODELADOS)
    return sorted({s for s in sensibles if len(s) >= 3 and not s.isdigit() and s not in base and s.lower() not in _ALTO}, key=len, reverse=True)


def sensibles_de_carpeta(carpeta) -> set[str]:
    """Nombres propios de las escenas de una carpeta: archivos, carpetas, nodos, columnas y elementos."""
    from sightread.lector import abrir
    from sightread.lector.escena import limpiar_cache
    p = Path(carpeta)
    out: set[str] = set(p.resolve().parts) | {p.name}
    escenas = [p] if p.is_file() else sorted(p.rglob("*.xstage"))
    for x in escenas:
        out |= set(x.resolve().parts) | {x.stem}
        try:
            e = abrir(x)
        except Exception:  # noqa: BLE001 - una escena ilegible solo aporta sus nombres de archivo
            continue
        for n in e.nodos.values():
            out.add(n.nombre); out.update(n.ruta.split("/"))
        out.update(str(c) for c in e.columnas)
        for el in e.elementos.values():
            out.update(v for v in (el.nombre, el.carpeta) if v)
        limpiar_cache()
    return out


def verificar(archivo, escenas=None, sensibles=None) -> list[tuple[str, str]]:
    """Lista de (campo, motivo); vacia si el archivo es compartible. `escenas`: carpeta con las escenas originales; `sensibles`: nombres ya reunidos."""
    problemas: list[tuple[str, str]] = []
    try:
        j = json.loads(Path(archivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [("$", "no se puede leer como JSON")]
    if not isinstance(j, dict):
        return [("$", "la raiz no es un objeto")]
    for k in j:
        if k not in _RAIZ:
            problemas.append(("$", "campo de la raiz fuera del formato"))
    if j.get("formato") != FORMATO:
        problemas.append(("$.formato", f"no es {FORMATO}"))
    for campo in ("pegcraft", "sightread"):
        v = j.get(campo)
        if v is not None and not (isinstance(v, str) and _RX_VERSION.match(v)):
            problemas.append((f"$.{campo}", "no parece un numero de version"))
    for campo in ("escenas", "escenas_con_hallazgos"):
        if not isinstance(j.get(campo), int) or isinstance(j.get(campo), bool) or j[campo] < 0:
            problemas.append((f"$.{campo}", "no es un entero >= 0"))
    h = j.get("harmony")
    if not isinstance(h, dict):
        problemas.append(("$.harmony", "no es un objeto"))
    else:
        for i, (k, v) in enumerate(h.items()):
            if not _RX_HARMONY.match(str(k)):
                problemas.append((f"$.harmony[{i}]", "no parece una version de Harmony"))
            if not isinstance(v, int) or isinstance(v, bool):
                problemas.append((f"$.harmony[{i}]", "el conteo no es un entero"))
    filas = j.get("hallazgos")
    if not isinstance(filas, list):
        problemas.append(("$.hallazgos", "no es una lista"))
        filas = []
    toks = _tokens(set(sensibles or ()) | (sensibles_de_carpeta(escenas) if escenas else set()))
    rx_nombres = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(s) for s in toks) + r")(?![\w])") if toks else None
    for i, f in enumerate(filas):
        pre = f"$.hallazgos[{i}]"
        if not isinstance(f, dict):
            problemas.append((pre, "no es un objeto")); continue
        if set(f) != _FILA:
            problemas.append((pre, "campos distintos de categoria, clave, n, escenas"))
        cat, clave = f.get("categoria"), f.get("clave")
        if cat not in CATEGORIAS:
            problemas.append((pre + ".categoria", "categoria fuera del vocabulario"))
        for c in ("n", "escenas"):
            if not isinstance(f.get(c), int) or isinstance(f.get(c), bool) or f[c] < 0:
                problemas.append((f"{pre}.{c}", "no es un entero >= 0"))
        if not isinstance(clave, str) or not clave:
            problemas.append((pre + ".clave", "no es una cadena")); continue
        rx = _RX_CLAVE.get(cat, None)
        if len(clave) > MAX_CLAVE or len(clave.split()) > MAX_PALABRAS:
            problemas.append((pre + ".clave", "texto libre largo"))
        elif rx is not None and not rx.match(clave):
            problemas.append((pre + ".clave", f"fuera del vocabulario de {cat}"))
        elif rx is None and not _RX_GENERICA.match(clave):
            problemas.append((pre + ".clave", "tiene caracteres fuera del vocabulario"))
        m = _sospechoso(clave, barra_ok=(cat == "atributo_no_leido"))
        if m:
            problemas.append((pre + ".clave", m))
        if rx_nombres is not None and rx_nombres.search(clave):
            problemas.append((pre + ".clave", "coincide con un nombre de las escenas (archivo, carpeta, nodo, columna o elemento)"))
    for campo in ("pegcraft", "sightread"):
        if isinstance(j.get(campo), str):
            m = _sospechoso(j[campo])
            if m:
                problemas.append((f"$.{campo}", m))
    if isinstance(h, dict):
        for i, k in enumerate(h):
            m = _sospechoso(str(k))
            if m:
                problemas.append((f"$.harmony[{i}]", m))
    return problemas


def informar(problemas, salida=print) -> int:
    """Imprime `campo: motivo` por problema (sin el texto hallado). Devuelve 0 si no hay, 1 si hay."""
    if not problemas:
        salida("OK: el archivo no contiene rutas, nombres ni texto libre")
        return 0
    salida(f"NO COMPARTIR: {len(problemas)} problema(s)")
    for campo, motivo in problemas[:100]:
        salida(f"  {campo}: {motivo}")
    return 1
