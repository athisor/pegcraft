"""Descomposicion del error de un cuadro en interior / banda de borde (personaje y fondo). Experimento de bordes 11-11-2026.
Uso (desde .):  python -m pegcraft.medir.bordes REF.png MIO.png [--sil REF_SOLO_PERSONAJE.png] [--json salida.json]
Banda de personaje: <=1 px de un pixel con 0,02<alfa<0,98 en `sil` (render solo del personaje de Harmony).
Banda de fondo: gradiente local (3x3) de la referencia >= 12 niveles, fuera de la banda de personaje. Interior: el resto."""
import json
import sys
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from .metricas import componer


def descomponer(ref, mio, sil=None, T=(24, 8, 0), grad_min=12):
    A, _ = componer(ref)
    B, _ = componer(mio)
    d = np.abs(A - B).max(2)
    if sil:
        g = np.asarray(Image.open(sil).convert("RGBA"))[..., 3] / 255.0
        band_c = ndi.binary_dilation((g > 0.02) & (g < 0.98), structure=np.ones((3, 3), bool))
    else:
        band_c = np.zeros(d.shape, bool)
    grad = (ndi.maximum_filter(A, size=(3, 3, 1)) - ndi.minimum_filter(A, size=(3, 3, 1))).max(2)
    band_f = (grad >= grad_min) & ~band_c
    reg = {"banda_personaje": band_c, "banda_fondo": band_f, "interior": ~(band_c | band_f)}
    r = {"px_total": int(d.size)}
    for t in T:
        r[f"px_ok_T{t}"] = float((d <= t).mean())
    for nm, mk in reg.items():
        n = int(mk.sum())
        r[nm] = {"n": n, "frac_img": n / d.size}
        for t in T:
            malos = int(((d > t) & mk).sum())
            r[nm][f"malos_T{t}"] = malos
            r[nm][f"px_ok_T{t}"] = 1 - malos / max(n, 1)
    dch = np.abs(A - B)
    if sil:
        r["banda_personaje"]["error_canal_p50_p90_p99"] = [float(x) for x in np.percentile(dch[band_c], [50, 90, 99])]
    return r


if __name__ == "__main__":
    a = sys.argv[1:]
    opt = lambda k: a[a.index(k) + 1] if k in a else None
    out = descomponer(a[0], a[1], opt("--sil"))
    print(json.dumps(out, indent=1))
    if opt("--json"):
        json.dump(out, open(opt("--json"), "w"), indent=1)
