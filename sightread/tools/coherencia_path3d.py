"""Prueba de coherencia velocity <-> llaves fijas de las trayectorias 3D de una escena `.xstage`, sin necesidad de Harmony (P34).

En el cuadro de una llave fija (`lockedInTime`) la fracción `velocity` que guardó Harmony, llevada a la curva del modelo (longitud de arco en espacio de matriz),
debe caer en la llave: el error de posición debe ser <= 1e-4 campos. Si no cae, o la escena no la guardó Harmony, la longitud que calcula el modelo no es la que
usó Harmony para esa trayectoria. Detecta también escenas que no guardó Harmony (atributos en orden alfabético: salida de una herramienta de edición).

Uso (PowerShell 5.1), desde la raíz del repo:
    python -I tools\\coherencia_path3d.py escena1.xstage [escena2.xstage ...] [--tope 1e-4] [--json]
Código de salida: 0 = todas coherentes y de Harmony; 2 = alguna incoherente o no guardada por Harmony; 1 = alguna no se pudo leer.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sightread.lector.columnas import ColTrayectoria3D, leer_columnas  # noqa: E402

TOPE_LLAVE = 1e-4        # campos: error de posición admitido en una llave fija
TOPE_COLUMNA_MALA = 1e-3


def guardada_por_harmony(raiz: ET.Element) -> tuple[bool, str]:
    """Heurística sobre el XML: Harmony escribe los atributos en su orden (source, version, build, creator en `<project>`); una herramienta de edición los deja
    en orden alfabético. Devuelve (True, '') o (False, motivo)."""
    if "Harmony" not in (raiz.get("source") or ""):
        return False, f"project@source sin 'Harmony': {raiz.get('source')!r}"
    for etiqueta, el in (("project", raiz), ("column", next(raiz.iter("column"), None))):
        if el is None:
            continue
        claves = list(el.attrib)
        if len(claves) > 2 and claves == sorted(claves):
            return False, f"atributos de <{etiqueta}> en orden alfabético: {claves}"
    return True, ""


def coherencia_de(raiz: ET.Element, tope: float = TOPE_LLAVE) -> dict:
    """Mide la coherencia de todas las trayectorias 3D con velocity y longitud no nula de la escena (`raiz` = `<project>`)."""
    met = raiz.find("options/metrics")
    metricas = {k: float(v) for k, v in (met.attrib.items() if met is not None else []) if v.replace(".", "", 1).lstrip("-").isdigit()}
    n_cols = n_llaves = 0
    hist = {"<=1e-4": 0, "<=1e-3": 0, "<=1e-2": 0, ">1e-2": 0}
    cols_mal, llaves_mal, peores = 0, 0, []
    sin_curva = 0
    for esc in raiz.iter("scene"):
        if esc.find("columns") is None:
            continue
        cols = leer_columnas(esc, metricas)
        for nombre in cols:
            c = cols[nombre]
            if not isinstance(c, ColTrayectoria3D):
                continue
            errs = c.fraccion_en_llaves()
            if not errs:
                sin_curva += 1
                continue
            n_cols += 1
            emax = 0.0
            for _lf, _i, e in errs:
                n_llaves += 1
                emax = max(emax, e)
                hist["<=1e-4" if e <= 1e-4 else "<=1e-3" if e <= 1e-3 else "<=1e-2" if e <= 1e-2 else ">1e-2"] += 1
                llaves_mal += e > tope
            cols_mal += emax > TOPE_COLUMNA_MALA
            peores.append((round(emax, 6), nombre, len(c.P), len({tuple(p) for p in c.P})))
    peores.sort(reverse=True)
    return {"columnas_3d": n_cols, "llaves": n_llaves, "hist": hist, "llaves_sobre_tope": llaves_mal, "columnas_sobre_1e-3": cols_mal,
            "columnas_sin_curva_o_velocity": sin_curva, "peores": peores[:3], "coherente": llaves_mal == 0}


def revisar(ruta, tope: float = TOPE_LLAVE) -> dict:
    """Resultado para un `.xstage`: coherencia + si lo guardó Harmony. No lanza: un archivo ilegible vuelve con `error`."""
    out: dict = {"escena": str(ruta)}
    try:
        raiz = ET.parse(str(ruta)).getroot()
    except (ET.ParseError, OSError) as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    ok, motivo = guardada_por_harmony(raiz)
    out["guardada_por_harmony"] = ok
    if motivo:
        out["motivo_no_harmony"] = motivo
    out.update(coherencia_de(raiz, tope))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("escenas", nargs="+", help="archivos .xstage")
    ap.add_argument("--tope", type=float, default=TOPE_LLAVE, help="error de posición máximo en una llave fija, en campos (por omisión 1e-4)")
    ap.add_argument("--json", action="store_true", help="una línea JSON por escena")
    a = ap.parse_args(argv)
    codigo = 0
    for ruta in a.escenas:
        r = revisar(ruta, a.tope)
        if "error" in r:
            codigo = max(codigo, 1) if codigo != 2 else 2
        elif not r["coherente"] or not r["guardada_por_harmony"]:
            codigo = 2
        if a.json:
            print(json.dumps(r, ensure_ascii=False))
        elif "error" in r:
            print(f"{ruta}: ERROR {r['error']}")
        else:
            estado = "coherente" if r["coherente"] else "INCOHERENTE"
            nota = "" if r["guardada_por_harmony"] else f" | NO GUARDADA POR HARMONY ({r['motivo_no_harmony']})"
            print(f"{ruta}: {estado} | columnas 3D con velocity: {r['columnas_3d']} | llaves: {r['llaves']} {r['hist']} | llaves sobre el tope: "
                  f"{r['llaves_sobre_tope']} | peores (err, col, n_pts, n_distintos): {r['peores']}{nota}")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
