#!/usr/bin/env python
"""Paquete portable de Windows del visor pegcraft: `dist/pegcraft-visor-<version>-win64.zip`.

El zip se descomprime en cualquier carpeta y el visor abre con doble clic, sin Python ni Rust instalados.
Contenido (carpeta raiz `pegcraft-visor-<version>-win64/`):

    pegcraft-visor.exe        el visor (egui + vello; GPU opcional, cae a CPU)
    pegcraft.cmd              CLI (`pegcraft ver|hornear-rango|analizar ...`) con el Python embebido
    python/                   Python embebible oficial (python.org) + numpy y Pillow
    app/                      pegcraft/, sightread/, scripts/grafo_visor.py y bin/pegcraft-render.exe
    ejemplos/                 la escena minima de ejemplo
    LICENCIAS/                licencias de pegcraft, Python, numpy, Pillow y de los crates de Rust
    LEEME.txt

Pasos: compila el visor y `pegcraft-render` (cargo, release), descarga el Python embebible (SHA-256 fijo en este
script) y las wheels de numpy/Pillow (SHA-256 que publica PyPI), arma la carpeta, precompila los .pyc, reune
licencias, crea el zip y escribe su SHA-256 al lado. Las descargas se guardan en una cache y se verifican siempre.

Uso (desde la raiz del repo):
    python tools/empaquetar/empaquetar.py                    # todo
    python tools/empaquetar/empaquetar.py --sin-compilar     # reutiliza los .exe ya compilados en --target-dir
    python tools/empaquetar/empaquetar.py --help

Es idempotente: la carpeta de armado se rehace entera y el zip sale con fechas fijas, asi que el mismo contenido da el mismo zip.
Descargas solo de python.org y pypi.org / files.pythonhosted.org. No escribe fuera de `--dist`, `--target-dir` y la cache.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# --- Python embebible oficial (python.org). Mismo menor que el entorno de trabajo (3.12). ---
PY_VERSION = "3.12.9"
PY_ZIP = f"python-{PY_VERSION}-embed-amd64.zip"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/{PY_ZIP}"
# MD5 que publica la pagina oficial de la version (https://www.python.org/downloads/release/python-3129/); el SHA-256 se calculo
# sobre el archivo cuyo MD5 coincide con esa pagina (la pagina no lista SHA-256).
PY_MD5 = "f34996cc1f44c98729ef6ce92d05e41c"
PY_SHA256 = "615861fb801e8b04c847598db4e1e46e4b046295017caa37cb5486dde72b5865"
PY_TAG = "312"  # python312.zip / python312._pth

# --- Wheels binarias (cp312 / win_amd64). El SHA-256 lo da el JSON de PyPI y se comprueba al bajarlas. ---
WHEELS = {"numpy": "2.2.6", "pillow": "12.3.0"}
HOSTS_PERMITIDOS = ("www.python.org", "pypi.org", "files.pythonhosted.org")

DIR = Path(__file__).resolve().parent
REPO = DIR.parent.parent
TEXTOS_LICENCIA = ("LICEN", "COPYING", "NOTICE", "UNLICENSE", "COPYRIGHT")
FECHA_ZIP = (2026, 1, 1, 0, 0, 0)


def info(msg):
    print(f"[empaquetar] {msg}", flush=True)


def sha256_de(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def descargar(url, destino, verificar):
    """Baja `url` a `destino` si no esta ya (o no verifica) y comprueba con `verificar(ruta)->bool`. Solo hosts permitidos."""
    host = urllib.parse.urlparse(url).hostname
    if url.split(":", 1)[0] != "https" or host not in HOSTS_PERMITIDOS:
        raise SystemExit(f"descarga no permitida: {url}")
    destino = Path(destino)
    if destino.is_file() and verificar(destino):
        info(f"cache: {destino.name}")
        return destino
    info(f"descargando {url}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "pegcraft-empaquetar"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    if not verificar(tmp):
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"la descarga no coincide con el hash esperado: {url}")
    tmp.replace(destino)
    return destino


def json_de(url):
    host = urllib.parse.urlparse(url).hostname
    if host not in HOSTS_PERMITIDOS:
        raise SystemExit(f"consulta no permitida: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "pegcraft-empaquetar"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def correr(cmd, cwd=None, env=None):
    info("$ " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env)
    if r.returncode != 0:
        raise SystemExit(f"fallo ({r.returncode}): {cmd[0]}")


def version_del_repo(repo):
    with open(repo / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


# --------------------------------------------------------------------------------------------- compilacion
def entorno_rust(repo):
    """Variables para que el .exe no lleve rutas del disco de quien compila (rutas de fuentes y del registro de cargo)."""
    env = dict(os.environ)
    cargo_home = Path(env.get("CARGO_HOME") or Path.home() / ".cargo")
    sysroot = subprocess.run(["rustc", "--print", "sysroot"], capture_output=True, text=True).stdout.strip()
    remaps = [(repo, "/src"), (cargo_home, "/cargo")] + ([(sysroot, "/rustc")] if sysroot else [])
    flags = env.get("RUSTFLAGS", "")
    for origen, destino in remaps:
        flags += f" --remap-path-prefix={origen}={destino}"
    env["RUSTFLAGS"] = flags.strip()
    env["CARGO_PROFILE_RELEASE_STRIP"] = "symbols"
    return env


def compilar(repo, target_dir):
    """Devuelve (exe_visor, exe_render)."""
    env = entorno_rust(repo)
    exes = []
    for crate, nombre in (("pegcraft-viewer-craft", "pegcraft-viewer-craft.exe"), ("pegcraft-render", "pegcraft-render.exe")):
        td = target_dir / crate
        correr(["cargo", "build", "--release", "--manifest-path", repo / "crates" / crate / "Cargo.toml", "--target-dir", td], env=env)
        exes.append(td / "release" / nombre)
    return exes


def exes_existentes(target_dir):
    exes = [target_dir / c / "release" / n for c, n in (("pegcraft-viewer-craft", "pegcraft-viewer-craft.exe"), ("pegcraft-render", "pegcraft-render.exe"))]
    faltan = [e for e in exes if not e.is_file()]
    if faltan:
        raise SystemExit("con --sin-compilar faltan: " + ", ".join(str(e) for e in faltan))
    return exes


def licencias_crates(repo, destino):
    """Lista nombre/version/licencia/repositorio de los crates de Rust (visor + render, para Windows x64) y copia el texto de licencia de cada uno."""
    filas = {}
    for crate in ("pegcraft-viewer-craft", "pegcraft-render"):
        r = subprocess.run(["cargo", "metadata", "--format-version", "1", "--locked", "--filter-platform", "x86_64-pc-windows-msvc",
                            "--manifest-path", str(repo / "crates" / crate / "Cargo.toml")], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("cargo metadata fallo:\n" + r.stderr[-800:])
        meta = json.loads(r.stdout)
        dentro = {n["id"] for n in meta["resolve"]["nodes"]}
        for p in meta["packages"]:
            if p["id"] not in dentro or p["source"] is None:  # los de ruta local son del propio repo
                continue
            filas[(p["name"], p["version"])] = p
    destino.mkdir(parents=True, exist_ok=True)
    lineas = ["Crates de Rust enlazados en pegcraft-visor.exe y pegcraft-render.exe (nombre version | licencia | repositorio).",
              "El texto de licencia de cada crate esta en crates/<nombre>-<version>/ cuando el crate lo incluye.", ""]
    n_textos = 0
    for (nombre, ver), p in sorted(filas.items()):
        lineas.append(f"{nombre} {ver} | {p.get('license') or p.get('license_file') or 'sin declarar'} | {p.get('repository') or p.get('homepage') or '-'}")
        origen = Path(p["manifest_path"]).parent
        for f in sorted(origen.iterdir()):
            if f.is_file() and f.name.upper().startswith(TEXTOS_LICENCIA):
                d = destino / "crates" / f"{nombre}-{ver}"
                d.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, d / f.name)
                n_textos += 1
    (destino / "crates_rust.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    info(f"licencias de crates: {len(filas)} crates, {n_textos} textos")
    return len(filas)


# --------------------------------------------------------------------------------------------- Python embebido
def preparar_python(cache, stage):
    z = descargar(PY_URL, cache / PY_ZIP, lambda p: sha256_de(p) == PY_SHA256 and hashlib.md5(p.read_bytes()).hexdigest() == PY_MD5)
    py = stage / "python"
    with zipfile.ZipFile(z) as zf:
        zf.extractall(py)
    licencia = py / "LICENSE.txt"
    pth = py / f"python{PY_TAG}._pth"
    # stdlib en el zip, el propio directorio, el codigo de pegcraft (..\app) y site-packages; `import site` activa site-packages.
    lineas = [f"python{PY_TAG}.zip", ".", os.path.join("..", "app"), os.path.join("Lib", "site-packages"), "import site"]
    pth.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return py, licencia


def instalar_wheels(cache, py, destino_licencias):
    sp = py / "Lib" / "site-packages"
    sp.mkdir(parents=True, exist_ok=True)
    for nombre, ver in WHEELS.items():
        datos = json_de(f"https://pypi.org/pypi/{nombre}/{ver}/json")
        cand = [u for u in datos["urls"] if u["packagetype"] == "bdist_wheel" and f"-cp{PY_TAG}-cp{PY_TAG}-win_amd64" in u["filename"]]
        if not cand:
            raise SystemExit(f"{nombre} {ver}: no hay wheel cp{PY_TAG} win_amd64 en PyPI")
        u = cand[0]
        esperado = u["digests"]["sha256"]
        w = descargar(u["url"], cache / u["filename"], lambda p, e=esperado: sha256_de(p) == e)
        with zipfile.ZipFile(w) as zf:
            zf.extractall(sp)
            for m in zf.namelist():
                partes = m.split("/")
                if partes[0].endswith(".dist-info") and not m.endswith("/") and (partes[-1].upper().startswith(TEXTOS_LICENCIA) or "licenses" in partes[1:-1]):
                    d = destino_licencias / f"{nombre}-{ver}"
                    d.mkdir(parents=True, exist_ok=True)
                    (d / "_".join(partes[1:])).write_bytes(zf.read(m))
        info(f"instalada {nombre} {ver} ({u['filename']})")
    # PyPI da las licencias dentro de las dist-info; deben quedar en cada dist-info y tambien en LICENCIAS/


# --------------------------------------------------------------------------------------------- app
def copiar_arbol(origen, destino, excluir_dirs=()):
    def ignorar(d, nombres):
        return [n for n in nombres if n == "__pycache__" or n.endswith((".pyc", ".pyo")) or n in excluir_dirs]
    shutil.copytree(origen, destino, ignore=ignorar)


def preparar_app(repo, stage, exe_render):
    app = stage / "app"
    app.mkdir()
    copiar_arbol(repo / "pegcraft", app / "pegcraft")
    copiar_arbol(repo / "sightread", app / "sightread", excluir_dirs=("tests",))
    (app / "scripts").mkdir()
    shutil.copyfile(repo / "scripts" / "grafo_visor.py", app / "scripts" / "grafo_visor.py")
    (app / "bin").mkdir()
    shutil.copyfile(exe_render, app / "bin" / "pegcraft-render.exe")
    return app


def precompilar(stage):
    """.pyc con hash 'unchecked' (no dependen de la fecha de los archivos) y rutas relativas, para que el visor no escriba nada en la carpeta del paquete."""
    py = stage / "python" / "python.exe"
    app = stage / "app"
    correr([py, "-X", "utf8", "-B", "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash",
            "-s", str(app), "-p", "app", app])


# --------------------------------------------------------------------------------------------- textos
CMD = '@echo off\r\n"%~dp0python\\python.exe" -X utf8 -B -m pegcraft %*\r\n'

LEEME = """pegcraft - visor de escenas de Toon Boom Harmony (version {version})
=====================================================================

Que es
  Un lector y renderer abierto de escenas .xstage (subconjunto cutout). Este paquete trae el visor y todo lo que
  necesita (Python incluido): no hay que instalar nada.

Como abrirlo
  1. Descomprime el zip en cualquier carpeta.
  2. Doble clic en pegcraft-visor.exe. En el primer arranque aparece el dialogo "Abrir escena": elige un .xstage
     (para probar: ejemplos\\escena_minima\\escena.xstage). El visor lo hornea y lo muestra.
  3. Menu Archivo > Analizar carpeta de planos: revisa carpetas de escenas y escribe un log de lo que pegcraft no conoce.
  4. Casilla "Acelerar por GPU": usa la GPU; si no hay una compatible, el visor sigue en CPU.

Linea de comandos (sin instalar nada)
  pegcraft.cmd ver ejemplos\\escena_minima\\escena.xstage 1 -o salida.png
  pegcraft.cmd hornear-rango escena.xstage carpeta_de_salida --desde 1 --hasta 10
  pegcraft.cmd analizar carpeta_con_escenas --log analisis --compartible
  pegcraft.cmd --help

Donde escribe
  Los resultados que el visor genera por omision (horneados, logs) van a %LOCALAPPDATA%\\pegcraft\\trabajo.
  La carpeta del paquete no se modifica (puede ser de solo lectura). Las escenas que abres solo se leen.

Requisitos
  Windows 10 u 11, 64 bits. GPU opcional (con Vulkan o DirectX 12; sin ella se usa la CPU).

Licencias
  pegcraft se distribuye bajo MIT o Apache-2.0, a tu eleccion. Las licencias de pegcraft, de Python (PSF), numpy,
  Pillow y de las bibliotecas de Rust del visor estan en la carpeta LICENCIAS.
  pegcraft es un proyecto independiente: no esta afiliado a Toon Boom Animation Inc.; Harmony es marca de su titular.
"""

MIT_GENERICO = """MIT License (texto generico)

Copyright (c) <titulares de derechos de cada crate; ver su propio archivo de licencia en crates/>

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""


def reunir_licencias(repo, stage, licencia_python):
    lic = stage / "LICENCIAS"
    lic.mkdir(exist_ok=True)
    for f in ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE", "ATTRIBUTION.md"):
        shutil.copyfile(repo / f, lic / f)
    sr = lic / "sightread"
    sr.mkdir(exist_ok=True)
    for f in ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE"):
        if (repo / "sightread" / f).is_file():
            shutil.copyfile(repo / "sightread" / f, sr / f)
    shutil.copyfile(licencia_python, lic / "Python-PSF-LICENSE.txt")
    shutil.copyfile(repo / "LICENSE-APACHE", lic / "Apache-2.0.txt")  # texto estandar de Apache-2.0
    (lic / "MIT-generico.txt").write_text(MIT_GENERICO, encoding="utf-8")
    return lic


def zip_determinista(carpeta, destino):
    raiz = carpeta.name
    archivos = sorted(p for p in carpeta.rglob("*") if p.is_file())
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in archivos:
            zi = zipfile.ZipInfo(f"{raiz}/{p.relative_to(carpeta).as_posix()}", FECHA_ZIP)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, p.read_bytes(), compresslevel=9)


def main():
    ap = argparse.ArgumentParser(description="Arma dist/pegcraft-visor-<version>-win64.zip (visor + Python embebido + CLI + licencias).",
                                 epilog="La cabecera del script describe el contenido del paquete.")
    ap.add_argument("--repo", type=Path, default=REPO, help="raiz del repo (por omision, la de este script)")
    ap.add_argument("--dist", type=Path, default=None, help="carpeta de salida (por omision <repo>/dist)")
    ap.add_argument("--target-dir", type=Path, default=None, help="carpeta de cargo (por omision <repo>/target-paquete)")
    ap.add_argument("--cache", type=Path, default=None, help="cache de descargas (por omision %%LOCALAPPDATA%%/pegcraft/cache_empaquetar)")
    ap.add_argument("--sin-compilar", action="store_true", help="no llama a cargo: usa los .exe que ya haya en --target-dir")
    a = ap.parse_args()

    if sys.platform != "win32":
        raise SystemExit("el paquete es para Windows x64")
    repo = a.repo.resolve()
    dist = (a.dist or repo / "dist").resolve()
    target = (a.target_dir or repo / "target-paquete").resolve()
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    cache = (a.cache or base / "pegcraft" / "cache_empaquetar").resolve()
    version = version_del_repo(repo)
    nombre = f"pegcraft-visor-{version}-win64"
    info(f"version {version}; salida {dist / (nombre + '.zip')}")

    exe_visor, exe_render = exes_existentes(target) if a.sin_compilar else compilar(repo, target)

    dist.mkdir(parents=True, exist_ok=True)
    stage = dist / nombre
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()

    shutil.copyfile(exe_visor, stage / "pegcraft-visor.exe")
    py, licencia_py = preparar_python(cache, stage)
    lic = stage / "LICENCIAS"
    lic.mkdir()
    instalar_wheels(cache, py, lic / "python-paquetes")
    preparar_app(repo, stage, exe_render)
    precompilar(stage)
    (stage / "pegcraft.cmd").write_bytes(CMD.encode("ascii"))
    copiar_arbol(repo / "ejemplos", stage / "ejemplos")
    reunir_licencias(repo, stage, licencia_py)
    licencias_crates(repo, lic)
    (stage / "LEEME.txt").write_text(LEEME.format(version=version).replace("\n", "\r\n"), encoding="utf-8")

    zpath = dist / f"{nombre}.zip"
    zip_determinista(stage, zpath)
    h = sha256_de(zpath)
    (dist / f"{nombre}.zip.sha256").write_text(f"{h} *{zpath.name}\n", encoding="ascii")
    info(f"listo: {zpath} ({zpath.stat().st_size / 1e6:.1f} MB) sha256 {h}")


if __name__ == "__main__":
    main()
