"""Pruebas de publicar.py con repos temporales sinteticos: python -m pytest tools/publicar"""
import subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import publicar as P

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def repo(archivos):
    d = Path(tempfile.mkdtemp())
    subprocess.run(["git", "-C", str(d), "init", "-q", "-b", "main"], check=True)
    for rel, txt in archivos.items():
        p = d / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(txt, encoding="utf-8")
    subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
    subprocess.run(GIT + ["-C", str(d), "commit", "-q", "-m", "x"], check=True)
    return d


def permitidos(*lineas):
    f = Path(tempfile.mkdtemp()) / "perm.txt"; f.write_text("\n".join(lineas), encoding="utf-8"); return str(f)


class TestPublicar(unittest.TestCase):
    def test_limpio_se_publica_y_filtra_no_permitidos(self):
        o = repo({"pkg/a.py": "x = 1\n", "privado/b.py": "y = 2\n"})
        dest = Path(tempfile.mkdtemp()) / "limpio"
        self.assertEqual(P.main(["--origen", str(o), "--destino", str(dest), "--permitidos", permitidos("pkg/")]), 0)
        self.assertTrue((dest / "pkg" / "a.py").exists())
        self.assertFalse((dest / "privado").exists())
        n = subprocess.run(["git", "-C", str(dest), "rev-list", "--count", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(n, "1")

    def test_sin_commitear_no_entra(self):
        o = repo({"pkg/a.py": "x = 1\n"})
        (o / "pkg" / "nuevo.py").write_text("z = 3\n", encoding="utf-8")
        dest = Path(tempfile.mkdtemp()) / "l"
        P.main(["--origen", str(o), "--destino", str(dest), "--permitidos", permitidos("pkg/")])
        self.assertFalse((dest / "pkg" / "nuevo.py").exists())

    def test_fuga_detiene_y_no_toca_destino(self):
        malas = {"ruta": 'p = r"D:\\\\proyectos\\\\privado"\n', "correo": "a = 'alguien@correo.com'\n",  # publicar: permitir
                 "token": "t = 'ghp_" + "a" * 30 + "'\n", "cred": 'password = "supersecreto"\n'}  # publicar: permitir
        for nombre, txt in malas.items():
            o = repo({"pkg/a.py": txt})
            dest = Path(tempfile.mkdtemp()) / "l"
            self.assertEqual(P.main(["--origen", str(o), "--destino", str(dest), "--permitidos", permitidos("pkg/")]), 2, nombre)
            self.assertFalse(dest.exists(), nombre)

    def test_nombres_prohibidos_y_extension(self):
        o = repo({"pkg/a.py": "# cliente Acme\n", "pkg/e.xstage": "<x/>"})
        proh = permitidos("acme")
        h = P.escanear(P.exportar_head(o, tempfile.mkdtemp()), ["pkg/a.py", "pkg/e.xstage"], ["acme"])
        cats = {c for _, _, c in h}
        self.assertEqual(cats, {"nombre", "extension_bloqueada"})
        # el informe no contiene el texto hallado
        self.assertTrue(all(isinstance(x[1], int) for x in h))

    def test_segunda_publicacion_hace_commit_nuevo_y_borra_retirados(self):
        o = repo({"pkg/a.py": "x = 1\n", "pkg/b.py": "y = 1\n"})
        dest = Path(tempfile.mkdtemp()) / "l"; perm = permitidos("pkg/")
        P.main(["--origen", str(o), "--destino", str(dest), "--permitidos", perm])
        (o / "pkg" / "b.py").unlink(); (o / "pkg" / "a.py").write_text("x = 2\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(o), "add", "-A"], check=True); subprocess.run(GIT + ["-C", str(o), "commit", "-q", "-m", "y"], check=True)
        P.main(["--origen", str(o), "--destino", str(dest), "--permitidos", perm])
        self.assertFalse((dest / "pkg" / "b.py").exists())
        n = subprocess.run(["git", "-C", str(dest), "rev-list", "--count", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(n, "2")

    def test_regex_con_barras_se_respeta(self):
        f = Path(tempfile.mkdtemp()) / "p.txt"; f.write_text(r"\bfoo\b" + "\n", encoding="utf-8")
        self.assertEqual(P.leer_regex(f), [r"\bfoo\b"])
        o = repo({"pkg/a.py": "# el foo azul\n", "pkg/b.py": "# foos\n"})
        h = P.escanear(P.exportar_head(o, tempfile.mkdtemp()), ["pkg/a.py", "pkg/b.py"], P.leer_regex(f))
        self.assertEqual([(r, c) for r, _, c in h], [("pkg/a.py", "nombre")])

    def test_excepcion_marcada(self):
        o = repo({"pkg/a.py": 'p = r"C:\\\\ejemplo\\\\x"  # publicar: permitir\n'})
        dest = Path(tempfile.mkdtemp()) / "l"
        self.assertEqual(P.main(["--origen", str(o), "--destino", str(dest), "--permitidos", permitidos("pkg/"), "--en-seco"]), 0)


if __name__ == "__main__":
    unittest.main()
