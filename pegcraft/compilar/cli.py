"""Subcomandos `compilar` y `render-plano` (python -m pegcraft ...)."""
import json, sys, time, shutil
from pathlib import Path
from . import almacen, plano


def rango(spec, xs):
    if spec == "todos":
        from ..bake import apilado
        r = apilado.X.escena_resumen(xs)
        n = r.get("fotogramas") or r.get("frames") or r.get("n_fotogramas")
        if not n:
            raise SystemExit(f"no pude leer el numero de fotogramas de escena_resumen: {list(r)[:12]}")
        return list(range(1, int(n) + 1))
    if ":" in spec:
        a, b = spec.split(":"); return list(range(int(a), int(b) + 1))
    return [int(x) for x in spec.split(",")]


def compilar(xs, frames, salida, conservar_horneado=False, memo_doc=True, residual=True, depurar_personal=False, **kw):
    """Hornea el rango compartiendo grafo (memo) y almacen de activos, y escribe el plano. Devuelve tiempos y conteos."""
    from ..bake.hornear import hornear
    from . import memo
    if memo_doc:
        memo.activar()
    out = Path(salida); work = out / "_horneado"; work.mkdir(parents=True, exist_ok=True)
    almacen.reset_stats(); almacen.tomar_registro()
    J, REGS, tf = {}, {}, {}
    t_ini = time.perf_counter()
    for f in frames:
        t0 = time.perf_counter()
        ruta, _ = hornear(str(xs), f, str(work), nombre=f"escena_f{f}.json", **kw)
        tf[f] = time.perf_counter() - t0
        J[f] = json.load(open(ruta, encoding="utf-8")); REGS[f] = almacen.tomar_registro()
        print(f"  f{f}: {tf[f]:.2f} s", file=sys.stderr)
    t_hor = time.perf_counter() - t_ini
    t0 = time.perf_counter(); est = plano.escribir(out, xs, frames, J, REGS, residual=residual, depurar_personal=depurar_personal); t_esc = time.perf_counter() - t0
    if not conservar_horneado:
        shutil.rmtree(work, ignore_errors=True)
    return {"plano": str(out / "plano"), **est, "t_hornear_total": round(t_hor, 2), "t_escribir_plano": round(t_esc, 2),
            "t_por_cuadro": {str(k): round(v, 2) for k, v in tf.items()}, "almacen": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in almacen.STATS.items()}, "memo_doc": dict(memo.STATS)}


def main(a):
    if a.cmd == "compilar":
        xs = str(Path(a.xstage))
        if Path(xs).is_dir():
            xs = str(next(Path(xs).glob("*.xstage")))
        res = compilar(xs, rango(a.frames, xs), a.salida, conservar_horneado=a.conservar_horneado,
                       residual=not getattr(a, "sin_residual", False), depurar_personal=getattr(a, "depurar_personal", False))
        print(json.dumps(res, ensure_ascii=False))
    elif a.cmd == "vuelta-plano":
        from . import residual
        ed = [tuple(e.split("=", 1)) for e in (a.editar or [])]
        res = residual.vuelta_plano(Path(a.plano) / "plano" if (Path(a.plano) / "plano" / "harmony").is_dir() else a.plano, a.salida,
                                    editar=ed or None, origen_dir=a.origen)
        res["contradicciones"] = residual.contradicciones(a.plano) if (Path(a.plano) / "plano" / "harmony").is_dir() else []
        print(json.dumps(res, ensure_ascii=False))
        return 0 if (res["bytes_ok"] or (ed and res["solo_las_editadas"])) and not res["contradicciones"] else 1
    else:
        t = plano.render_plano(a.plano, a.frame, a.out, a.salida_json, exacto=not a.f32, flags=a.flags or plano_flags())
        print(json.dumps({k: round(v, 4) for k, v in t.items()}))
    return 0


def plano_flags():
    return ("--aa-gauss", "0.45", "--ss", "2", "--opacidad-grupo")
