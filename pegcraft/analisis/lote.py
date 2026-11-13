"""Lote de escenas: `python -m pegcraft analizar <carpeta|xstage...> [--planos lista] --log <ruta_base> [--fotogramas muestra]`.

Salida por stdout (una linea por evento, vaciada al momento, para que el visor muestre el avance):
    escena i/N <ruta>            antes de analizar cada escena
    hecho i/N <segundos> s, K hallazgos
    fin <N> escenas, <K> hallazgos distintos, <segundos> s
El log se escribe INCREMENTAL: `<base>.jsonl` (una linea JSON por evento; matar el proceso es seguro), y tras cada escena se reescribe `<base>.md` (resumen
legible) y `<base>.resumen.json` (lo mismo para maquinas). Lineas del jsonl: `inicio`, `escena`, `hallazgo` (uno por categoria+clave y escena), `fin`.
Las escenas se leen y nunca se escriben: sirven planos de produccion.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True


class CompartibleContaminado(Exception):
    """El log compartible no paso la verificacion; `args[0]` = lista de (campo, motivo). El archivo se borro."""


def descubrir(entradas) -> list[Path]:
    """`.xstage` de las entradas: un archivo tal cual, una carpeta recursivamente (ordenados, sin repetir)."""
    out, vistos = [], set()
    for e in entradas:
        p = Path(e)
        if p.is_dir():
            hallados = sorted(p.rglob("*.xstage"))
        elif p.is_file():
            hallados = [p]
        else:
            raise FileNotFoundError(f"no existe: {e}")
        for x in hallados:
            k = os.path.normcase(os.path.abspath(x))
            if k not in vistos:
                vistos.add(k); out.append(x)
    return out


def filtrar_planos(escenas: list[Path], planos: str | None) -> list[Path]:
    """`planos`: archivo de texto con una ruta de .xstage por linea, o lista separada por comas de trozos de ruta (sin distinguir mayusculas)."""
    if not planos:
        return escenas
    pf = Path(planos)
    if pf.is_file():
        quiero = {os.path.normcase(os.path.abspath(l.strip())) for l in pf.read_text(encoding="utf-8").splitlines() if l.strip()}
        return [x for x in escenas if os.path.normcase(os.path.abspath(x)) in quiero]
    trozos = [t.strip().lower() for t in planos.split(",") if t.strip()]
    return [x for x in escenas if any(t in str(x).lower() for t in trozos)]


# ------------------------------------------------------------------ resumen
def resumir(jsonl: Path) -> dict:
    """Resumen agrupado por (categoria, clave) a partir del jsonl (sirve tambien para un log interrumpido)."""
    escenas, hall = [], defaultdict(lambda: {"escenas": set(), "n": 0, "ejemplos": []})
    for linea in Path(jsonl).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(linea)
        except ValueError:
            continue
        if r.get("t") == "escena":
            escenas.append(r)
        elif r.get("t") == "hallazgo":
            h = hall[(r["categoria"], r["clave"])]
            h["escenas"].add(r["escena"]); h["n"] += r.get("n", 1)
            if len(h["ejemplos"]) < 4:
                h["ejemplos"].append({"escena": r["escena"], "nodos": r.get("nodos", [])[:3], "ejemplo": r.get("ejemplo")})
    por_cat: dict[str, dict] = defaultdict(lambda: {"claves": 0, "escenas": set(), "n": 0})
    for (cat, _), h in hall.items():
        c = por_cat[cat]; c["claves"] += 1; c["escenas"] |= h["escenas"]; c["n"] += h["n"]
    top = sorted(({"categoria": c, "clave": k, "escenas": len(h["escenas"]), "n": h["n"], "ejemplos": h["ejemplos"]} for (c, k), h in hall.items()),
                 key=lambda x: (-x["escenas"], -x["n"], x["categoria"], x["clave"]))
    ts = [e["t_s"] for e in escenas if "t_s" in e]
    return {
        "escenas": len(escenas),
        "escenas_con_hallazgos": sum(1 for e in escenas if e.get("n_hallazgos")),
        "escenas_con_error": sum(1 for e in escenas if e.get("errores")),
        "hallazgos_distintos": len(hall),
        "t_total_s": round(sum(ts), 2), "t_medio_s": round(sum(ts) / len(ts), 2) if ts else 0.0, "t_max_s": round(max(ts), 2) if ts else 0.0,
        "por_categoria": {c: {"claves": v["claves"], "escenas": len(v["escenas"]), "n": v["n"]} for c, v in sorted(por_cat.items(), key=lambda kv: -len(kv[1]["escenas"]))},
        "top": top[:60],
        "mas_lentas": sorted(({"escena": e["escena"], "t_s": e["t_s"], "nodos": e.get("nodos")} for e in escenas if "t_s" in e), key=lambda x: -x["t_s"])[:5],
    }


def _md(r: dict, base: Path, parcial: bool) -> str:
    L = [f"# Analisis de escenas{' (parcial)' if parcial else ''}", "",
         f"- Escenas: {r['escenas']} ({r['escenas_con_hallazgos']} con hallazgos, {r['escenas_con_error']} con errores de lectura)",
         f"- Hallazgos distintos (categoria, clave): {r['hallazgos_distintos']}",
         f"- Tiempo por escena: medio {r['t_medio_s']} s, maximo {r['t_max_s']} s, total {r['t_total_s']} s",
         f"- Log: `{base.with_suffix('.jsonl')}`", "", "## Por categoria", "", "| categoria | claves | escenas | n |", "|---|---:|---:|---:|"]
    for c, v in r["por_categoria"].items():
        L.append(f"| {c} | {v['claves']} | {v['escenas']} | {v['n']} |")
    L += ["", "## Mas frecuentes (por numero de escenas)", ""]
    for i, h in enumerate(r["top"][:30], 1):
        L.append(f"{i}. **{h['categoria']}** / `{h['clave']}` - {h['escenas']} escena(s), n={h['n']}")
        for ej in h["ejemplos"][:2]:
            nodos = ", ".join(ej["nodos"][:3])
            L.append(f"    - {Path(ej['escena']).parent.name}/{Path(ej['escena']).name}" + (f": {nodos}" if nodos else ""))
    if r["mas_lentas"]:
        L += ["", "## Escenas mas lentas", ""] + [f"- {x['t_s']} s ({x['nodos']} nodos) {x['escena']}" for x in r["mas_lentas"]]
    return "\n".join(L) + "\n"


def _escribir(ruta: Path, texto: str) -> None:
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, ruta)


def analizar(entradas, log_base, planos: str | None = None, fotogramas="muestra", escenas: list[Path] | None = None, salida=lambda s: print(s, flush=True),
             compartible: bool = False) -> dict:
    """Analiza las escenas y escribe el log. Con `compartible` escribe ademas `<base>_compartible.json` (sin rutas ni nombres; ver compartible.py)."""
    from .escena import analizar_escena
    from .compartible import Compartible
    from .verificar import verificar
    comp = Compartible() if compartible else None
    todos_sens: set[str] = set()
    final = Path(log_base).with_suffix("").with_name(Path(log_base).with_suffix("").name + "_compartible.json")
    parcial = final.with_name(final.name + ".parcial")
    lista = escenas if escenas is not None else filtrar_planos(descubrir(entradas), planos)
    base = Path(log_base).with_suffix("")
    base.parent.mkdir(parents=True, exist_ok=True)
    jl = base.with_suffix(".jsonl")
    n = len(lista)
    t0 = time.perf_counter()
    with open(jl, "w", encoding="utf-8", newline="\n") as fh:
        def w(obj):
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n"); fh.flush()
        w({"t": "inicio", "escenas": n, "fotogramas": str(fotogramas), "entradas": [str(x) for x in (entradas or [])], "hora": time.strftime("%Y-%m-%d %H:%M:%S")})
        for i, xs in enumerate(lista, 1):
            salida(f"escena {i}/{n} {xs}")
            try:
                r = analizar_escena(xs, fotogramas)
            except KeyboardInterrupt:
                raise
            except BaseException as ex:  # noqa: BLE001 - una escena que revienta no detiene el lote
                r = {"escena": str(xs), "n_fotogramas": None, "fotogramas": [], "nodos": None, "t_s": 0.0, "etapas_s": {},
                     "hallazgos": [{"categoria": "error_lectura", "clave": f"analisis: {type(ex).__name__}", "n": 1, "nodos": [], "fotogramas": [], "ejemplo": str(ex)[:300]}]}
            hs = r.pop("hallazgos")
            sens = r.pop("sensibles", [])           # nombres propios de la escena: nunca al log
            if comp is not None:
                comp.agregar({**r, "sensibles": sens}, hs)
                todos_sens.update(sens)
                comp.escribir(parcial)          # sin verificar todavia: solo se llama «_compartible.json» al terminar y pasar la verificacion
            errores = sum(1 for h in hs if h["categoria"] == "error_lectura")
            w({"t": "escena", "i": i, "n": n, **r, "n_hallazgos": len(hs), "errores": errores})
            for h in hs:
                w({"t": "hallazgo", "escena": str(xs), **h})
            res = resumir(jl)
            _escribir(base.with_suffix(".md"), _md(res, base, parcial=i < n))
            _escribir(base.with_suffix(".resumen.json"), json.dumps({**res, "terminado": i == n, "jsonl": str(jl), "md": str(base.with_suffix(".md"))}, ensure_ascii=False, indent=1))
            salida(f"hecho {i}/{n} {r['t_s']} s, {len(hs)} hallazgos")
        w({"t": "fin", "escenas": n, "t_s": round(time.perf_counter() - t0, 2)})
    res = resumir(jl)
    _escribir(base.with_suffix(".md"), _md(res, base, parcial=False))
    _escribir(base.with_suffix(".resumen.json"), json.dumps({**res, "terminado": True, "jsonl": str(jl), "md": str(base.with_suffix(".md"))}, ensure_ascii=False, indent=1))
    if comp is not None:
        comp.escribir(parcial)
        problemas = verificar(parcial, sensibles=todos_sens)
        if problemas:                               # se niega a dejar el archivo
            parcial.unlink(missing_ok=True)
            raise CompartibleContaminado(problemas)
        os.replace(parcial, final)
        salida(f"compartible {final}")
    salida(f"fin {n} escenas, {res['hallazgos_distintos']} hallazgos distintos, {round(time.perf_counter() - t0, 1)} s")
    return res
