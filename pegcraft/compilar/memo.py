"""Cargar el .xstage UNA vez: memoriza `abrir_doc` (XstageDoc) y `SceneGraph.from_xstage` por (ruta, mtime).
MEDIDO (perfil de un horneado, PLANO fN): el .xstage se parsea 8 veces por fotograma (5 abrir_doc + 3 from_xstage) = 1,41 s de 2,10 s perfilados.
Solo lectura: los consumidores de hornear (evaluar, censo, matriz_causal, apilado) no mutan el documento (comprobado: salida identica, (doc interna omitida).
Se activa en `compilar` (no cambia `hornear` suelto). Desactivar: env PEGCRAFT_MEMO_DOC=no."""
import os, sys
from pathlib import Path

_ACTIVO = False
STATS = {"abrir_hit": 0, "abrir_miss": 0, "grafo_hit": 0, "grafo_miss": 0}


def activar():
    global _ACTIVO
    if _ACTIVO or os.environ.get("PEGCRAFT_MEMO_DOC", "si") == "no":
        return False
    from ..bake import apilado            # deja lector_xstage importable
    import lector_xstage.utils.escena_io as io
    from lector_xstage.core.scene_graph import SceneGraph
    orig_abrir, orig_from = io.abrir_doc, SceneGraph.from_xstage.__func__
    docs, grafos = {}, {}

    def _k(ruta):
        p = Path(str(io.xstage_de(ruta))); return (str(p), p.stat().st_mtime_ns)

    def abrir_memo(ruta):
        try:
            k = _k(ruta)
        except OSError:
            return orig_abrir(ruta)
        if k not in docs:
            if len(docs) >= 2:
                docs.pop(next(iter(docs)))
            docs[k] = orig_abrir(ruta); STATS["abrir_miss"] += 1
        else:
            STATS["abrir_hit"] += 1
        return docs[k]

    def from_memo(cls, path):
        try:
            p = Path(str(path)); k = (str(p), p.stat().st_mtime_ns)
        except OSError:
            return orig_from(cls, path)
        if k not in grafos:
            if len(grafos) >= 2:
                grafos.pop(next(iter(grafos)))
            grafos[k] = orig_from(cls, path); STATS["grafo_miss"] += 1
        else:
            STATS["grafo_hit"] += 1
        return grafos[k]

    for mod in list(sys.modules.values()):
        if mod is not None and getattr(mod, "__name__", "").startswith("lector_xstage"):
            for n, v in list(vars(mod).items()):
                if v is orig_abrir:
                    setattr(mod, n, abrir_memo)
    SceneGraph.from_xstage = classmethod(from_memo)
    _ACTIVO = True
    return True
