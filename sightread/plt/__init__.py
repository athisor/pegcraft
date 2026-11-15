"""Lector de solo lectura de las paletas de Harmony: archivos `.plt` y listas `PALETTE_LIST`.

Solo biblioteca estandar. Cada hecho de formato que se asume lleva su cita `# PLT-v0 §n` (especificacion de paletas, sala limpia).

API:
    leer(datos: bytes) -> Paleta                 # Paleta.colores() -> [{tipo, id, nombre, rgba, extra, paradas}]
    paletas(escena) -> [{archivo, declarada, ambito, clave}]
    paleta_tvg(escena, elemento=None) -> {id_hex: {nombre, rgba, paleta}}

El `id` es siempre el colorId en 16 hexadecimales minusculas, sin `0x` (la misma forma que usa el lector de `.tvg`).
"""
import os
import re
from pathlib import Path

from .. import rutas as _rutas

__all__ = ["leer", "paletas", "paleta_tvg", "Paleta", "PaletaIlegible"]

CABECERA_PLT = "ToonBoomAnimationInc PaletteFile 2"      # PLT-v0 §2
CABECERA_LISTA = "ToonBoomAnimationInc PaletteList 1"    # PLT-v0 §5


class PaletaIlegible(ValueError):
    """El contenido no es un `.plt` (falta la cabecera)."""


# PLT-v0 §3.1 y §3.2: tipo, ficha de nombre (sin comillas, o entre comillas dobles sin escapes), `0x` + 16 hex.
_FILA = re.compile(r'^(Solid|Texture|Gradient)[ \t]+("[^"]*"|[^\s"]+)[ \t]+0x([0-9A-Fa-f]{1,16})(?:[ \t]+(.*?))?[ \t]*$')
_ENTERO = re.compile(r"-?\d+")
_NUM = r"(-?\d+(?:\.\d+)?)"
# PLT-v0 §3.3: parada = posicion (un decimal) + R G B A, con `{` al inicio de la primera y `,` o ` }` al final.
_PARADA = re.compile(r"^\s*\{?\s*" + _NUM + r"\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*,?\s*(\})?\s*$")


class Paleta:
    """Contenido de un `.plt`. `conteo` cuenta las lineas por tipo (incluye Cadena y Desconocida, que `colores()` no devuelve)."""

    def __init__(self):
        self._filas = []
        self.conteo = {"Solid": 0, "Gradient": 0, "Texture": 0, "Cadena": 0, "Desconocida": 0}

    def colores(self):
        """Filas Solid, Gradient y Texture en el orden del archivo (el orden es significativo, PLT-v0 §2).
        Cada una: {tipo, id, nombre, rgba (r,g,b,a) | None, extra, paradas [(pos 0-100, (r,g,b,a))]}.
        Solid: rgba. Gradient: extra Linear/Radial y paradas. Texture: extra Tile/Stretch (se reconoce, no se usa)."""
        return [dict(f) for f in self._filas]

    def __len__(self):
        return len(self._filas)


def _nombre(ficha):
    return ficha[1:-1] if ficha.startswith('"') else ficha


def _parada(linea):
    m = _PARADA.match(linea)
    if not m:
        return None
    return (float(m.group(1)), tuple(int(x) for x in m.group(2, 3, 4, 5))), bool(m.group(6))


def leer(datos):
    """Interpreta los bytes de un `.plt`. Sin excepciones salvo `PaletaIlegible` (sin cabecera); una linea que no se entiende se cuenta como Desconocida."""
    texto = bytes(datos).decode("utf-8", errors="replace")      # PLT-v0 §2: UTF-8, sin BOM, 0 invalidos
    if texto.startswith("﻿"):
        texto = texto[1:]
    # Se parte solo por \n (y se quita \r): str.splitlines tambien parte por separadores que pueden aparecer en un nombre. PLT-v0 §2: LF o CRLF.
    lineas = [l[:-1] if l.endswith("\r") else l for l in texto.split("\n")]
    if lineas and lineas[-1] == "":
        lineas.pop()
    if not lineas or lineas[0].strip() != CABECERA_PLT:
        raise PaletaIlegible("falta la cabecera de paleta")
    p = Paleta()
    i = 1
    while i < len(lineas):
        linea = lineas[i]
        i += 1
        if not linea.strip():
            continue
        if linea.lstrip().startswith('"'):
            p.conteo["Cadena"] += 1                              # PLT-v0 §3.3: cadena sola, no cuenta como color
            continue
        m = _FILA.match(linea)
        if not m:
            p.conteo["Desconocida"] += 1
            continue
        tipo, ficha, hexid, resto = m.group(1), m.group(2), m.group(3), (m.group(4) or "")
        cid = hexid.lower().zfill(16)
        nombre = _nombre(ficha)
        if tipo == "Solid":                                      # PLT-v0 §3.1
            n = _ENTERO.findall(resto)
            if len(n) < 4:
                p.conteo["Desconocida"] += 1
                continue
            p._filas.append({"tipo": "Solid", "id": cid, "nombre": nombre, "rgba": tuple(int(x) for x in n[:4]), "extra": None, "paradas": []})
        elif tipo == "Texture":                                  # PLT-v0 §3.3
            p._filas.append({"tipo": "Texture", "id": cid, "nombre": nombre, "rgba": None, "extra": resto.strip() or None, "paradas": []})
        else:                                                    # Gradient, PLT-v0 §3.3: paradas en las lineas siguientes
            paradas, completo = [], False
            while i < len(lineas) and not completo:
                r = _parada(lineas[i])
                if r is None:
                    break
                par, completo = r
                paradas.append(par)
                i += 1
            if not paradas:
                p.conteo["Desconocida"] += 1
                continue
            p._filas.append({"tipo": "Gradient", "id": cid, "nombre": nombre, "rgba": None, "extra": resto.strip() or None, "paradas": paradas})
        p.conteo[tipo] += 1
    return p


# ---------------------------------------------------------------- PALETTE_LIST y escenas

_CLAVE = re.compile(r"^((?:\.\./)*)palette-library/(.+)$")       # PLT-v0 §5: `palette-library/<n>` o `../../palette-library/<n>`


def _buscar(base, *partes):
    """Busqueda exacta primero y luego sin distinguir mayusculas (Harmony trabaja en Windows y macOS; en Linux importa)."""
    return _rutas.buscar(base, *partes)


def _leer_lista(archivo):
    """[(prefijo_relativo, clave)] de un `PALETTE_LIST`, en orden. El destino tras `LINK` se ignora (PLT-v0 §5). Sin cabecera o ilegible: []."""
    try:
        texto = Path(archivo).read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return []
    lineas = [l[:-1] if l.endswith("\r") else l for l in texto.split("\n")]
    if not lineas or lineas[0].strip() != CABECERA_LISTA:
        return []
    out = []
    for l in lineas[1:]:
        clave, sep, _destino = l.partition(" LINK ")
        if not sep:
            continue
        m = _CLAVE.match(clave.strip())
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def _de_carpeta(carpeta, ambito):
    """Paletas de una carpeta con su `PALETTE_LIST` y su `palette-library`: las declaradas en el orden de la lista y despues las no declaradas."""
    carpeta = Path(carpeta)
    res, vistas = [], set()
    lista = _buscar(carpeta, "PALETTE_LIST")
    if lista is not None and lista.is_file():
        for prefijo, clave in _leer_lista(lista):
            if clave.lower() in vistas:                          # PLT-v0 §5: clave repetida (7 listas); se carga una vez
                continue
            vistas.add(clave.lower())
            # El destino absoluto se ignora; se carga <carpeta>/<prefijo>palette-library/<clave>.plt. PLT-v0 §5.
            ruta = _buscar(carpeta, prefijo + "palette-library", clave + ".plt")
            if ruta is not None and not ruta.is_file():
                ruta = None
            res.append({"archivo": ruta, "declarada": True, "ambito": ambito, "clave": clave})
    lib = _buscar(carpeta, "palette-library")
    if lib is not None and lib.is_dir():
        try:
            extra = sorted(f for f in lib.iterdir() if f.suffix.lower() == ".plt" and f.is_file())
        except OSError:
            extra = []
        for f in extra:                                          # PLT-v0 §5: lo no declarado no se carga
            if f.stem.lower() not in vistas:
                res.append({"archivo": f, "declarada": False, "ambito": ambito, "clave": f.stem})
    return res


def _carpeta_escena(escena):
    e = Path(os.fspath(escena))
    return e.parent if e.is_file() else e


def paletas(escena):
    """Paletas de una escena (carpeta o `.xstage`): primero las de la escena y luego las de cada elemento (`elements/<x>`).
    [{archivo: Path|None, declarada: bool, ambito: 'escena'|'elemento:<x>', clave}]. `archivo` es None si esta declarada y no existe.
    Solo las `declarada` se cargan (PLT-v0 §5)."""
    base = _carpeta_escena(escena)
    res = _de_carpeta(base, "escena")
    els = _buscar(base, "elements")
    if els is not None and els.is_dir():
        try:
            nombres = sorted(d.name for d in els.iterdir() if d.is_dir())
        except OSError:
            nombres = []
        for n in nombres:
            res += _de_carpeta(els / n, f"elemento:{n}")
    return res


_CACHE = {}


def _leer_archivo(ruta):
    try:
        st = os.stat(ruta)
        k = (str(ruta), st.st_mtime_ns, st.st_size)
        if k not in _CACHE:
            if len(_CACHE) > 512:
                _CACHE.clear()
            _CACHE[k] = leer(Path(ruta).read_bytes())
        return _CACHE[k]
    except (OSError, PaletaIlegible):
        return None


def _seleccion(escena, elemento):
    for p in paletas(escena):
        if p["archivo"] is None or not p["declarada"]:
            continue
        if p["ambito"] != "escena" and p["ambito"] != f"elemento:{elemento}":
            continue
        yield p


def paleta_tvg(escena, elemento=None):
    """{id_hex: {nombre, rgba, paleta}} de los colores Solid de las paletas declaradas de la escena (y las del `elemento`, si se da).
    La paleta de la escena gana sobre la copia local del dibujo (PLT-v0 §7); entre paletas, la primera que define el id gana."""
    out = {}
    for p in _seleccion(escena, elemento):
        pal = _leer_archivo(p["archivo"])
        if pal is None:
            continue
        for c in pal.colores():
            if c["tipo"] == "Solid" and c["id"] not in out:
                out[c["id"]] = {"nombre": c["nombre"], "rgba": c["rgba"], "paleta": p["clave"]}
    return out
