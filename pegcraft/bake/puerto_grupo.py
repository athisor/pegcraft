"""puerto_grupo.py: el puerto de salida de un grupo se busca por TIPO (MULTIPORT_OUT), no por el nombre fijo `<grupo>/Multi-Port-Out`.

lector_xstage (upstream: NO se modifica) resuelve `SceneGraph._cable_origen` con `f"{grupo}/Multi-Port-Out"`. En EscenaB ese nodo se llama
`no-name_1`, `Output`, etc.; sin el parche el apilado trata el GRUPO como transparente y el rig no se dibuja.
En el estudio el nombre coincide siempre: el parche no cambia nada ahi.
Se aplica en memoria (como `_leer_ylocal` de hornear.py). PEGCRAFT_PUERTO_GRUPO=no lo apaga (comportamiento upstream).
"""
import os, sys
sys.dont_write_bytecode = True

AVISOS = {}   # grupo -> nodo MULTIPORT_OUT elegido por tipo (solo cuando el nombre canonico no existia); hornear() lo reinicia en cada cuadro


def reiniciar():
    AVISOS.clear()


def resumen():
    """Lista de avisos para escena.json (una linea) y stderr (una linea); [] si todos los grupos traian 'Multi-Port-Out'."""
    if not AVISOS:
        return []
    ej = ", ".join(f"{g.split('/')[-1]}->{n.split('/')[-1]}" for g, n in list(AVISOS.items())[:3])
    msg = f"puerto_grupo: {len(AVISOS)} grupo(s) sin 'Multi-Port-Out'; salida resuelta por tipo MULTIPORT_OUT ({ej}{', ...' if len(AVISOS) > 3 else ''})"
    print("AVISO " + msg, file=sys.stderr)
    return [msg]


def _mpo_por_tipo(sg, grafo, grupo):
    """Nodo MULTIPORT_OUT del `grupo`: el de nombre canonico si existe; si no, el primero (orden de ruta) cuyo `group` es el grupo."""
    canon = f"{grupo}/Multi-Port-Out"
    if canon in grafo.nodes:
        return canon
    memo = grafo.__dict__.setdefault("_pegcraft_mpo", {})
    if grupo not in memo:
        hijos = sorted(p for p, n in grafo.nodes.items() if n.type == sg.MULTIPORT_OUT and n.group == grupo)
        memo[grupo] = hijos[0] if hijos else None
    if memo[grupo]:
        AVISOS[grupo] = memo[grupo]
    return memo[grupo]


def parchar():
    """Idempotente. Devuelve True si quedo aplicado."""
    if os.environ.get("PEGCRAFT_PUERTO_GRUPO", "si") == "no":
        return False
    from . import apilado  # noqa: F401  (deja lector_xstage importable)
    from lector_xstage.core import scene_graph as sg
    G = sg.SceneGraph
    if getattr(G, "_pegcraft_puerto_grupo", False):
        return True
    orig = G._cable_origen

    def _cable_origen(self, s, sp, depth):
        sn = self.nodes[s]
        if sn.type == sg.GROUP:
            mpo = _mpo_por_tipo(sg, self, s)
            if mpo and self._edges_in.get((mpo, sp)):
                return self._cables(mpo, sp, depth + 1)
            return [(s, sp)]
        return orig(self, s, sp, depth)

    G._cable_origen = _cable_origen
    G._pegcraft_puerto_grupo = True
    return True
