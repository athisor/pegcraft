"""`pegcraft ver <escena.xstage> <fotograma> -o salida.png`: hornea a una carpeta temporal y dibuja con el rasterizador CPU (crates/pegcraft-render)."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

from . import config
from .medir import render as _render


def ver(xstage, fotograma, salida, bg="gris", extra=()):
    """Devuelve la ruta del PNG. Sin el binario del rasterizador: SystemExit con el comando para compilarlo (se comprueba antes de hornear)."""
    if not Path(config.EXE).is_file():
        raise SystemExit(_render.AVISO_SIN_BINARIO.format(exe=config.EXE))
    xstage = Path(xstage)
    if not xstage.is_file():
        raise SystemExit(f"no existe la escena {xstage}")
    from .bake.hornear import hornear
    tmp = Path(tempfile.mkdtemp(prefix="pegcraft_ver_"))
    try:
        ruta_json, resumen = hornear(str(xstage), int(fotograma), str(tmp))
        if resumen.get("avisos"):
            with open(ruta_json, encoding="utf-8") as fh:
                avisos = json.load(fh).get("avisos") or []
            for aviso in avisos[:10]:
                print("aviso:", aviso, file=sys.stderr)
            if len(avisos) > 10:
                print(f"... y {len(avisos) - 10} avisos mas", file=sys.stderr)
        salida = Path(salida)
        salida.parent.mkdir(parents=True, exist_ok=True)
        return _render.renderizar(ruta_json, salida, bg, list(extra))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
