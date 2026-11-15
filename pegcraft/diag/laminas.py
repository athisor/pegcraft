"""Laminas de comparacion (ex <datos de trabajo omitidos>, fable2/ver.py, lamina_def.py, integra/lamina_zonas.py y scripts/diag2.py lamina).
Todo compone RGBA sobre gris 50 %. Las zonas son parametros (`--zona nombre=x0,y0,x1,y1,escala`), no estan fijas a un plano."""
import json
import numpy as np, cv2


def sobre(p, g=128):
    im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED).astype(np.float32)
    if im.shape[2] == 3:
        return im
    a = im[..., 3:4] / 255
    return im[..., :3] * a + g * (1 - a)


def _diff(a, b):
    return np.abs(a - b).max(2)


def _d3(d):
    return np.stack([np.clip(d * 4, 0, 255)] * 3, -1)


def _unir(ts):
    return np.concatenate([np.pad(t, ((0, 0), (0, 5), (0, 0)), constant_values=255) for t in ts[:-1]] + [ts[-1]], 1)


def _rotulo(t, txt):
    cv2.putText(t, txt, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)
    return t


def completa(ref, mio, salida):
    """Cuadro completo: referencia | nuestro | diff x4."""
    A, B = sobre(ref), sobre(mio)
    cv2.imwrite(str(salida), np.clip(_unir([A, B, _d3(_diff(A, B))]), 0, 255).astype(np.uint8))


def tira(salida, caja, escala, imagenes, diff=None):
    """Recortes lado a lado (`imagenes`: lista 'etiqueta=ruta' o ruta). caja='auto' = caja del alfa de la primera (+-10). diff=(i,j) agrega |i-j|."""
    ims = []
    for a in imagenes:
        etq, p = a.split("=", 1) if "=" in a else (a[-18:], a)
        ims.append((etq, p, cv2.imread(str(p), cv2.IMREAD_UNCHANGED)))
    if caja == "auto":
        ys, xs = np.nonzero(ims[0][2][..., 3] > 8)
        x0, y0, x1, y1 = max(xs.min() - 10, 0), max(ys.min() - 10, 0), xs.max() + 10, ys.max() + 10
    else:
        x0, y0, x1, y1 = (int(v) for v in caja.split(","))
    rec = [_rotulo(sobre(p)[y0:y1, x0:x1].copy(), etq) for etq, p, _ in ims]
    res = {}
    if diff:
        A, B = rec[diff[0]], rec[diff[1]]
        d = _diff(A, B); aa = ims[diff[0]][2][y0:y1, x0:x1, 3] > 127; bb = ims[diff[1]][2][y0:y1, x0:x1, 3] > 127
        u = max(int((aa | bb).sum()), 1)
        res = {"distintos_T24": int((d > 24).sum()), "total": int(d.size), "iou_alfa": round(float((aa & bb).sum() / u), 4),
               "px_ok_union": round(float(((d <= 24) & (aa | bb)).sum() / u), 4)}
        rec.append(_d3(d / 2))
    t = _unir(rec)
    if escala != 1:
        t = cv2.resize(t, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_CUBIC)
    cv2.imwrite(str(salida), np.clip(t, 0, 255).astype(np.uint8))
    return res


def zonas(ref, salida, renders, zonas):
    """Por cada render ('etiqueta=ruta') y cada zona {nombre: (x0,y0,x1,y1,escala)}: fila referencia | nuestro | diff x4.
    Devuelve por zona/etiqueta px_ok (T=24), px_mal y desplazamiento (dx, dy) por correlacion de fase. Escribe tambien <salida>.json."""
    A = sobre(ref); filas, res = [], {}
    for r in renders:
        etq, p = r.split("=", 1)
        B = sobre(p)
        for z, (x0, y0, x1, y1, esc) in zonas.items():
            a, b = A[y0:y1, x0:x1], B[y0:y1, x0:x1]
            d = _diff(a, b)
            ga, gb = (cv2.cvtColor(np.clip(v, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32) for v in (a, b))
            (dx, dy), _ = cv2.phaseCorrelate(ga, gb, cv2.createHanningWindow(ga.shape[::-1], cv2.CV_32F))
            res.setdefault(z, {})[etq] = {"px_ok": round(float((d <= 24).mean()), 4), "px_mal": int((d > 24).sum()), "dx": round(dx, 2), "dy": round(dy, 2)}
            t = cv2.resize(_unir([a, b, _d3(d)]), None, fx=esc, fy=esc, interpolation=cv2.INTER_CUBIC)
            filas.append(_rotulo(np.clip(t, 0, 255), f"{z} | {etq}: referencia | nuestro | diff x4 ({int((d > 24).sum())} px)"))
    w = max(f.shape[1] for f in filas)
    filas = [np.pad(f, ((0, 6), (0, w - f.shape[1]), (0, 0)), constant_values=255) for f in filas]
    cv2.imwrite(str(salida), np.concatenate(filas, 0).astype(np.uint8))
    json.dump(res, open(str(salida).rsplit(".", 1)[0] + ".json", "w", encoding="utf-8"), indent=1)
    return res
