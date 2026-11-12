"""CLI unica: python -m pegcraft <subcomando> ...   (ver (doc interna omitida)

  hornear         un fotograma -> escena.json + dibujos\\*.svg   (def.: conectores, matriz causal y deformadores = lo mejor validado)
  render          escena.json -> PNG con el crate pegcraft-render
  medir           px_ok / px_ok_personajes / (con --solo-ref --solo-mio) metrica de un grupo solo
  keyframes       fotogramas donde cambian los dibujos expuestos
  censo           deformadores (Offset/Curve) activos por READ
  diag-solos      pieza por pieza contra los `solo` de Harmony (caja, IoU, ECC, contorno)
  lamina          completa | tira | zonas
"""
import sys, json, argparse
from pathlib import Path

sys.dont_write_bytecode = True


def _si(v):
    return v == "si"


def _zonas(lst):
    z = {}
    for s in lst or []:
        n, v = s.split("=", 1); a = v.split(",")
        z[n] = (*(int(x) for x in a[:4]), float(a[4]) if len(a) > 4 else 2.0)
    return z


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pegcraft", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    h = sp.add_parser("hornear", help="hornear un fotograma")
    h.add_argument("xstage"); h.add_argument("fotograma", type=int); h.add_argument("salida")
    h.add_argument("--nombre", default="escena.json")
    h.add_argument("--excluir", default=None, help="regex de rutas de nodo que no se dibujan (por omision PEGCRAFT_EXCLUIR; vacia = ninguna)")
    h.add_argument("--grupo", default=None, help="solo piezas cuya ruta empieza asi (p. ej. Top/Personaje/)")
    h.add_argument("--conectores", choices=["si", "no"], default="si")
    h.add_argument("--matriz-causal", dest="causal", choices=["si", "no"], default="si", help="no = matrices de Evaluador.nodos (con --desfase si se quiere el estado de 0,908)")
    h.add_argument("--deformadores", choices=["si", "no"], default="si")
    h.add_argument("--exp", default="", help="experimentos de conectores: sin_capas,sin_visibility,sin_cutter,sin_selector,sin_autopatch,apagar=A+B")
    h.add_argument("--z", choices=["global", "bitmap"], default="global")
    h.add_argument("--apilado", choices=["puertos", "lista"], default="puertos", help="solo con --conectores no")
    h.add_argument("--recortadas", choices=["omitir", "incluir"], default="omitir", help="solo con --conectores no")
    h.add_argument("--camara", choices=["iso", "anisotropa", "supuesta", "metricas"], default=None, help="def.: metricas con matriz causal, iso sin ella")
    h.add_argument("--desfase", default=None, help="DIAGNOSTICO: dx_sin_espejo,dx_espejo en campos para las piezas de --desfase-grupo")
    h.add_argument("--desfase-grupo", default="Top/Personaje/")
    h.add_argument("--carpeta", choices=["real", "elemento"], default="real")
    h.add_argument("--gradientes", choices=["si", "no"], default="si", help="def. si (validado 11-11-2026). rellenos Gradient (Linear/Radial) como SVG <linearGradient>; el crate los dibuja (doc interna omitida)")
    h.add_argument("--opacidad", choices=["leer", "ignorar"], default="leer")
    h.add_argument("--glow-suma", choices=["si", "no"], default="si", help="def. si (validado 11-11-2026, PLANO +0,28..+0,39): marca mezcla=suma en las piezas cuya rama pasa por un GLOW aditivo; el crate las suma por canal. Sin GLOW no cambia nada")

    r = sp.add_parser("render", help="escena.json -> PNG")
    r.add_argument("escena"); r.add_argument("--out", required=True)
    r.add_argument("--bg", choices=["gris", "transparente"], default="gris")
    r.add_argument("extra", nargs="*", help="flags del crate tras --, p. ej. -- --sin-recorte --div 150")

    m = sp.add_parser("medir", help="px_ok contra una referencia de Harmony")
    m.add_argument("ref"); m.add_argument("mio")
    m.add_argument("--sil", default=None, help="render de Harmony solo de los personajes (define px_ok_personajes)")
    m.add_argument("--solo-ref", default=None, help="con --solo-mio: metrica de un grupo renderizado solo (px_ok en la union e IoU)")
    m.add_argument("--solo-mio", default=None); m.add_argument("--json", default=None)

    k = sp.add_parser("keyframes", help="fotogramas donde cambian los dibujos")
    k.add_argument("xstage"); k.add_argument("--desde", type=int, default=1); k.add_argument("--hasta", type=int, default=None)
    k.add_argument("--patron", default=None, help="regex sobre la ruta del READ")

    c = sp.add_parser("censo", help="deformadores activos por READ")
    c.add_argument("xstage"); c.add_argument("fotograma", type=int); c.add_argument("--patron", default="."); c.add_argument("--json", default=None)

    d = sp.add_parser("diag-solos", help="pieza por pieza contra los solo de Harmony")
    d.add_argument("escena_json"); d.add_argument("carpeta_solo"); d.add_argument("salida")
    d.add_argument("pares", nargs="+", help="estado=Top/Grupo/READ[+otro]")
    d.add_argument("--fotograma", type=int, default=22); d.add_argument("--capas", default=None, help="p. ej. colour,line")
    d.add_argument("--sin-recorte", action="store_true")

    l = sp.add_parser("lamina", help="laminas de comparacion")
    l.add_argument("tipo", choices=["completa", "tira", "zonas"])
    l.add_argument("salida"); l.add_argument("imagenes", nargs="+", help="completa: ref mio | tira: etq=ruta... | zonas: ref etq=mio...")
    l.add_argument("--caja", default="auto"); l.add_argument("--escala", type=float, default=1.0)
    l.add_argument("--diff", default=None, help="i,j (tira)"); l.add_argument("--zona", action="append", help="nombre=x0,y0,x1,y1[,escala] (zonas)")




    co = sp.add_parser("compilar", help="escena -> plano nativo (tensores + sidecar x-harmony + almacen de activos; (doc interna omitida)")
    co.add_argument("xstage"); co.add_argument("--frames", required=True, help="A:B | n,m,k | todos"); co.add_argument("--salida", required=True)
    co.add_argument("--conservar-horneado", action="store_true")
    co.add_argument("--sin-residual", action="store_true", help="no escribir plano/harmony/ (arbol de origen exacto)")
    co.add_argument("--depurar-personal", action="store_true", help="SOLO si el autor lo pide: reemplaza username/realUsername y rutas absolutas en el arbol (rompe la identidad byte a byte)")
    vp = sp.add_parser("vuelta-plano", help="plano -> .xstage/.aux originales desde harmony/arbol.json.gz (byte a byte) [--editar REF=VALOR]")
    vp.add_argument("plano"); vp.add_argument("--salida", required=True)
    vp.add_argument("--editar", action="append", default=None, metavar="REF=VALOR", help="REF = id de harmony/mapa_ids.json (+/subruta y @atributo) o ruta del arbol; exige que cambie solo esa linea")
    vp.add_argument("--origen", default=None, help="carpeta del proyecto original: verifica el sha256 de las referencias (.tvg...)")
    rp = sp.add_parser("render-plano", help="plano -> PNG de un fotograma (sin .xstage ni .tvg)")
    rp.add_argument("plano"); rp.add_argument("--frame", type=int, required=True); rp.add_argument("--out", required=True)
    rp.add_argument("--salida-json", default=None); rp.add_argument("--f32", action="store_true", help="usar solo el tensor baked F32 (spec D-Tab)")
    rp.add_argument("--flags", nargs="*", default=None, help="flags del crate (def.: --aa-gauss 0.45 --ss 2 --opacidad-grupo)")




    a = ap.parse_args(argv)
    if a.cmd in ("compilar", "render-plano", "vuelta-plano"):
        from .compilar import cli as KC
        return KC.main(a)
    if a.cmd == "hornear":
        from .bake.hornear import hornear
        _, res = hornear(a.xstage, a.fotograma, a.salida, nombre=a.nombre, excluir=a.excluir, grupo=a.grupo, conectores=_si(a.conectores), exp=a.exp,
                         z=a.z, apilado_modo=a.apilado, recortadas=a.recortadas, camara=a.camara, desfase=a.desfase, desfase_grupo=a.desfase_grupo,
                         carpeta=a.carpeta, opacidad=a.opacidad, matriz_causal=_si(a.causal), deformadores=_si(a.deformadores), gradientes=_si(a.gradientes), glow_suma=_si(a.glow_suma))
        print(json.dumps(res, ensure_ascii=False))
    elif a.cmd == "render":
        from .medir.render import renderizar
        print(renderizar(a.escena, a.out, a.bg, a.extra))
    elif a.cmd == "medir":
        from .medir import metricas as M
        if a.solo_ref:
            print(json.dumps(M.metrica_grupo(a.solo_ref, a.solo_mio)))
        else:
            M.main(a.ref, a.mio, a.sil, a.json)
    elif a.cmd == "keyframes":
        from .keyframes import keyframes
        print(keyframes(a.xstage, a.desde, a.hasta, a.patron))
    elif a.cmd == "censo":
        from .bake import censo
        censo.main(a.xstage, a.fotograma, a.patron, a.json)
    elif a.cmd == "diag-solos":
        from .diag.solos import solos
        solos(a.escena_json, a.carpeta_solo, a.salida, a.pares, a.fotograma, a.capas.split(",") if a.capas else None, a.sin_recorte)
    elif a.cmd == "lamina":
        from .diag import laminas as L
        if a.tipo == "completa":
            L.completa(a.imagenes[0], a.imagenes[1], a.salida)
        elif a.tipo == "tira":
            print(L.tira(a.salida, a.caja, a.escala, a.imagenes, [int(x) for x in a.diff.split(",")] if a.diff else None))
        else:
            print(json.dumps(L.zonas(a.imagenes[0], a.salida, a.imagenes[1:], _zonas(a.zona)), indent=1))


if __name__ == "__main__":
    sys.exit(main())
