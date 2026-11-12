"""Descomposicion afin <-> (posicion, rotacion, escala, sesgo) y utilidades de series con Hold."""
import math

EXT_CANALES = ("ShearX", "Opacity", "Order", "Z")   # atributos que el formato externo (anim.rs::Attribute) no tiene hoy


def descomponer(m):
    """[[a,b,tx],[c,d,ty]] -> dict(PositionX,PositionY,Rotation,ScaleX,ScaleY,ShearX). M_lineal = R(th) * [[sx, h],[0, sy]],
    equivalente a la convencion R*Shear*Scale con shear_x = h/sy (Transform2D, pivote 0). sy<0 = espejo."""
    (a, b, tx), (c, d, ty) = m
    sx = math.hypot(a, c)
    if sx == 0.0:
        th, h, sy = 0.0, b, d
    else:
        th = math.atan2(c, a)
        cs, sn = math.cos(th), math.sin(th)
        h = cs * b + sn * d
        sy = -sn * b + cs * d
    shx = h / sy if abs(sy) > 1e-12 else 0.0
    return {"PositionX": tx, "PositionY": ty, "Rotation": th, "ScaleX": sx, "ScaleY": sy, "ShearX": shx}


def componer(v):
    th, sx, sy = v["Rotation"], v["ScaleX"], v["ScaleY"]
    h = v.get("ShearX", 0.0) * sy
    cs, sn = math.cos(th), math.sin(th)
    return [[cs * sx, cs * h - sn * sy, v["PositionX"]], [sn * sx, sn * h + cs * sy, v["PositionY"]]]


def claves_hold(frames, valores):
    """Solo donde el valor cambia (Hold: lo anterior sigue valiendo). frames ordenados y consecutivos o con huecos."""
    ks, prev = [], object()
    for f, v in zip(frames, valores):
        if v != prev:
            ks.append({"time": float(f), "value": v, "interpolation": "Hold"})
            prev = v
    return {"keyframes": ks}


def valor_en(curva, f):
    """Valor de una curva Hold en el frame f (ultima clave con time <= f)."""
    v = None
    for k in curva["keyframes"]:
        if k["time"] <= f:
            v = k["value"]
        else:
            break
    return v


def runs(frames, valores):
    """[(inicio, largo, valor)] de valores iguales en frames consecutivos."""
    out = []
    for f, v in zip(frames, valores):
        if out and out[-1][2] == v and out[-1][0] + out[-1][1] == f:
            out[-1][1] += 1
        else:
            out.append([f, 1, v])
    return out


def desplegar(rs, f):
    for ini, n, v in rs:
        if ini <= f < ini + n:
            return v
    return None
