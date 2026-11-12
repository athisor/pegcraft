"""px_ok / px_ok_personajes , IoU de alfa y metrica por grupo (ex medir.py y <datos de trabajo omitidos>)."""
import json
import numpy as np
from PIL import Image, ImageFilter


def componer(p, gris=128):
    """RGBA -> (RGB float sobre gris 50 %, alfa 0..255)."""
    im = np.asarray(Image.open(p).convert("RGBA")).astype(np.float32)
    a = im[..., 3:4] / 255.0
    return (im[..., :3] * a + gris * (1 - a)), im[..., 3]


def metricas(ref, mio, sil=None, T=(24, 8, 0)):
    """px_ok: max|dc| <= T en toda la imagen. Personajes: alfa>8 de `sil` (render solo de los personajes), dilatada ~4 px."""
    A, _ = componer(ref); B, _ = componer(mio)
    d = np.abs(A - B).max(axis=2)
    r = {f"px_ok_T{t}": float((d <= t).mean()) for t in T}
    r["px_ok"] = r["px_ok_T24"]
    if sil is not None:
        s = (np.asarray(Image.open(sil).convert("RGBA"))[..., 3] > 8).astype(np.uint8) * 255
        s = np.asarray(Image.fromarray(s).filter(ImageFilter.MaxFilter(9))) > 0
        r["n_px_personaje"] = int(s.sum())
        for t in T:
            r[f"px_ok_personajes_T{t}"] = float((d[s] <= t).mean()) if s.any() else None
        r["px_ok_personajes"] = r.get("px_ok_personajes_T24")
    return r


def caja_alfa(p, umbral=8, margen=10):
    al = np.asarray(Image.open(p).convert("RGBA"))[..., 3] > umbral
    ys, xs = np.nonzero(al)
    return (max(xs.min() - margen, 0), max(ys.min() - margen, 0), xs.max() + margen, ys.max() + margen)


def metrica_grupo(ref_solo, mio_solo, caja=None, T=24):
    """Un grupo/personaje renderizado SOLO (fondo transparente) en ambos: px_ok dentro de la union de siluetas y IoU de alfa,
    en la caja del alfa de la referencia (+-10 px) o `caja`=(x0,y0,x1,y1). Es la cifra 'Personaje'."""
    x0, y0, x1, y1 = caja or caja_alfa(ref_solo)
    A, aA = componer(ref_solo); B, aB = componer(mio_solo)
    d = np.abs(A - B).max(2)[y0:y1, x0:x1]
    a = aA[y0:y1, x0:x1] > 127; b = aB[y0:y1, x0:x1] > 127
    u = max(int((a | b).sum()), 1)
    return {"caja": [int(x0), int(y0), int(x1), int(y1)], "px_ok": float(((d <= T) & (a | b)).sum() / u), "iou_alfa": float((a & b).sum() / u)}


def main(ref, mio, sil=None, salida_json=None):
    r = metricas(ref, mio, sil)
    print(json.dumps(r))
    if salida_json:
        json.dump(r, open(salida_json, "w"), indent=1)
    return r
