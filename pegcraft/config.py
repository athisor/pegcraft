"""Rutas del laboratorio (una sola fuente). Todo se puede cambiar con variables de entorno."""
import os
from pathlib import Path

# Por omision, la raiz del repositorio (dos niveles sobre este archivo).
RAIZ = Path(os.environ.get("PEGCRAFT_RAIZ", str(Path(__file__).resolve().parent.parent)))
EXE = Path(os.environ.get("PEGCRAFT_EXE", str(RAIZ / "crates" / "pegcraft-render" / "target" / "release" / "pegcraft-render.exe")))
TRABAJO = RAIZ / "trabajo"
# Escena de prueba opcional (no incluida en el repositorio): ruta a un .xstage propio para las pruebas lentas.
_E = os.environ.get("PEGCRAFT_XSTAGE_PRUEBA")
XSTAGE_PRUEBA = Path(_E) if _E else TRABAJO / "prueba" / "escena.xstage"
# Expresion regular (sin distinguir mayusculas) de las rutas de nodo que el horneado NO dibuja (capas auxiliares de la escena que no son imagen final).
# Vacia = no se excluye ninguna. Cada produccion pone la suya: `PEGCRAFT_EXCLUIR` o `--excluir`.
EXCLUIR = os.environ.get("PEGCRAFT_EXCLUIR", "")
# Nombres (separados por coma) de piezas cuya Z se conoce y que `apilado.orden_apilado` marca como `z_excepcion_conocida` (solo informativo).
Z_EXCEPCIONES = tuple(x.strip() for x in os.environ.get("PEGCRAFT_Z_EXCEPCIONES", "").split(",") if x.strip())
