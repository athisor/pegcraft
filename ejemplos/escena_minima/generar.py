"""Regenera la escena de ejemplo `ejemplos/escena_minima/` (SINTETICA: formas geometricas inventadas, sin datos de produccion).

    python -I ejemplos/escena_minima/generar.py            escribe escena.xstage, elements/, palette-library/ y PALETTE_LIST
    python -I ejemplos/escena_minima/generar.py --verificar  regenera en memoria y compara con lo que hay en disco

Los .tvg los escribe `sightread/sintetico/tvg_minimo.py` (sin CERT ni firma: no son archivos de Harmony); el .xstage lo escribe
`sightread/sintetico/generador.py`. Todo es determinista.
"""
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parents[1] / "sightread" / "sintetico"))
import generador  # noqa: E402
import tvg_minimo as w  # noqa: E402

PALETA = "Formas"
COLORES = [  # (id, nombre, rgba)
    (0x0D00000000000010, "Cielo", (150, 200, 240, 255)),
    (0x0D00000000000011, "Pasto", (90, 170, 80, 255)),
    (0x0D00000000000012, "Rojo", (220, 50, 50, 255)),
    (0x0D00000000000013, "Amarillo", (245, 200, 50, 255)),
    (0x0D00000000000014, "Violeta", (130, 70, 170, 255)),
    (0x0D00000000000015, "Tinta", (25, 25, 35, 255)),
]
ID = {n: i for i, n, _ in COLORES}


def _paleta_tvg():
    return [{"id": i, "rgba": c, "nombre": n, "paleta": PALETA} for i, n, c in COLORES]


def _dibujo(formas):
    """formas: [(contorno, relleno|None, linea|None, grosor)] -> dibujo para tvg_minimo (arte colour para rellenos, line para lapiz)."""
    colour, line = [], []
    for contorno, relleno, linea, grosor in formas:
        c, l = w.forma(contorno, relleno=ID[relleno] if relleno else None, linea=ID[linea] if linea else None, grosor=grosor)
        colour += c
        line += l
    return {"paleta": _paleta_tvg(), "artes": {"colour": colour, "line": line}}


def _poligono(pts):
    return pts + [pts[0]], None


# (carpeta, formas). Coordenadas en unidades de dibujo (marco visible de 3 750 u.d.).
DIBUJOS = [
    ("Fondo", [(w.rectangulo(-1875, -1875, 1875, 1875), "Cielo", None, 0),
               (w.rectangulo(-1875, -1875, 1875, -900), "Pasto", "Tinta", 6)]),
    ("Circulo", [(w.elipse(0, 0, 330, 330), "Rojo", "Tinta", 8)]),
    ("Cuadrado", [(w.rectangulo(-260, -260, 260, 260), "Amarillo", "Tinta", 8)]),
    ("Triangulo", [(_poligono([(-300, -260), (300, -260), (0, 300)]), "Violeta", "Tinta", 8)]),
]


def _plt():
    filas = ["ToonBoomAnimationInc PaletteFile 2"]
    filas += ['Solid "%s" 0x%016x %d %d %d %d' % ((n, i) + c) for i, n, c in COLORES]
    return "\n".join(filas) + "\n"


def _lista():
    return "ToonBoomAnimationInc PaletteList 1\npalette-library/%s LINK %s.plt\n" % (PALETA, PALETA)


def _spec():
    elementos = [{"id": 2 + k, "nombre": n, "carpeta": n, "dibujos": ["1"]} for k, (n, _f) in enumerate(DIBUJOS)]
    columnas = [{"nombre": "Col_" + n, "tipo": 0, "elemento": 2 + k, "secuencias": [{"cuadros": "1-24", "dibujo": "1"}]} for k, (n, _f) in enumerate(DIBUJOS)]
    columnas.append({"nombre": "Col_PosX", "tipo": 3, "puntos": [{"x": "1", "y": -3.0, "constSeg": False}, {"x": "24", "y": 3.0, "constSeg": False}]})
    columnas.append({"nombre": "Col_Giro", "tipo": 3, "puntos": [{"x": "1", "y": 0.0, "constSeg": False}, {"x": "24", "y": 90.0, "constSeg": False}]})
    pos = {"Fondo": {}, "Circulo": {"position/x": {"val": 0, "col": "Col_PosX"}, "position/y": 1.0},
           "Cuadrado": {"position/x": 2.5, "position/y": -2.0, "rotation/anglez": {"val": 0, "col": "Col_Giro"}},
           "Triangulo": {"position/x": -2.5, "position/y": -2.0, "scale/x": 0.8, "scale/y": 0.8}}
    nodos, enlaces = [], []
    for n, _f in DIBUJOS:
        nodos += [{"tipo": "PEG", "nombre": "Peg_" + n, "attrs": pos[n]},
                  {"tipo": "READ", "nombre": n, "attrs": {"drawing/element": {"col": "Col_" + n}}}]
        enlaces += [{"origen": "Peg_" + n, "destino": n}, {"origen": n, "destino": "Composite"}]
    nodos += [{"tipo": "COMPOSITE", "nombre": "Composite"}, {"tipo": "DISPLAY", "nombre": "Pantalla"}]
    enlaces.append({"origen": "Composite", "destino": "Pantalla"})
    return {"nombre": "escena_minima", "fotogramas": 24, "fps": 24, "elementos": elementos, "columnas": columnas, "nodos": nodos, "enlaces": enlaces}


def archivos():
    """{ruta relativa: bytes} de todo el ejemplo."""
    out = {"escena.xstage": generador.a_bytes(_spec()),
           "PALETTE_LIST": _lista().encode("utf-8"),
           "palette-library/%s.plt" % PALETA: _plt().encode("utf-8")}
    for n, formas in DIBUJOS:
        out["elements/%s/%s-1.tvg" % (n, n)] = w.escribir(_dibujo(formas))
    return out


def main():
    ar = archivos()
    if "--verificar" in sys.argv:
        mal = [r for r, b in ar.items() if not (AQUI / r).is_file() or (AQUI / r).read_bytes() != b]
        print("distintos:", mal or "ninguno")
        return 1 if mal else 0
    for r, b in ar.items():
        p = AQUI / r
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    print("escritos", len(ar), "archivos en", AQUI)
    return 0


if __name__ == "__main__":
    sys.exit(main())
