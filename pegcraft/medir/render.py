"""Llamadas al crate pegcraft-render (el binario se compila aparte: cargo build --release --offline)."""
import json, subprocess
from pathlib import Path
from ..config import EXE


def renderizar(escena_json, png, bg="gris", extra=()):
    """Renderiza un escena.json a png (RGBA 1920x1080). bg: 'gris' o 'transparente'. extra: flags del crate (--div, --sin-recorte...)."""
    if not Path(EXE).is_file():
        raise SystemExit(f"falta {EXE}: cd crates\\pegcraft-render; cargo build --release --offline")
    cmd = [str(EXE), str(escena_json), "--out", str(png), *extra]
    if bg == "transparente":
        cmd += ["--bg", "transparente"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"pegcraft-render fallo: {r.stderr[-300:]}")
    return str(png)


def renderizar_pieza_sola(escena_json, ids, png, capas=None, sin_recorte=False):
    """Render (fondo transparente) de las piezas `ids` (lista de rutas) de un escena.json; `capas` fuerza ['colour','line']..."""
    e = json.load(open(escena_json, encoding="utf-8"))
    base = Path(escena_json).resolve().parent
    ps = []
    for p in e["piezas"]:
        if p["id"] in ids:
            p = dict(p)
            if not Path(p["dibujo"]).is_absolute():
                p["dibujo"] = str(base / p["dibujo"])
            if capas:
                p["capas"] = list(capas)
            ps.append(p)
    e["piezas"] = ps
    tmp = Path(png).with_suffix(".json")
    json.dump(e, open(tmp, "w", encoding="utf-8"))
    return renderizar(tmp, png, "transparente", ["--sin-recorte"] if sin_recorte else []) if ps else None
