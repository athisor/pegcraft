"""sightread: lectores de sala limpia de los formatos de escena de Toon Boom Harmony, solo con biblioteca estandar.

Tres lectores, cada uno es un subpaquete que se importa por separado:

- ``sightread.lector``: escenas ``.xstage`` (grafo de nodos, columnas, evaluacion de PEG/READ/composite por fotograma).
- ``sightread.tvg``: dibujos vectoriales ``.tvg`` (decodificacion y conversion a SVG).
- ``sightread.plt``: paletas ``.plt`` / ``palette-library`` (colores y gradientes).

Ademas: ``sightread.rutas`` (busqueda de archivos tolerante a mayusculas) y ``sightread.sintetico`` (generador de escenas sinteticas).
Procedencia de cada regla: ``docs/PROCEDENCIA.md``.
"""
__version__ = "0.1.0"

__all__ = ["__version__", "lector", "tvg", "plt", "rutas"]
