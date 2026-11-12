"""Diagnostico pieza por pieza: el render SOLO de Harmony (render_escena con solo_grupos/solo) contra el nuestro (ex diag2_solo.py,
<datos de trabajo omitidos> y <datos de trabajo omitidos>). Cifras: caja, IoU de alfa, ECC afin (escala/traslacion/cizalla; signo negativo =
espejo) y distancia de contorno (media, p95, max, px)."""
import json, os
import numpy as np, cv2
from ..medir.render import renderizar_pieza_sola

alfa = lambda p: cv2.imread(str(p), cv2.IMREAD_UNCHANGED)[..., 3].astype(np.float32) / 255.0


def caja(a, u=.03):
    m = a > u
    if not m.any():
        return None
    xs = np.nonzero(m.any(0))[0]; ys = np.nonzero(m.any(1))[0]
    return [int(xs[0]), int(xs[-1]), int(ys[0]), int(ys[-1])]


def _borde(m):
    return m & ~cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)


def contorno(A, B):
    """IoU de alfa>0,5 y distancia de contorno en ambos sentidos."""
    a, b = A > .5, B > .5
    if a.sum() < 20 or b.sum() < 20:
        return {"iou": None}
    r = {"iou": round(float((a & b).sum() / (a | b).sum()), 4)}
    da = cv2.distanceTransform((~_borde(a)).astype(np.uint8), cv2.DIST_L2, 5)
    db = cv2.distanceTransform((~_borde(b)).astype(np.uint8), cv2.DIST_L2, 5)
    d = np.concatenate([da[_borde(b)], db[_borde(a)]])
    r.update(cont_media=round(float(d.mean()), 2), cont_p95=round(float(np.percentile(d, 95)), 2), cont_max=round(float(d.max()), 1))
    return r


def ecc(A, B):
    try:
        bl = lambda x: cv2.GaussianBlur(x, (0, 0), 4)
        W = np.eye(2, 3, dtype=np.float32)
        _, W = cv2.findTransformECC(bl(A), bl(B), W, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 500, 1e-7), None, 5)
        return {"sx_sy": [round(float(W[0, 0]), 3), round(float(W[1, 1]), 3)], "t": [round(float(W[0, 2]), 1), round(float(W[1, 2]), 1)],
                "cizalla": [round(float(W[0, 1]), 3), round(float(W[1, 0]), 3)]}
    except cv2.error:
        return "no converge"


def solos(escena_json, carpeta_solo, salida, pares, fotograma=22, capas=None, sin_recorte=False):
    """pares: ['estado=Top/.../READ', ...]; el PNG de Harmony es <carpeta_solo>/<estado>-<fotograma:04d>.png (alfa).
    Para varias piezas en un mismo solo: 'estado=idA+idB'. Escribe <salida>/resumen.json."""
    os.makedirs(salida, exist_ok=True)
    res = {}
    for kv in pares:
        est, rid = kv.split("=", 1)
        png = os.path.join(salida, f"{est}.png")
        ok = renderizar_pieza_sola(escena_json, rid.split("+"), png, capas, sin_recorte)
        B = alfa(png) if ok else np.zeros((1080, 1920), np.float32)
        A = alfa(os.path.join(carpeta_solo, f"{est}-{fotograma:04d}.png"))
        r = {"caja_ref": caja(A), "caja_mio": caja(B), "px_ref": int((A > .5).sum()), "px_mio": int((B > .5).sum())}
        if r["px_ref"] > 50 and r["px_mio"] > 50:
            r.update(contorno(A, B)); r["ecc"] = ecc(A, B)
        res[est] = r
        print(est, json.dumps(r))
    json.dump(res, open(os.path.join(salida, "resumen.json"), "w", encoding="utf-8"), indent=1)
    return res
