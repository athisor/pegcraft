"""Rutas del laboratorio (una sola fuente). Todo se puede cambiar con variables de entorno."""
import os
import sys
from pathlib import Path

# Por omision, la raiz del repositorio (dos niveles sobre este archivo).
RAIZ = Path(os.environ.get("PEGCRAFT_RAIZ", str(Path(__file__).resolve().parent.parent)))
NOMBRE_EXE = "pegcraft-render" + (".exe" if sys.platform == "win32" else "")   # solo Windows lleva extension
def _buscar_exe() -> Path:
    """`PEGCRAFT_EXE`; si no, el binario del repo (cargo build --release) y, en el paquete portable, `app\\bin\\pegcraft-render.exe`."""
    if os.environ.get("PEGCRAFT_EXE"):
        return Path(os.environ["PEGCRAFT_EXE"])
    repo = RAIZ / "crates" / "pegcraft-render" / "target" / "release" / NOMBRE_EXE
    paquete = RAIZ / "bin" / NOMBRE_EXE
    return paquete if (not repo.exists() and paquete.exists()) else repo
EXE = _buscar_exe()
TRABAJO = RAIZ / "trabajo"
# Paquete portable (app\ junto a python\python.exe): la carpeta del paquete puede ser de solo lectura, asi que la cache va a %LOCALAPPDATA%.
EN_PAQUETE = (RAIZ.name == "app" and (RAIZ.parent / "python" / "python.exe").is_file())
CACHE = (Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "pegcraft" / "cache") if EN_PAQUETE else RAIZ / "cache"
# Escena de prueba opcional (no incluida en el repositorio): ruta a un .xstage propio para las pruebas lentas.
_E = os.environ.get("PEGCRAFT_XSTAGE_PRUEBA")
XSTAGE_PRUEBA = Path(_E) if _E else TRABAJO / "prueba" / "escena.xstage"
# Expresion regular (sin distinguir mayusculas) de las rutas de nodo que el horneado NO dibuja (capas auxiliares de la escena que no son imagen final).
# Vacia = no se excluye ninguna. Cada produccion pone la suya: `PEGCRAFT_EXCLUIR` o `--excluir`.
EXCLUIR = os.environ.get("PEGCRAFT_EXCLUIR", "")
# Nombres (separados por coma) de piezas cuya Z se conoce y que `apilado.orden_apilado` marca como `z_excepcion_conocida` (solo informativo).
Z_EXCEPCIONES = tuple(x.strip() for x in os.environ.get("PEGCRAFT_Z_EXCEPCIONES", "").split(",") if x.strip())
