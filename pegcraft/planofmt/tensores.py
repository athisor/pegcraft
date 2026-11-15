"""D-Tab para el plano exportado: diccionario JSON + safetensors (keys, key_interp, channel_offsets, exposure_runs, exposure_offsets, baked).

baked F32 [frames, piezas*BK]: por pieza BK=12 columnas contiguas (48 bytes, multiplo de 16 para vec4 en GPU):
  0..5  matriz mundo 2x3 fila a fila [a,b,tx,c,d,ty] (campos Harmony)   6 opacidad   7 indice de dibujo (exacto en f32 < 2^24; -1 = ninguno)
  8 orden de apilado   9 z de cadena   10 visible (1/0)   11 relleno (0)
Orden de las piezas = orden de `piezas` del diccionario (mismo que los pegs de definition.json).
"""
import json
from pathlib import Path
import numpy as np
from safetensors.numpy import save_file, load_file
from . import comun

BK = 12


def escribir(plano, jsons):
    """jsons = {frame: escena.json dict del horneado}. Escribe plano/anim/escena.tensores.{json,safetensors}."""
    pl = Path(plano)
    an = json.load(open(pl / "anim" / "escena.anim.json", encoding="utf-8"))
    sd = json.load(open(pl / "anim" / "escena.x-harmony.json", encoding="utf-8"))
    chs = an["channels"] + an["extension_channels"]
    keys, interp, offs = [], [], [0]
    for c in chs:
        for k in c["curve"]["keyframes"]:
            keys.append([k["time"], k["value"], 0.0, 0.0, 0.0, 0.0]); interp.append(0)   # 0 = Hold (sin manijas)
        offs.append(len(keys))
    dids = sorted(sd["dibujos"]); di = {d: i for i, d in enumerate(dids)}
    runs, eoffs = [], [0]
    for e in an["exposure"]:
        for s, n, d in e["runs"]:
            runs.append([s, n, di[d]])
        eoffs.append(len(runs))
    frames = sorted(jsons); piezas = list(sd["piezas"])
    bk = np.zeros((len(frames), len(piezas) * BK), np.float32); bk[:, 7::BK] = -1
    for fi, f in enumerate(frames):
        # misma regla de nombres que exportar._nombres
        from .exportar import _nombres
        for k, p in zip(_nombres(jsons[f]["piezas"]), jsons[f]["piezas"]):
            o = piezas.index(k) * BK
            (a, b, tx), (c, d, ty) = p["matriz_campo"]
            bk[fi, o:o + 12] = [a, b, tx, c, d, ty, p["opacidad"], di[Path(p["dibujo"]).stem], p["orden"], p["z"], 1.0, 0.0]
    t = {"keys": np.array(keys, np.float64).reshape(-1, 6), "key_interp": np.array(interp, np.uint8),
         "channel_offsets": np.array(offs, np.uint32), "exposure_runs": np.array(runs, np.uint32).reshape(-1, 3),
         "exposure_offsets": np.array(eoffs, np.uint32), "baked": bk}
    save_file(t, str(pl / "anim" / "escena.tensores.safetensors"))
    json.dump({"canales": [{"path": c["path"], "attribute": c["attribute"]} for c in chs],
               "pistas_exposicion": [{"path": e["path"], "level": e["level"]} for e in an["exposure"]],
               "dibujos": dids, "baked": {"frames": frames, "piezas": piezas, "columnas": BK, "dtype": "F32", "por_pieza": [
                   "a", "b", "tx", "c", "d", "ty", "opacidad", "dibujo", "orden", "z", "visible", "relleno"]}},
              open(pl / "anim" / "escena.tensores.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return {k: list(v.shape) for k, v in t.items()}


def verificar(plano, jsons):
    """Relee los tensores y compara: curvas contra anim.json, baked contra las matrices del horneado. Devuelve el error maximo."""
    pl = Path(plano)
    an = json.load(open(pl / "anim" / "escena.anim.json", encoding="utf-8"))
    t = load_file(str(pl / "anim" / "escena.tensores.safetensors"))
    dic = json.load(open(pl / "anim" / "escena.tensores.json", encoding="utf-8"))
    chs = an["channels"] + an["extension_channels"]; err = 0.0
    for i, c in enumerate(chs):
        a, b = int(t["channel_offsets"][i]), int(t["channel_offsets"][i + 1])
        ks = c["curve"]["keyframes"]
        assert b - a == len(ks)
        for j, k in enumerate(ks):
            err = max(err, abs(t["keys"][a + j][0] - k["time"]), abs(t["keys"][a + j][1] - k["value"]))
    bk = t["baked"]; eb = 0.0
    for fi, f in enumerate(dic["baked"]["frames"]):
        from .exportar import _nombres
        for k, p in zip(_nombres(jsons[f]["piezas"]), jsons[f]["piezas"]):
            o = dic["baked"]["piezas"].index(k) * BK
            m = [x for r in p["matriz_campo"] for x in r]
            eb = max(eb, float(np.max(np.abs(bk[fi, o:o + 6] - np.array(m, np.float32)))))
    return {"err_curvas_f64": err, "err_baked_f32": eb, "bytes_safetensors": (pl / "anim" / "escena.tensores.safetensors").stat().st_size}
