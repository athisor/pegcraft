"""ALMACEN DE ACTIVOS direccionado por contenido: cache\\svg\\<clave>.svg.

Clave de un dibujo base  = sha256( sha256(.tvg) | hash de paletas visibles | VERSION_CONVERSOR | flag gradientes ).
Clave de un dibujo deformado = sha256( clave base | estado del deformador (nodos activos, aspecto, div, variante) ).
El almacen solo guarda SVG que ya produce el lector .tvg (hornear los copia a su carpeta de salida: la salida de `hornear` no cambia).
Desactivar: env PEGCRAFT_ALMACEN=no.
"""
import hashlib, json, os, shutil, time
from pathlib import Path
from ..config import RAIZ

RAIZ_ALMACEN = Path(os.environ.get("PEGCRAFT_CACHE_SVG", str(RAIZ / "cache" / "svg")))
ACTIVO = os.environ.get("PEGCRAFT_ALMACEN", "si") != "no"
PAQUETE = Path(__file__).resolve().parents[1]   # carpeta pegcraft/
ESQUEMA = "1"          # subir si cambia el formato de clave

STATS = {"hit": 0, "miss": 0, "hit_def": 0, "miss_def": 0, "t_convertir": 0.0, "t_deformar": 0.0, "t_copiar": 0.0, "t_clave": 0.0}
REG = {}               # nombre de svg en la carpeta de salida de hornear -> {"clave":..., "base":...}  (lo lee compilar)
_memo = {}


def _sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_archivo(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def version_conversor():
    """Hash del codigo del lector .tvg (sightread/tvg/*.py), del lector .plt (sightread/plt/*.py) y del post-proceso de gradientes
    (cambia el codigo => cambia toda la clave)."""
    if "ver" not in _memo:
        import sightread
        sr = Path(sightread.__file__).resolve().parent
        h = hashlib.sha256(ESQUEMA.encode())
        fs = sorted((sr / "tvg").glob("*.py")) + sorted((sr / "plt").glob("*.py")) + [PAQUETE / "bake" / "gradientes.py"]
        for f in fs:
            if f.is_file():
                h.update(f.parent.name.encode()); h.update(f.name.encode()); h.update(f.read_bytes())
        _memo["ver"] = h.hexdigest()[:16]
    return _memo["ver"]


def _hash_dir_paletas(d):
    k = ("pal", str(d))
    if k not in _memo:
        h = hashlib.sha256()
        d = Path(d)
        for f in [d / "PALETTE_LIST", *sorted((d / "palette-library").glob("*.plt"))]:
            if f.is_file():
                h.update(f.name.encode()); h.update(f.read_bytes())
        _memo[k] = h.hexdigest()
    return _memo[k]


def hash_paletas(esc, tvg):
    """Paletas que influyen: las de la escena + las del elemento (carpeta del .tvg)."""
    return _sha_bytes((_hash_dir_paletas(esc) + _hash_dir_paletas(Path(tvg).parent)).encode())


def clave_base(tvg, esc, gradientes=True):
    t0 = time.perf_counter()
    st = Path(tvg).stat()
    km = ("tvg", str(tvg), st.st_mtime_ns, st.st_size)
    if km not in _memo:
        _memo[km] = sha_archivo(tvg)
    s = "|".join([_memo[km], hash_paletas(esc, tvg), version_conversor(), "g1" if gradientes else "g0"])
    STATS["t_clave"] += time.perf_counter() - t0
    return _sha_bytes(s.encode())


def clave_deformado(clave_b, nodos, aspecto, div, var=""):
    s = json.dumps([clave_b, nodos, aspecto, div, var], sort_keys=True, default=repr)
    return _sha_bytes(s.encode())


def ruta(clave):
    return RAIZ_ALMACEN / f"{clave}.svg"


def traer(clave, destino, deformado=False):
    """Copia del almacen a `destino` si existe; True si hubo acierto."""
    if not ACTIVO:
        return False
    p = ruta(clave)
    if p.is_file():
        t0 = time.perf_counter(); shutil.copyfile(p, destino); STATS["t_copiar"] += time.perf_counter() - t0
        STATS["hit_def" if deformado else "hit"] += 1
        return True
    STATS["miss_def" if deformado else "miss"] += 1
    return False


def guardar(clave, origen):
    if not ACTIVO:
        return
    RAIZ_ALMACEN.mkdir(parents=True, exist_ok=True)
    tmp = ruta(clave).with_suffix(f".tmp{os.getpid()}")
    shutil.copyfile(origen, tmp)
    try:
        os.replace(tmp, ruta(clave))      # atomico: dos procesos no ven medio archivo
    except PermissionError:
        # Windows: otro proceso tiene abierto el destino (lo esta copiando o lo guardo antes). La clave es por contenido: el existente vale.
        try:
            os.remove(tmp)
        except OSError:
            pass
    except OSError:
        raise
    # (12-11-2026: sin esto, corridas en paralelo del banco fallaban al azar con PermissionError)


def registrar(nombre_svg, clave, base=None, tvg=None):
    REG[nombre_svg] = {"clave": clave, "base": base or clave, "tvg": str(tvg) if tvg else None}


def tomar_registro():
    r = dict(REG); REG.clear(); return r


def reset_stats():
    for k in STATS:
        STATS[k] = 0 if isinstance(STATS[k], int) else 0.0
