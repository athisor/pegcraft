"""Conversion .tvg -> SVG con la paleta de la escena y los rellenos GRADIENTE (Linear/Radial).

Usa los lectores del repositorio: `pegcraft.tvg` (dibujo) y `pegcraft.plt` (paletas). Que se sabe (MEDIDO en una escena de planos con degradados):
- El color de un relleno es un id de 8 B; en la paleta .plt (declarada) ese id es una fila `Gradient <nombre> 0x<id> Linear|Radial` + paradas
  (posicion 0-100, R G B A).
- La GEOMETRIA no esta en la paleta: esta en el registro TGCO del trazo (`modelo["tgco"]`, CENSO-12): 6 f64 = matriz afin 2x3 (a b c d e f,
  estilo SVG matrix) del espacio del gradiente al espacio del dibujo (unidades de dibujo, y arriba). En espacio de gradiente el eje Linear es u en [0,1]
  (parada p% = u p/100) y v en [-0,5, 0,5] perpendicular.
- Radial: SUPUESTO (sin ejemplo medido): circulo de centro (0,0), radio 0,5 en espacio de gradiente.

Salida: SVG con <defs><linearGradient|radialGradient gradientUnits="userSpaceOnUse" gradientTransform="matrix(..)"> y fill="url(#...)".
Los degradados y texturas llegan del lector con rgba=None y `a_svg` no los dibuja; aqui se les da un color marcador unico que luego se sustituye por el url().
"""
import sys
from pathlib import Path

from .. import plt as _plt
from .. import rutas as _rutas
from ..tvg import a_svg, decodificar as _decodificar


def paradas_escena(escena, elemento=None):
    """{id_hex: {tipo: 'Linear'|'Radial', nombre, paradas: [(pos0-100, (r,g,b,a))]}} de las paletas declaradas de la escena (la primera gana)."""
    out = {}
    for p in _plt.paletas(escena):
        if p["archivo"] is None or not p["declarada"]:
            continue
        if elemento is not None and p["ambito"] not in ("escena", f"elemento:{elemento}"):
            continue
        try:
            pal = _plt.leer(Path(p["archivo"]).read_bytes())
        except (OSError, _plt.PaletaIlegible):
            continue
        for c in pal.colores():
            if c["tipo"] == "Gradient" and c["id"] not in out:
                out[c["id"]] = {"tipo": c["extra"] or "Linear", "nombre": c["nombre"], "paradas": c["paradas"], "paleta": p["clave"]}
    return out


def _elemento(tvg_path, escena):
    """Nombre real de la carpeta del elemento (`elements/<el>`) si existe en la escena (tolerando mayusculas), si no None."""
    carpeta = Path(tvg_path).resolve().parent.name
    d = _rutas.buscar(escena, "elements", carpeta)
    return d.name if d is not None and d.is_dir() else None


def decodificar(tvg_path, escena):
    """modelo de `pegcraft.tvg` con la paleta de la escena encima de la copia local del dibujo. Devuelve (modelo, {id: matrices}, elemento)."""
    m = _decodificar(Path(tvg_path).read_bytes())
    el = _elemento(tvg_path, escena)
    m["paleta"].update(_plt.paleta_tvg(escena, elemento=el))     # PLT-v0 §7: la paleta de la escena gana sobre la TPAL
    return m, {k: list(v) for k, v in m["tgco"].items()}, el


def _stops(par):
    return "".join(f'<stop offset="{p / 100.0:.4f}" stop-color="#{r:02x}{g:02x}{b:02x}"' + ("" if a >= 255 else f' stop-opacity="{a / 255.0:.4f}"') + "/>"
                   for p, (r, g, b, a) in par)


def convertir(tvg_path, escena, salida, con_gradientes=True):
    """Escribe en `salida` el SVG del dibujo con gradientes. Devuelve {'gradientes': [...], 'avisos': [...]}. Sin gradientes usados: SVG sin <defs>.
    `con_gradientes=False` ni los busca: solo modelo del .tvg + paleta de la escena -> SVG. `TvgIlegible` sube tal cual."""
    m, mats, el = decodificar(tvg_path, escena)
    grads = paradas_escena(escena, el) if con_gradientes else {}
    # ids de color de los rellenos del dibujo (cualquier arte)
    ids = set()
    for a in m["artes"].values():
        for capa in a["capas"]:
            for tz in capa["trazos"]:
                e = tz["estilo"]
                if e:
                    ids.update(x for x in (e.get("der"), e.get("izq")) if x)
    # `grads` solo trae ids de filas Gradient: no choca con solidos.
    gu = [cid for cid in sorted(ids) if cid in grads]
    info, avisos, repl, defs = [], [], {}, []
    usados_rgb = {tuple(c["rgba"][:3]) for c in m["paleta"].values() if isinstance(c, dict) and c.get("rgba")}
    for k, cid in enumerate(gu):
        g = grads[cid]
        ms = mats.get(cid)
        if not ms:
            avisos.append(f"gradiente {cid} ({g['nombre']}) sin matriz TGCO: no se dibuja"); continue
        if len({tuple(round(v, 3) for v in x) for x in ms}) > 1:
            avisos.append(f"gradiente {cid}: {len(ms)} matrices distintas en el dibujo; se usa la primera (se agrupa por color)")
        a, b, c, d, e_, f_ = ms[0]
        ph = (1, 2 + k // 250, 3 + k % 250)
        while ph in usados_rgb:
            ph = (ph[0] + 1, ph[1], ph[2])
        usados_rgb.add(ph)
        m["paleta"][cid] = {"nombre": g["nombre"], "rgba": (*ph, 255), "paleta": g["paleta"], "tipo": "solido"}
        gid = f"grad_{cid}"
        tm = f'matrix({a:.6f} {b:.6f} {c:.6f} {d:.6f} {e_:.6f} {f_:.6f})'
        if g["tipo"] == "Radial":
            defs.append(f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="0.5" gradientTransform="{tm}">{_stops(g["paradas"])}</radialGradient>')
        else:
            defs.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="1" y2="0" gradientTransform="{tm}">{_stops(g["paradas"])}</linearGradient>')
        repl[f"#{ph[0]:02x}{ph[1]:02x}{ph[2]:02x}"] = f"url(#{gid})"
        info.append({"id": cid, "nombre": g["nombre"], "tipo": g["tipo"], "paradas": g["paradas"], "matriz": list(ms[0])})
    txt = a_svg(m)
    for ph, url in repl.items():
        txt = txt.replace(f'fill="{ph}"', f'fill="{url}"')
    if defs:
        txt = txt.replace("<g transform=\"matrix(1 0 0 -1 0 0)\">", "<defs>" + "".join(defs) + "</defs><g transform=\"matrix(1 0 0 -1 0 0)\">", 1)
    Path(salida).write_text(txt, encoding="utf-8")
    return {"gradientes": info, "avisos": avisos}


if __name__ == "__main__":
    print(convertir(sys.argv[1], sys.argv[2], sys.argv[3]))
