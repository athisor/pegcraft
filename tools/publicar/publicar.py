"""publicar: lleva a un repo LIMPIO solo lo commiteado y permitido del repo de desarrollo, tras un escaner anti-fuga.

Uso:  python tools/publicar/publicar.py --destino <carpeta> [--origen <repo>] [--permitidos publicar.permitidos]
                                         [--prohibidos prohibidos.local.txt] [--fixtures fixtures.permitidos] [--autor "nombre <correo>"] [--mensaje TXT] [--empujar]

Reglas:
  1. Parte de `git archive HEAD` del origen: el trabajo sin commitear nunca entra.
  2. Copia SOLO las rutas listadas en el archivo de permitidos (prefijos de carpeta o archivos exactos; `#` comenta).
  3. Escanea lo copiado: rutas absolutas, UNC, usuarios, correos, claves/tokens, archivos binarios o de produccion
     (por extension) y, si se da, los NOMBRES PROHIBIDOS de un archivo local (una expresion regular por linea).
     Si algo falla, se detiene con codigo 2 SIN tocar el destino. El informe da archivo:linea:categoria, nunca el texto hallado.
  4. Escribe en el destino (repo git propio, con historial propio) y hace un commit nuevo con autor neutro.
  5. `--empujar` hace `git push` al remoto del destino; sin el flag no se sube nada.

  6. Los .xstage estan bloqueados por extension, salvo los de las rutas de `fixtures.permitidos` (escenas SINTETICAS de pruebas):
     ahi deben pesar menos de 200 KB, no llevar `checksumValidation`, rutas absolutas ni ningun nombre de prohibidos.local.txt.
     Ver tools/publicar/prohibidos.local.txt.ejemplo.

El archivo de nombres prohibidos NO debe versionarse (contiene justo lo que se quiere ocultar): usar `prohibidos.local.txt`.
"""
import argparse, fnmatch, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

PATRONES = {
    "ruta_disco": re.compile(r"\b[A-Za-z]:[\\/]{1,2}[\w.\-]{2,}"),
    "ruta_unc": re.compile(r"\\\\[\w.\-]{2,}\\[\w.\-$]{1,}"),
    "ruta_usuario": re.compile(r"(?i)(/Users/|/home/|\\Users\\|\\\\Users\\\\)[\w.\-]{2,}"),
    "correo": re.compile(r"[\w.+\-]+@(?!example\.(invalid|com|org)\b)[\w\-]+\.[A-Za-z]{2,}"),
    "token": re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{20,}"),
    "clave_privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    "credencial": re.compile(r"""(?i)\b(api[_-]?key|secret|passw(or)?d|token)\b\s*[:=]\s*['"][^'"\s]{6,}['"]"""),
}
EXT_BLOQUEADAS = {".xstage", ".tvg", ".safetensors", ".sqlite", ".db", ".zip", ".rar", ".7z", ".exe", ".dll", ".mp4", ".mov", ".wav",
                  ".psd", ".plt", ".sboard", ".sbpz", ".env", ".pem", ".key", ".pfx"}
EXT_TEXTO = {".py", ".rs", ".toml", ".md", ".txt", ".json", ".yml", ".yaml", ".ps1", ".cmd", ".sh", ".cfg", ".ini", ".html", ".css", ".js",
             ".svg", ".lock", ".gitignore", ".permitidos", ".ejemplo", ".xml", ".gitattributes", ""}
EXT_FIXTURE = {".xstage"}                     # unica extension bloqueada que puede admitirse, solo en las rutas de fixtures.permitidos
MAX_BYTES = 1_500_000
MAX_FIXTURE = 200_000
IGNORAR_LINEA = "publicar: permitir"          # comentario en la linea para excepciones revisadas a mano


def leer_lista(ruta):
    out = []
    for l in Path(ruta).read_text(encoding="utf-8").splitlines():
        l = l.split("#", 1)[0].strip()
        if l:
            l = l.replace("\\", "/")
            while l.startswith("./"):        # solo el prefijo "./": lstrip(".") se comia el punto de ".gitignore"
                l = l[2:]
            out.append(l.lstrip("/"))
    return out


def leer_regex(ruta):
    """Una expresion regular por linea; `#` solo comenta si va al inicio de la linea (no se tocan las barras)."""
    return [l.strip() for l in Path(ruta).read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")]


def permitido(rel, lista):
    for p in lista:
        if p.endswith("/"):
            if rel.startswith(p):
                return True
        elif rel == p or rel.startswith(p + "/") or fnmatch.fnmatch(rel, p):
            return True
    return False


def exportar_head(origen, tmp):
    """git archive HEAD -> tmp (solo lo commiteado)."""
    zip_p = Path(tmp) / "head.tar"
    subprocess.run(["git", "-C", str(origen), "archive", "--format=tar", "-o", str(zip_p), "HEAD"], check=True)
    dst = Path(tmp) / "head"
    dst.mkdir()
    subprocess.run(["tar", "-xf", str(zip_p), "-C", str(dst)], check=True)
    return dst


def escanear(raiz, rutas, prohibidos=(), fixtures=()):
    """-> lista de (ruta relativa, linea|0, categoria). No devuelve el texto encontrado.

    `fixtures` = prefijos (formato de publicar.permitidos) donde se admite un .xstage SINTETICO; ahi se exige ademas:
    menos de MAX_FIXTURE bytes, sin `checksumValidation` y (como todo texto) sin rutas absolutas ni nombres prohibidos.
    Un .xstage fuera de esos prefijos sigue bloqueado por extension."""
    hallazgos = []
    nombres = [re.compile(p, re.I) for p in prohibidos]
    for rel in rutas:
        p = Path(raiz) / rel
        ext = p.suffix.lower()
        es_fixture = ext in EXT_FIXTURE and permitido(rel, fixtures)
        if ext in EXT_BLOQUEADAS and not es_fixture:
            hallazgos.append((rel, 0, "extension_bloqueada")); continue
        if p.stat().st_size > (MAX_FIXTURE if es_fixture else MAX_BYTES):
            hallazgos.append((rel, 0, "fixture_grande" if es_fixture else "archivo_grande")); continue
        for n in nombres:                                   # nombres tambien en la RUTA
            if n.search(rel):
                hallazgos.append((rel, 0, "nombre_en_ruta"))
        if ext not in EXT_TEXTO and not es_fixture:
            hallazgos.append((rel, 0, "tipo_desconocido")); continue
        try:
            texto = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            hallazgos.append((rel, 0, "no_es_utf8")); continue
        if rel.endswith("Cargo.lock"):
            continue
        for i, linea in enumerate(texto.splitlines(), 1):
            if IGNORAR_LINEA in linea:
                continue
            if es_fixture and "checksumValidation" in linea:
                hallazgos.append((rel, i, "checksum_en_fixture"))
            for cat, rx in PATRONES.items():
                if rx.search(linea):
                    hallazgos.append((rel, i, cat))
            for n in nombres:
                if n.search(linea):
                    hallazgos.append((rel, i, "nombre"))
    return hallazgos


def seleccionar(raiz, permitidos):
    todo = [p.relative_to(raiz).as_posix() for p in Path(raiz).rglob("*") if p.is_file() and ".git" not in p.relative_to(raiz).parts]
    return sorted(r for r in todo if permitido(r, permitidos))


def sincronizar(raiz, rutas, destino, autor, mensaje, empujar=False):
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    if not (destino / ".git").exists():
        subprocess.run(["git", "-C", str(destino), "init", "-q", "-b", "main"], check=True)
    # borrar de la copia lo que ya no esta permitido o ya no existe en HEAD
    previos = subprocess.run(["git", "-C", str(destino), "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    for r in previos:
        if r not in rutas and (destino / r).exists():
            (destino / r).unlink()
    for r in rutas:
        d = destino / r
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(raiz) / r, d)
    subprocess.run(["git", "-C", str(destino), "add", "-A"], check=True)
    cambios = subprocess.run(["git", "-C", str(destino), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip()
    if not cambios:
        return "sin cambios"
    nombre, correo = re.match(r"(.*?)\s*<(.*)>", autor).groups()
    subprocess.run(["git", "-C", str(destino), "-c", f"user.name={nombre}", "-c", f"user.email={correo}", "commit", "-q", "-m", mensaje], check=True)
    if empujar:
        subprocess.run(["git", "-C", str(destino), "push"], check=True)
    return "commit nuevo" + (" y push" if empujar else "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origen", default=".")
    ap.add_argument("--destino", required=True)
    ap.add_argument("--permitidos", default=None, help="def.: publicar.permitidos junto a este script")
    ap.add_argument("--prohibidos", default=None, help="regex por linea, p. ej. nombres de clientes (NO versionar)")
    ap.add_argument("--fixtures", default=None, help="def.: fixtures.permitidos junto a este script (rutas donde se admite un .xstage sintetico)")
    ap.add_argument("--autor", default="publicador <publicador@example.invalid>")
    ap.add_argument("--mensaje", default="Actualizacion desde el repo de desarrollo")
    ap.add_argument("--empujar", action="store_true")
    ap.add_argument("--en-seco", action="store_true", help="solo escanear")
    a = ap.parse_args(argv)
    perm = a.permitidos or str(Path(__file__).with_name("publicar.permitidos"))
    lista = leer_lista(perm)
    prohibidos = leer_regex(a.prohibidos) if a.prohibidos else []
    fx = a.fixtures or str(Path(__file__).with_name("fixtures.permitidos"))
    fixtures = leer_lista(fx) if Path(fx).exists() else []
    with tempfile.TemporaryDirectory() as tmp:
        raiz = exportar_head(a.origen, tmp)
        rutas = seleccionar(raiz, lista)
        if not rutas:
            print("nada permitido en HEAD: revisa el archivo de permitidos"); return 2
        h = escanear(raiz, rutas, prohibidos, fixtures)
        if h:
            print(f"DETENIDO: {len(h)} hallazgos en {len({x[0] for x in h})} archivos (destino sin tocar)")
            for rel, ln, cat in h[:100]:
                print(f"  {rel}:{ln}:{cat}")
            return 2
        print(f"escaner limpio: {len(rutas)} archivos permitidos")
        if a.en_seco:
            return 0
        print(sincronizar(raiz, rutas, a.destino, a.autor, a.mensaje, a.empujar))
    return 0


if __name__ == "__main__":
    sys.exit(main())
