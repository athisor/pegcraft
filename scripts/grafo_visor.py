"""grafo_visor.py: exporta el grafo de nodos de un .xstage a grafo.json para la vista de nodos de pegcraft-viewer.
SOLO LECTURA sobre el .xstage (lector del repo: sightread.lector). Escribe solo el JSON de salida.
Uso: python -I scripts\\grafo_visor.py <escena.xstage> <salida grafo.json>
Formato: {escena, raiz, grupos:{ruta_grupo:{nodos:[{id,nombre,tipo,apagado,x,y,entradas:n,salidas:n}], cables:[{de,pd,a,pa}]}}}
 - cables LITERALES del archivo por grupo (puerto de salida pd -> puerto de entrada pa); los grupos se entran con doble clic en el visor.
 - x,y: layout por capas calculado aqui (rango por camino mas largo, orden por baricentro), en unidades de rejilla; el flujo va de arriba a abajo.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # raiz del repo (con -I el directorio del script no entra solo)
from sightread.lector import abrir  # noqa: E402
from sightread.lector.tipos import RAIZ  # noqa: E402


def layout(ids, cables):
    """Capas por camino mas largo desde fuentes (los ciclos se ignoran con DFS) + baricentro. Devuelve {id: (col, fila)}."""
    suc = defaultdict(list)
    pred = defaultdict(list)
    for c in cables:
        if c["de"] != c["a"]:
            suc[c["de"]].append(c["a"])
            pred[c["a"]].append(c["de"])
    rank = {}
    estado = {}

    def r(n):
        if n in rank:
            return rank[n]
        if estado.get(n) == 1:
            return 0  # ciclo
        estado[n] = 1
        v = 0
        for p in pred[n]:
            v = max(v, r(p) + 1)
        estado[n] = 2
        rank[n] = v
        return v

    sys.setrecursionlimit(10000)
    for n in ids:
        r(n)
    capas = defaultdict(list)
    for n in ids:
        capas[rank[n]].append(n)
    pos_en_capa = {}
    for k in sorted(capas):
        capas[k].sort()
        for i, n in enumerate(capas[k]):
            pos_en_capa[n] = float(i)
    for _ in range(6):  # barridos de baricentro abajo y arriba
        for k in sorted(capas):
            if k == min(capas):
                continue
            capas[k].sort(key=lambda n: (sum(pos_en_capa[p] for p in pred[n]) / len(pred[n])) if pred[n] else pos_en_capa[n])
            for i, n in enumerate(capas[k]):
                pos_en_capa[n] = float(i)
        for k in sorted(capas, reverse=True):
            capas[k].sort(key=lambda n: (sum(pos_en_capa[s] for s in suc[n]) / len(suc[n])) if suc[n] else pos_en_capa[n])
            for i, n in enumerate(capas[k]):
                pos_en_capa[n] = float(i)
    return {n: (pos_en_capa[n], float(rank[n])) for n in ids}


def main():
    xs, out = Path(sys.argv[1]), Path(sys.argv[2])
    g = abrir(xs)
    por_grupo = defaultdict(lambda: {"nodos": [], "cables": []})
    nin, nout = defaultdict(int), defaultdict(int)
    for e in g.cables:
        nout[e.origen] = max(nout[e.origen], e.puerto_origen + 1)
        nin[e.destino] = max(nin[e.destino], e.puerto_destino + 1)
    for p, n in g.nodos.items():
        # px,py = posicion que Harmony guarda en el .xstage (coordenadas de la vista nodal; y crece hacia abajo)
        por_grupo[n.grupo]["nodos"].append({"id": p, "nombre": n.nombre, "tipo": n.tipo, "apagado": bool(n.apagado), "entradas": nin[p], "salidas": nout[p],
                                            "px": n.pos[0], "py": n.pos[1]})
    for bd in g.backdrops:
        por_grupo[bd.grupo].setdefault("backdrops", []).append({"titulo": bd.titulo, "color": bd.color, "rect": list(bd.rect), "nodos": list(bd.nodos)})
    for e in g.cables:
        por_grupo[e.grupo]["cables"].append({"de": e.origen, "pd": e.puerto_origen, "a": e.destino, "pa": e.puerto_destino})
    for gr, d in por_grupo.items():
        pos = layout([n["id"] for n in d["nodos"]], d["cables"])
        for n in d["nodos"]:
            n["x"], n["y"] = pos[n["id"]]
    salida = {"escena": str(xs), "raiz": RAIZ, "total_nodos": len(g.nodos), "total_cables": len(g.cables), "grupos": por_grupo}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(salida, ensure_ascii=False), encoding="utf-8")
    print(f"{len(g.nodos)} nodos, {len(g.cables)} cables, {len(por_grupo)} grupos -> {out}")
    for gr, d in sorted(por_grupo.items(), key=lambda kv: -len(kv[1]["nodos"]))[:8]:
        print(f"  {gr}: {len(d['nodos'])} nodos, {len(d['cables'])} cables")


if __name__ == "__main__":
    main()
