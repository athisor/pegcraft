"""esperado: calcula <caso>.esperado.json desde la ESPECIFICACION del caso (nunca desde el .xstage ni desde un lector).

Uso:
  python sintetico/esperado.py ESPEC.json [--verificar]
  python sintetico/esperado.py --dir CARPETA [--verificar]

Origen de cada dato: "regla" = calculado por reglas observadas o medidas (R1 yLocal primero, R2 columnas, R3 canales,
R8 apagado propio, R9 padre, R10 preorden, R11 dibujo; grafo P09-P12); "paridad" = convencion de compatibilidad aun no
medida en Harmony (R4 matriz, R5 cadena, R6 READ propio, R7 Z, herencia del apagado, guardas de trayectoria 3D: A3-01). Los valores
medidos en Harmony (A7b-01..A7b-10) van en el campo `medicion`, que este programa NO calcula: lo conserva al regenerar y se incrusta con
`esperado.py ESPEC.json --medicion bloque.json`.

Limites a proposito: la matriz solo se da cuando posicion XY, pivote y offset XY son 0 (la unidad de la traslacion en la matriz
-campos- no esta fijada en una regla); las columnas tipo 3 con manijas Bezier solo se evaluan en cuadros de llave; la trayectoria 3D,
solo en llaves, con un punto o con puntos coincidentes. Lo no calculable sale `null` ("sin referencia").
"""
import argparse
import json
import math
import sys
from pathlib import Path

TRANSPARENTES = {"CurveModule", "OffsetModule", "AutoPatchModule", "GROUP", "MULTIPORT_IN", "MULTIPORT_OUT",
                 "PointConstraint2", "TransformationSwitch"}
DEFECTOS = {"scale/x": 1, "scale/y": 1, "scale/xy": 1, "rotation/anglez": 0, "angle": 0, "skew": 0,
            "pivot/x": 0, "pivot/y": 0, "position/x": 0, "position/y": 0, "position/z": 0,
            "offset/x": 0, "offset/y": 0, "offset/z": 0}


class SinReferencia(Exception):
    pass


def _r(v):
    if v is None:
        return None
    v = round(float(v), 9)
    return 0.0 if v == 0 else v


def cuadros(texto):
    """'1-4,7,9-10' -> [1,2,3,4,7,9,10]"""
    out = []
    for t in str(texto).split(","):
        t = t.strip()
        if "-" in t[1:]:
            a, b = t.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif t:
            out.append(int(t))
    return out


# ------------------------------------------------------------------ modelo del grafo (desde la especificacion)
class Modelo:
    def __init__(self, spec):
        self.spec = spec
        self.nodos = {}          # ruta -> dict(tipo, nombre, grupo, apagado, attrs)
        self.orden = []          # preorden
        self.cables = []         # [grupo, origen, po, destino, pd]
        self.columnas = {c["nombre"]: c for c in spec.get("columnas", [])}
        self.elementos = {e["id"]: e for e in spec.get("elementos", [{"id": 2, "nombre": "Dibujo_A", "carpeta": "Dibujo_A", "dibujos": []}])}
        self._cargar(spec["nodos"], spec.get("enlaces", []), "Top")

    def _cargar(self, nodos, enlaces, grupo):
        for n in nodos:
            ruta = f"{grupo}/{n['nombre']}"
            self.nodos[ruta] = {"tipo": n["tipo"], "nombre": n["nombre"], "grupo": grupo, "apagado": bool(n.get("apagado", False)),
                                "attrs": n.get("attrs", {})}
            self.orden.append(ruta)
            if n["tipo"] == "GROUP":
                self._cargar(n.get("nodos", []), n.get("enlaces", []), ruta)
        for e in enlaces:
            self.cables.append([grupo, f"{grupo}/{e['origen']}", e.get("puerto_origen", 0),
                                f"{grupo}/{e['destino']}", e.get("puerto_destino", 0)])

    # --- fuentes resueltas (P11, P12)
    def literales(self, ruta, puerto):
        n = self.nodos[ruta]
        return [(c[1], c[2]) for c in self.cables if c[0] == n["grupo"] and c[3] == ruta and c[4] == puerto]

    def _salida_de_grupo(self, ruta_grupo):
        for r in self.orden:
            if self.nodos[r]["grupo"] == ruta_grupo and self.nodos[r]["tipo"] == "MULTIPORT_OUT":
                return r
        return None

    def resolver(self, origen, po):
        n = self.nodos[origen]
        if n["tipo"] == "GROUP":
            mpo = self._salida_de_grupo(origen)
            fs = self.fuentes(mpo, po) if mpo else []
            return fs if fs else [(origen, po)]
        if n["tipo"] == "MULTIPORT_IN":
            return self.fuentes(n["grupo"], po)
        return [(origen, po)]

    def fuentes(self, ruta, puerto=0):
        out = []
        for (o, po) in self.literales(ruta, puerto):
            out.extend(self.resolver(o, po))
        return out

    def fuente(self, ruta, puerto=0):
        f = self.fuentes(ruta, puerto)
        return f[0] if f else None

    def padre(self, ruta):
        g = self.nodos[ruta]["grupo"]
        return None if g == "Top" else g[len("Top/"):]

    def apagado_efectivo(self, ruta):
        n = self.nodos[ruta]
        if n["apagado"]:
            return True
        g = n["grupo"]
        while g != "Top":
            if self.nodos[g]["apagado"]:
                return True
            g = self.nodos[g]["grupo"]
        return False

    # --- atributos y columnas
    def _attr(self, ruta, clave):
        a = self.nodos[ruta]["attrs"].get(clave)
        if clave == "angle" and a is None:
            a = self.nodos[ruta]["attrs"].get("rotation/anglez")
        return a

    def valor(self, ruta, clave, f):
        """R1: columna si existe; si no val; si no defecto. -> (valor, origen)"""
        a = self._attr(ruta, clave)
        if isinstance(a, dict) and a.get("col"):
            return self.col3(a["col"], f)
        if isinstance(a, dict):
            a = a.get("val", DEFECTOS.get(clave, 0))
        return (DEFECTOS.get(clave, 0) if a is None else float(a)), "regla"

    def col3(self, nombre, f):
        c = self.columnas[nombre]
        pts = {}
        for p in c["puntos"]:
            y = p["yLocal"] if "yLocal" in p else p["y"]                # R1: yLocal primero
            for x in cuadros(p["x"]):
                pts[x] = (y, bool(p.get("constSeg")), bool(p.get("extra")))
        ks = sorted(pts)
        if f in pts:
            return pts[f][0], "regla"
        if f < ks[0]:
            return pts[ks[0]][0], "regla"
        if f > ks[-1]:
            return pts[ks[-1]][0], "regla"
        l = max(k for k in ks if k < f)
        r = min(k for k in ks if k > f)
        if pts[l][1]:
            return pts[l][0], "regla"                                   # constSeg = escalon (P31)
        if pts[l][2] or pts[r][2]:
            raise SinReferencia(f"manijas Bezier entre {l} y {r}")
        return pts[l][0] + (pts[r][0] - pts[l][0]) * (f - l) / (r - l), "regla"   # manijas 0: la cubica es lineal

    def tray(self, nombre, f):
        """-> ((x,y,z), origen)"""
        c = self.columnas[nombre]
        pts = sorted(c["puntos"], key=lambda p: p["t"])
        if len(pts) == 1:
            return tuple(pts[0]["v"]), "paridad"                         # guarda: un punto = constante
        for p in pts:
            if p["t"] == f:
                return tuple(p["v"]), ("paridad" if any(pts[i]["v"] == pts[i + 1]["v"] for i in range(len(pts) - 1)) else "regla")
        if f < pts[0]["t"]:
            return tuple(pts[0]["v"]), "paridad"
        if f > pts[-1]["t"]:
            return tuple(pts[-1]["v"]), "paridad"
        for a, b in zip(pts, pts[1:]):
            if a["t"] < f < b["t"] and a["v"] == b["v"]:
                return tuple(a["v"]), "paridad"                          # cuerda nula: constante
        raise SinReferencia(f"trayectoria entre llaves en {f}")

    def dibujo(self, ruta, f):
        a = self._attr(ruta, "drawing/element")
        col = a.get("col") if isinstance(a, dict) else None
        c = self.columnas.get(col) if col else None
        if not c:
            return None
        for s in c.get("secuencias", []):
            if f in cuadros(s["cuadros"]):
                e = self.elementos[c["elemento"]]
                return {"elemento_id": c["elemento"], "elemento": e["nombre"], "carpeta": e.get("carpeta", e["nombre"]),
                        "dibujo": s["dibujo"], "ruta_relativa": f"elements/{e.get('carpeta', e['nombre'])}/{e.get('carpeta', e['nombre'])}-{s['dibujo']}.tvg"}
        return None

    def posicion(self, ruta, f):
        a = self._attr(ruta, "position/attr3dpath")
        if isinstance(a, dict) and a.get("col"):
            (x, y, z), o = self.tray(a["col"], f)
            return (x, y, z), o
        o = "regla"
        v = []
        for k in ("position/x", "position/y", "position/z"):
            val, oo = self.valor(ruta, k, f)
            v.append(val)
            o = "paridad" if oo == "paridad" else o
        return tuple(v), o

    def canales(self, ruta, f):
        pos, o1 = self.posicion(ruta, f)
        sx, o2 = self.valor(ruta, "scale/x", f)
        sy, o3 = self.valor(ruta, "scale/y", f)
        rot, o4 = self.valor(ruta, "rotation/anglez", f)
        sk, o5 = self.valor(ruta, "skew", f)
        px, _ = self.valor(ruta, "pivot/x", f)
        py, _ = self.valor(ruta, "pivot/y", f)
        origen = "paridad" if "paridad" in (o1, o2, o3, o4, o5) else "regla"
        pre = "offset" if self.nodos[ruta]["tipo"] == "READ" else "posicion"
        c = {"escala.x": sx, "escala.y": sy, "rotacion": rot, "sesgo": sk, "pivote.x": px, "pivote.y": py}
        if pre == "posicion":
            c.update({"posicion.x": pos[0], "posicion.y": pos[1], "posicion.z": pos[2]})
        else:
            ox, _ = self.valor(ruta, "offset/x", f)
            oy, _ = self.valor(ruta, "offset/y", f)
            oz, _ = self.valor(ruta, "offset/z", f)
            c.update({"offset.x": ox, "offset.y": oy, "offset.z": oz})
        return {k: _r(v) for k, v in c.items()}, origen

    # --- matrices (R4-R6; sesgo ignorado)
    def local(self, ruta, f):
        c, _ = self.canales(ruta, f)
        if c.get("posicion.x", 0) or c.get("posicion.y", 0) or c.get("offset.x", 0) or c.get("offset.y", 0) \
                or c["pivote.x"] or c["pivote.y"]:
            raise SinReferencia("traslacion/pivote distintos de 0")
        t = math.radians(c["rotacion"])
        co, si = math.cos(t), math.sin(t)
        return [[co * c["escala.x"], -si * c["escala.y"], 0.0], [si * c["escala.x"], co * c["escala.y"], 0.0]]

    def es_identidad_propia(self, ruta, f):
        c, _ = self.canales(ruta, f)
        return (c["escala.x"] == 1 and c["escala.y"] == 1 and c["rotacion"] == 0 and c["offset.x"] == 0 and c["offset.y"] == 0
                and c["pivote.x"] == 0 and c["pivote.y"] == 0)

    def cadena(self, ruta, f):
        """-> (lista de transformadores del mas cercano al mas lejano, cortada)"""
        lista, cortada = [], False
        n = self.nodos[ruta]
        if n["tipo"] == "READ" and not self.es_identidad_propia(ruta, f):
            lista.append(ruta)
        elif n["tipo"] == "PEG":
            lista.append(ruta)
        act = self.fuente(ruta, 0)
        while act:
            r = act[0]
            t = self.nodos[r]["tipo"]
            if t == "PEG":
                lista.append(r)
                act = self.fuente(r, 0)
            elif t in TRANSPARENTES:
                act = self.fuente(r, 0)
            else:
                cortada = True
                break
        return lista, cortada


def _mul(a, b):
    return [[a[0][0] * b[0][0] + a[0][1] * b[1][0], a[0][0] * b[0][1] + a[0][1] * b[1][1], a[0][0] * b[0][2] + a[0][1] * b[1][2] + a[0][2]],
            [a[1][0] * b[0][0] + a[1][1] * b[1][0], a[1][0] * b[0][1] + a[1][1] * b[1][1], a[1][0] * b[0][2] + a[1][1] * b[1][2] + a[1][2]]]


def _evaluar_nodo(m, ruta, f):
    n = m.nodos[ruta]
    cadena, cortada = m.cadena(ruta, f)
    e = {"tipo": n["tipo"], "padre": m.padre(ruta), "apagado": n["apagado"], "apagado_efectivo": m.apagado_efectivo(ruta),
         "cadena": cadena, "cortada": cortada}
    org = {"apagado": "regla", "apagado_efectivo": "paridad", "cadena": "paridad"}
    try:
        e["canales"], org["canales"] = m.canales(ruta, f)
    except SinReferencia:
        e["canales"], org["canales"] = None, "regla"
    if n["tipo"] == "READ":
        d = m.dibujo(ruta, f)
        e["dibujo"] = d
        org["dibujo"] = "regla"
    # Z (R7): suma de posicion.z de los PEG de la cadena (apagados incluidos) + offset.z del propio READ
    try:
        z = 0.0
        for r in cadena:
            if m.nodos[r]["tipo"] == "PEG":
                z += m.posicion(r, f)[0][2]
        if n["tipo"] == "READ":
            z += m.valor(ruta, "offset/z", f)[0]
        e["z"] = 0.0 if cortada else _r(z)
    except SinReferencia:
        e["z"] = None
    org["z"] = "paridad"
    try:
        if cortada:
            e["matriz"] = None
        else:
            mat = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
            for r in reversed(cadena):                       # del mas lejano al mas cercano: padre * hijo * ... * propio
                mat = _mul(mat, m.local(r, f))
            e["matriz"] = [[_r(v) for v in fila] for fila in mat]
    except SinReferencia:
        e["matriz"] = None
    org["matriz"] = "paridad"
    e["origen"] = org
    return e


def calcular(spec):
    m = Modelo(spec)
    nodos = [{"ruta": r, "tipo": m.nodos[r]["tipo"], "nombre": m.nodos[r]["nombre"], "padre": m.padre(r),
              "apagado": m.nodos[r]["apagado"], "apagado_efectivo": m.apagado_efectivo(r)} for r in m.orden]
    fuentes, puertos = {}, {}
    for r in m.orden:
        ps = sorted({c[4] for c in m.cables if c[3] == r})
        if ps:
            fuentes[r] = {str(p): [[o, po] for o, po in m.fuentes(r, p)] for p in ps}
        if m.nodos[r]["tipo"] == "COMPOSITE" and ps:
            puertos[r] = ps
    evaluacion = {}
    for f in spec.get("evaluar", [1]):
        evaluacion[str(f)] = {r: _evaluar_nodo(m, r, f) for r in m.orden if m.nodos[r]["tipo"] in ("READ", "PEG")}
    tiene_paridad = any(v == "paridad" for fr in evaluacion.values() for e in fr.values() for v in e["origen"].values())
    atr = {}
    for t in spec.get("atributos_texto", []):
        ruta = f"Top/{t['nodo']}"
        a = m.nodos[ruta]["attrs"]
        v = a
        for k in ["/".join(t["ruta"])]:
            v = v[k]
        atr.setdefault(ruta, {})["/".join(t["ruta"])] = v["val"] if isinstance(v, dict) else v
    return {
        "caso": spec["nombre"], "version_formato": 1,
        "descripcion": spec.get("descripcion", ""),
        "origen": "paridad" if tiene_paridad else "regla",
        "origen_por_bloque": {"grafo": "regla", "atributos": "regla", "evaluacion": "paridad" if tiene_paridad else "regla"},
        "medicion": {"estado": "pendiente", "nota": "los valores medidos en Harmony llegan en la ola 2"},
        "escena": {"fotogramas": int(spec.get("fotogramas", 24)), "fps": spec.get("fps", 24)},
        "nodos": nodos,
        "cables_literales": m.cables,
        "fuentes": fuentes,
        "puertos_composite": puertos,
        "atributos": atr,
        "evaluacion": evaluacion,
    }


def a_texto(esp):
    return json.dumps(esp, indent=1, ensure_ascii=True, sort_keys=False) + "\n"


def _medicion_previa(destino):
    """Bloque `medicion` ya incrustado en el esperado (estado "medido"), o None. Regenerar no lo pierde: el origen "harmony" no se calcula."""
    try:
        previo = json.loads(Path(destino).read_text(encoding="utf-8")).get("medicion")
    except (OSError, ValueError):
        return None
    return previo if isinstance(previo, dict) and previo.get("estado") == "medido" else None


def con_medicion(esp, medicion):
    esp["medicion"] = medicion
    esp["origen_por_bloque"]["medicion"] = medicion.get("origen", "harmony")
    return esp


def procesar(ruta_spec, verificar=False, medicion=None):
    """`medicion`: dict (bloque medido en Harmony) que se incrusta; si no se da, se conserva el que ya traiga el esperado."""
    ruta_spec = Path(ruta_spec)
    spec = json.loads(ruta_spec.read_text(encoding="utf-8"))
    destino = ruta_spec.with_name(ruta_spec.stem + ".esperado.json")
    esp = calcular(spec)
    med = medicion if medicion is not None else _medicion_previa(destino)
    if med is not None:
        con_medicion(esp, med)
    texto = a_texto(esp)
    if verificar:
        igual = destino.exists() and destino.read_text(encoding="utf-8") == texto
        print(("OK    " if igual else "DIFIERE ") + destino.name)
        return igual
    destino.write_text(texto, encoding="utf-8", newline="\n")
    print(f"escrito {destino.name}")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("espec", nargs="?")
    ap.add_argument("--dir")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--medicion", help="JSON con el bloque `medicion` (origen harmony) que se incrusta en el esperado de ESPEC.json")
    a = ap.parse_args(argv)
    if a.medicion:
        if not a.espec:
            ap.error("--medicion necesita ESPEC.json")
        return 0 if procesar(a.espec, a.verificar, json.loads(Path(a.medicion).read_text(encoding="utf-8"))) else 1
    if a.dir:
        specs = sorted(p for p in Path(a.dir).glob("*.json") if not p.name.endswith(".esperado.json"))
    elif a.espec:
        specs = [Path(a.espec)]
    else:
        ap.error("falta ESPEC.json o --dir")
    return 0 if all([procesar(p, a.verificar) for p in specs]) else 1


if __name__ == "__main__":
    sys.exit(main())
