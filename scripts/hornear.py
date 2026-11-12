"""Wrapper fino (compatibilidad): equivale a `python -m pegcraft hornear ...`. Los defaults NO son los del script antiguo:
ahora --matriz-causal si y --deformadores si; para el estado anterior (0,908): --conectores no --matriz-causal no --deformadores no --desfase 3.425,-1.07.
Version original: archivo\\scripts_sesion\\scripts\\hornear.py"""
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pegcraft.__main__ import main
sys.exit(main(["hornear", *sys.argv[1:]]))
