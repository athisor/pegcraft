"""Plano -> PNG por lotes con GPU (crates\\pegcraft-gpu, vello+wgpu) o CPU (pegcraft-render), y comparacion pixel a pixel.

    python -m pegcraft.gpu.render_lote DIR_plano --frames 22:46 --out carpeta [--gpu|--cpu|--ambos] [--flags "--ss 2 --aa-gauss 0.45 --opacidad-grupo"]
        [--sin-cache] [--lista-json]

Reconstruye el escena.json de cada cuadro con Plano.cuadro(N) (0,5 ms) y lo manda al crate. GPU: UN proceso con el dispositivo abierto para todo el
lote (resumen de tiempos por cuadro en <out>/gpu/resumen.json). CPU: un proceso pegcraft-render por cuadro. --ambos compara los PNG
(<out>/comparacion.json: max dif, % px distintos, % px dif>24 por cuadro).
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[2]
GPU_EXE = RAIZ / "crates" / "pegcraft-gpu" / "target" / "release" / "pegcraft-gpu" + (".exe" if sys.platform == "win32" else "")
FLAGS = "--ss 2 --aa-gauss 0.45 --opacidad-grupo"


def rango(spec, frames):
    if spec in (None, "todos"):
        return list(frames)
    if ":" in spec:
        a, b = spec.split(":")
        return [f for f in frames if int(a) <= f <= int(b)]
    return [int(x) for x in spec.split(",")]


def escribir_escenas(plano_dir, frames, destino):
    from ..compilar.plano import Plano
    t0 = time.perf_counter()
    P = Plano(plano_dir)
    fr = rango(frames, P.frames)
    destino = Path(destino); destino.mkdir(parents=True, exist_ok=True)
    rutas = []
    for n in fr:
        r = destino / f"f{n:04d}.json"
        json.dump(P.cuadro(n), open(r, "w", encoding="utf-8"), ensure_ascii=False)
        rutas.append(r)
    return rutas, time.perf_counter() - t0


def render_gpu(escenas_dir, out, flags, sin_cache=False, extra=()):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    cmd = [str(GPU_EXE), "--lote", str(escenas_dir), "--outdir", str(out), "--resumen", str(out / "resumen.json"), *flags.split(), *extra]
    if sin_cache:
        cmd.append("--sin-cache")
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("pegcraft-gpu fallo: " + r.stderr[-400:])
    return json.loads(r.stdout), time.perf_counter() - t0


def render_cpu(rutas, out, flags):
    from ..medir.render import EXE
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    t = []
    t0 = time.perf_counter()
    for r in rutas:
        t1 = time.perf_counter()
        subprocess.run([str(EXE), str(r), "--out", str(out / (r.stem + ".png")), *flags.split()], check=True, capture_output=True)
        t.append(time.perf_counter() - t1)
    return t, time.perf_counter() - t0


def comparar(dir_a, dir_b, nombres):
    from PIL import Image
    filas = []
    for n in nombres:
        a = np.asarray(Image.open(Path(dir_a) / f"{n}.png").convert("RGBA")).astype(np.int16)
        b = np.asarray(Image.open(Path(dir_b) / f"{n}.png").convert("RGBA")).astype(np.int16)
        d = np.abs(a - b).max(axis=2)
        filas.append({"cuadro": n, "max": int(d.max()), "pct_distintos": round(float((d > 0).mean() * 100), 4), "pct_mayor_24": round(float((d > 24).mean() * 100), 4),
                      "media_dif_en_distintos": round(float(d[d > 0].mean()) if (d > 0).any() else 0.0, 3)})
    return filas


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pegcraft.gpu.render_lote")
    ap.add_argument("plano"); ap.add_argument("--frames", default="todos"); ap.add_argument("--out", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--gpu", action="store_true"); g.add_argument("--cpu", action="store_true"); g.add_argument("--ambos", action="store_true")
    ap.add_argument("--flags", default=FLAGS); ap.add_argument("--sin-cache", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    rutas, t_esc = escribir_escenas(a.plano, a.frames, out / "escenas")
    res = {"cuadros": len(rutas), "escenas_s": round(t_esc, 3)}
    nombres = [r.stem for r in rutas]
    if a.cpu or a.ambos:
        t, tot = render_cpu(rutas, out / "cpu", a.flags)
        res["cpu"] = {"total_s": round(tot, 2), "por_cuadro_s": round(tot / len(t), 3), "cuadros_por_s": round(len(t) / tot, 2)}
    if a.gpu or a.ambos or not a.cpu:
        j, tot = render_gpu(out / "escenas", out / "gpu", a.flags, a.sin_cache)
        res["gpu"] = {"total_proceso_s": round(tot, 2), "pared_lote_s": round(j["pared_ms"] / 1000, 3), "cuadros_por_s": round(j["cuadros_por_s"], 2), "medio_ms": j["medio_ms"], "init_gpu_ms": j["init_gpu_ms"]}
    if a.ambos:
        f = comparar(out / "cpu", out / "gpu", nombres)
        res["comparacion"] = {"max": max(x["max"] for x in f), "pct_distintos_medio": round(sum(x["pct_distintos"] for x in f) / len(f), 4), "pct_mayor_24_medio": round(sum(x["pct_mayor_24"] for x in f) / len(f), 4)}
        json.dump(f, open(out / "comparacion.json", "w", encoding="utf-8"), indent=1)
    json.dump(res, open(out / "resumen_lote.json", "w", encoding="utf-8"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
