"""Rellenos GRADIENTE (Linear/Radial) como post-proceso del conversor oficial .tvg -> SVG (svg.py del lector .tvg externo, que no se toca).

Que se sabe (MEDIDO en banco\\PLANO, ver (doc interna omitida):
- El color de un relleno es un id de 8 B; en la paleta .plt (declarada) ese id es una fila `Gradient <nombre> 0x<id> Linear|Radial` + paradas
  (posicion 0-100, R G B A).
- La GEOMETRIA no esta en la paleta: esta en el registro TGCO del trazo (114 B): [0]=01, [1:49] = 6 f64 = matriz afin 2x3 (a b c d e f, estilo SVG
  matrix) del espacio del gradiente al espacio del dibujo (unidades de dibujo, y arriba), [49:57] = id de color. En espacio de gradiente el eje
  Linear es u en [0,1] (parada p% = u p/100) y v en [-0,5, 0,5] perpendicular. VENTANAS: a=d=4687,484 = ancho = alto del bbox, e = x minimo, f = y central.
- Radial: SUPUESTO (sin ejemplo en PLANO/PLANO): circulo de centro (0,0), radio 0,5 en espacio de gradiente (mismo cuadro v in [-0,5, 0,5]).

Salida: SVG con <defs><linearGradient|radialGradient gradientUnits="userSpaceOnUse" gradientTransform="matrix(..)"> y fill="url(#...)".
"""
import re, struct, sys
from pathlib import Path

import os
TVG = os.environ.get("PEGCRAFT_TVG_DIR", "")   # carpeta del lector .tvg (dependencia externa, ver LIMPIEZA_PENDIENTE.md)


def _cargar_tvg():
    """Importa los modulos del conversor oficial sin pisar otros modulos `svg`/`arbol` ya cargados en el proceso."""
    import importlib
    nombres = ("geometria", "svg", "plt_escena", "plt_formato", "arbol", "contenedor", "tvg")
    guardados = {n: sys.modules.pop(n) for n in nombres if n in sys.modules}
    sys.path.insert(0, TVG)
    try:
        mods = {n: importlib.import_module(n) for n in ("geometria", "svg", "plt_escena", "plt_formato")}
    finally:
        sys.path.remove(TVG)
        for n in nombres:
            sys.modules.pop(n, None)
        sys.modules.update(guardados)
    return mods


_M = _cargar_tvg()
G, S, PE, P = _M["geometria"], _M["svg"], _M["plt_escena"], _M["plt_formato"]

_MATS = {}      # id de color (hex) -> [matrices vistas en TGCO de 114 B]
_orig_id_tgco = G._id_tgco


def _id_tgco_mat(cuerpo):
    cid = _orig_id_tgco(cuerpo)
    # 114 B (rigs nuevos, tras el id: 0d 01 + dos matrices 2x2) o 66 B (TGCO corto: 01 + 6 f64 + id + 00 + 8 B ff; visto en BG_PLANO y BG_PLANO,
    # donde el relleno Gradient lleva este registro y antes "no se dibujaba" por filtrar solo 114 B). Misma matriz afin en [1:49] [M, 11-11-2026].
    if len(cuerpo) in (66, 114) and cuerpo[0] == 1:
        _MATS.setdefault(cid, []).append(struct.unpack_from("<6d", cuerpo, 1))
    return cid


def paradas_escena(escena, elemento=None):
    """{id_hex: {tipo: 'Linear'|'Radial', nombre, paradas: [(pos0-100, (r,g,b,a))]}} de las paletas declaradas de la escena (la primera gana)."""
    out = {}
    for p in PE.paletas(escena):
        if p["archivo"] is None or not p["declarada"]:
            continue
        if elemento is not None and p["ambito"] not in ("escena", f"elemento:{elemento}"):
            continue
        for c in P.leer(p["archivo"].read_bytes()).colores():
            if c["tipo"] == "Gradient" and c["id"] not in out:
                out[c["id"]] = {"tipo": c["extra"] or "Linear", "nombre": c["nombre"], "paradas": c["paradas"], "paleta": p["clave"]}
    return out


def decodificar(tvg_path, escena):
    """modelo del conversor oficial + matrices TGCO por id. Devuelve (modelo, {id: matrices})."""
    _MATS.clear()
    G._id_tgco = _id_tgco_mat
    try:
        m = G.decodificar(open(tvg_path, "rb").read())
    finally:
        G._id_tgco = _orig_id_tgco
    el = Path(tvg_path).resolve().parent.name
    esc_el = (Path(escena) / "elements" / el).is_dir()
    m["paleta"].update(PE.paleta_tvg(escena, elemento=el if esc_el else None))
    return m, {k: list(v) for k, v in _MATS.items()}, el if esc_el else None


def _stops(par):
    return "".join(f'<stop offset="{p / 100.0:.4f}" stop-color="#{r:02x}{g:02x}{b:02x}"' + ("" if a >= 255 else f' stop-opacity="{a / 255.0:.4f}"') + "/>"
                   for p, (r, g, b, a) in par)


def convertir(tvg_path, escena, salida, con_gradientes=True):
    """Escribe en `salida` el SVG del dibujo con gradientes. Devuelve {'gradientes': [...], 'avisos': [...]}. Sin gradientes usados: SVG identico al oficial.
    `con_gradientes=False` ni los busca: es la conversion oficial (modelo del .tvg + paleta de la escena -> SVG)."""
    m, mats, el = decodificar(tvg_path, escena)
    grads = paradas_escena(escena, el) if con_gradientes else {}
    usados = [cid for cid in m["paleta_usada"]] if "paleta_usada" in m else None
    # ids de color de los rellenos del dibujo (cualquier arte)
    ids = set()
    for a in m["artes"].values():
        for capa in a["capas"]:
            for tz in capa["trazos"]:
                e = tz["estilo"]
                if e:
                    ids.update(x for x in (e.get("der"), e.get("izq")) if x)
    # iter2 (11-11-2026): antes `... and cid not in m["paleta"]`; en PLANO el id de un Gradient SI esta en la paleta resuelta (como color plano de su
    # primera parada) y nunca se convertia (en vez de la rampa). `grads` solo trae ids de filas Gradient: no choca con solidos.
    gu = [cid for cid in sorted(ids) if cid in grads]
    info, avisos, repl, defs = [], [], {}, []
    usados_rgb = {tuple(c["rgba"][:3]) for c in m["paleta"].values() if isinstance(c, dict) and c.get("rgba")}
    for k, cid in enumerate(gu):
        g = grads[cid]
        ms = mats.get(cid)
        if not ms:
            avisos.append(f"gradiente {cid} ({g['nombre']}) sin matriz TGCO: no se dibuja"); continue
        if len({tuple(round(v, 3) for v in x) for x in ms}) > 1:
            avisos.append(f"gradiente {cid}: {len(ms)} matrices distintas en el dibujo; se usa la primera (el conversor agrupa por color)")
        a, b, c, d, e_, f_ = ms[0]
        ph = (1, 2 + k // 250, 3 + k % 250)
        while ph in usados_rgb:
            ph = (ph[0] + 1, ph[1], ph[2])
        m["paleta"][cid] = {"nombre": g["nombre"], "rgba": (*ph, 255), "paleta": g["paleta"]}
        gid = f"grad_{cid}"
        tm = f'matrix({a:.6f} {b:.6f} {c:.6f} {d:.6f} {e_:.6f} {f_:.6f})'
        if g["tipo"] == "Radial":
            defs.append(f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="0.5" gradientTransform="{tm}">{_stops(g["paradas"])}</radialGradient>')
        else:
            defs.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="1" y2="0" gradientTransform="{tm}">{_stops(g["paradas"])}</linearGradient>')
        repl[f"#{ph[0]:02x}{ph[1]:02x}{ph[2]:02x}"] = f"url(#{gid})"
        info.append({"id": cid, "nombre": g["nombre"], "tipo": g["tipo"], "paradas": g["paradas"], "matriz": list(ms[0])})
    txt = S.a_svg(m)
    for ph, url in repl.items():
        txt = txt.replace(f'fill="{ph}"', f'fill="{url}"')
    if defs:
        txt = txt.replace("<g transform=\"matrix(1 0 0 -1 0 0)\">", "<defs>" + "".join(defs) + "</defs><g transform=\"matrix(1 0 0 -1 0 0)\">", 1)
    Path(salida).write_text(txt, encoding="utf-8")
    return {"gradientes": info, "avisos": avisos}


if __name__ == "__main__":
    r = convertir(sys.argv[1], sys.argv[2], sys.argv[3])
    print(r)
