"""Compara dos PNG (lo usa prueba_limpia.ps1 con el Python del paquete): bytes, pixeles distintos e IoU del alfa. Sale con 1 si difieren."""
import hashlib
import sys

import numpy as np
from PIL import Image

a, b = sys.argv[1:3]
iguales_bytes = hashlib.sha256(open(a, "rb").read()).digest() == hashlib.sha256(open(b, "rb").read()).digest()
A = np.asarray(Image.open(a).convert("RGBA")).astype(int)
B = np.asarray(Image.open(b).convert("RGBA")).astype(int)
print("bytes identicos:", iguales_bytes, "| formas", A.shape, B.shape)
if A.shape != B.shape:
    sys.exit(1)
d = np.abs(A - B).max(axis=2)
ma, mb = A[..., 3] > 0, B[..., 3] > 0
iou = (ma & mb).sum() / max(1, (ma | mb).sum())
print("pixeles distintos:", int((d > 0).sum()), "de", d.size, "| max diff", int(d.max()), "| IoU (alfa):", round(float(iou), 6))
sys.exit(0 if int(d.max()) <= 1 and iou >= 0.9999 else 1)
