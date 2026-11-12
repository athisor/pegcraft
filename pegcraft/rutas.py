"""Busqueda de archivos tolerante a mayusculas, para sistemas de archivos que las distinguen (Linux).

Harmony trabaja en Windows y macOS, donde `Elements/X/x-1.tvg` y `elements/x/X-1.tvg` son el mismo archivo; un `.xstage` puede nombrar
una capitalizacion distinta de la del disco. Se prueba primero el nombre exacto y solo si no existe se busca sin distinguir mayusculas.
"""
import os
from pathlib import Path


def _componente(carpeta, nombre):
    exacto = carpeta / nombre
    if exacto.exists():
        return exacto
    try:
        bajo = nombre.lower()
        for f in sorted(carpeta.iterdir()):
            if f.name.lower() == bajo:
                return f
    except OSError:
        pass
    return None


def buscar(base, *partes):
    """Path existente al resolver `partes` (nombres o rutas con `/`) bajo `base`, componente por componente (exacto primero, luego sin
    distinguir mayusculas). None si no existe."""
    actual = Path(os.fspath(base))
    for parte in partes:
        for nombre in str(parte).replace("\\", "/").split("/"):
            if nombre in ("", "."):
                continue
            if nombre == "..":
                actual = actual.parent
                continue
            actual = _componente(actual, nombre)
            if actual is None:
                return None
    return actual
