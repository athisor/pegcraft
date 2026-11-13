"""Horneado de un RANGO de fotogramas en UN solo proceso: `python -m pegcraft hornear-rango <xstage> <salida> [--desde 1] [--hasta N|todos] [--paso 1] [opciones de hornear]`.

Escribe `<salida>/fNNNN/escena.json` por fotograma, con el mismo contenido que `hornear` fotograma a fotograma, salvo la ruta de los SVG base: se convierten
UNA vez y viven en `<salida>/dibujos/`, y el escena.json los referencia como `../dibujos/x.svg` (los deformados dependen del fotograma y quedan en
`fNNNN/dibujos/`). El .xstage se abre una vez (el lector guarda `Escena` y `Evaluador` por ruta+mtime) y se reutilizan sus cachés.
Avance por stdout, una linea por fotograma: `fotograma i/M f=N` (i = cuantos van, M = total del rango). Matar el proceso es seguro: cada escena.json se
escribe de forma atomica.
"""
import sys, json
from pathlib import Path

sys.dont_write_bytecode = True


def fotogramas(xs, desde=1, hasta=None, paso=1):
    """Lista de fotogramas del rango. `hasta` None o 'todos' = el ultimo de la escena."""
    from sightread.lector import compat as L
    n = L.n_fotogramas(xs)
    if hasta in (None, "todos"):
        hasta = n
    hasta = int(hasta)
    return list(range(int(desde), hasta + 1, max(1, int(paso))))


def _preparar_comun(comun, firma):
    """Carpeta de SVG base compartidos. Si los hizo otra combinacion de opciones (gradientes), se vacia: el nombre del SVG no la distingue."""
    comun.mkdir(parents=True, exist_ok=True)
    marca = comun / ".opciones"
    if marca.is_file() and marca.read_text(encoding="utf-8") != firma:
        for p in comun.glob("*.svg"):
            p.unlink()
    marca.write_text(firma, encoding="utf-8")


def hornear_rango(xs, salida, desde=1, hasta=None, paso=1, avance=None, **opciones):
    """Hornea el rango; `opciones` son las de `hornear` (excluir, grupo, conectores, ...). Devuelve {"fotogramas": n, "piezas": total, "avisos": total}."""
    from .hornear import hornear, Compartido
    salida = Path(salida)
    frames = fotogramas(xs, desde, hasta, paso)
    comun = salida / "dibujos"
    _preparar_comun(comun, json.dumps({"gradientes": bool(opciones.get("gradientes", True))}))
    comp = Compartido(comun)
    tot = {"fotogramas": 0, "piezas": 0, "avisos": 0}
    for i, f in enumerate(frames, 1):
        _, res = hornear(xs, f, salida / f"f{f:04d}", compartido=comp, **opciones)
        tot["fotogramas"] += 1; tot["piezas"] += res["piezas"]; tot["avisos"] += res["avisos"]
        if avance:
            avance(i, len(frames), f)
    return tot
