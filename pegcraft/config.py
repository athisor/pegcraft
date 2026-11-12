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
