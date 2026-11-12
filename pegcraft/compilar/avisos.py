"""Codigos estables para los avisos del horneado (FASE 1 de (doc interna omitida).

`bake\\` emite cadenas libres; aqui se clasifican POR PREFIJO sin tocar la cadena (cuadro(N) no cambia ni un byte). El plano guarda en
`formato.avisos` el recuento por codigo; quien lo lee filtra por codigo, no por texto. Un aviso nuevo de bake sin regla cae en `OTRO`
(y el test `test_avisos` lo delata si aparece en los fixtures)."""
import re
from collections import Counter

# (codigo, regex sobre el texto, que significa para quien consume el plano)
REGLAS = [
    ("SESGO_NO_CONSIDERADO", r"^/.*: sesgo \S+ no se considera", "un PEG con sesgo (skew) que el motor no aplica"),
    ("TVG_ILEGIBLE", r"^TVG_ILEGIBLE ", "el conversor .tvg externo (PEGCRAFT_TVG_DIR) no pudo leer el dibujo: la pieza se omite"),
    ("SIN_TVG", r"^sin tvg ", "READ sin dibujo .tvg en la escena: pieza sin SVG"),
    ("MATRIZ_CAUSAL", r"^matriz causal:", "informativo: aspecto de unidad y PEG con sesgo aplicado"),
    ("DEFORMADOR_MODELO", r"^deformadores: modelo", "informativo: modelo de deformadores usado"),
    ("DEFORMADOR_NO_MODELADO", r"^deformadores no modelado", "un deformador cuyo caso no esta modelado: el dibujo puede diferir"),
    ("BLEND_MODE_NO_MODELADO", r"^BLEND_MODE_MODULE activo", "un BLEND_MODE_MODULE activo (p. ej. eMULTIPLY) que el horneado compone como normal: el fondo/tono puede diferir mucho"),
    ("GLOW_NO_MODELADO", r"^GLOW activo", "un GLOW activo con radio > 0 (o no legible): el desenfoque del glow no esta modelado"),
    ("GLOW_MULTIPLE", r"^GLOW multiples", "varios GLOW alcanzados en la escena: orden y suma no validados"),
    ("PC2_NO_MEDIDO", r"^PointConstraint2 con parametros no medidos", "PointConstraint2 con parametros fuera de lo medido (transformtype, primaryport, balance, stretch, volumemin/max, padres distintos)"),
    ("CAMARA_ZOOM_REENCUADRE", r"^camara: zoom de reencuadre", "CAMERA offset.z != numberOfUnitsY/2: zoom de reencuadre asumido (inferencia, 1 plano validado)"),
    ("CAMARA_OFFSET_XY", r"^camara: CAMERA offset\.x/y", "CAMERA offset.x/y != 0: desplazamiento del encuadre aplicado (inferencia, varios planos validados)"),
    ("CAMARA_APLICADA", r"^camara:", "informativo: Camera-P no identidad aplicada a todas las piezas"),
    ("PUERTO_GRUPO", r"^puerto_grupo", "grupo sin Multi-Port-Out: salida resuelta por tipo"),
]
# avisos que NO salen de bake: los pone el lector/compilador sobre el plano entero
EXTRA = {
    "PLANO_SIN_MEZCLA": "plano compilado antes del 12-11-2026 (sin cabecera `formato`): `pieza.mezcla` no se guardaba; si la escena tiene un "
                        "GLOW aditivo (p. ej. PLANO) el render pierde el brillo. Recompilar para repararlo",
}
_RX = [(c, re.compile(r)) for c, r, _ in REGLAS]
SIGNIFICADO = {c: s for c, _, s in REGLAS} | EXTRA


def codigo(texto):
    for c, rx in _RX:
        if rx.search(texto):
            return c
    return "OTRO"


def recuento(textos):
    """-> {codigo: n} ordenado por codigo."""
    return dict(sorted(Counter(codigo(t) for t in textos).items()))
