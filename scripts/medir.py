"""Wrapper fino: equivale a `python -m pegcraft medir ref.png mio.png [--sil sil.png] [--json out.json]`."""
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pegcraft.__main__ import main
sys.exit(main(["medir", *sys.argv[1:]]))
