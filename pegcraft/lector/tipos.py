"""Constantes del lector: tipos de nodo, métricas por omisión y límites."""
from __future__ import annotations

# Nombre del grupo raíz en las rutas de la API (siempre "Top/...").
RAIZ = "Top"

# P08: un grupo es <group> sin atributo type; el lector lo tipifica así.
TIPO_GRUPO = "GROUP"
TIPO_READ = "READ"
TIPO_PEG = "PEG"
TIPO_COMPOSITE = "COMPOSITE"
TIPO_MULTIPORT_IN = "MULTIPORT_IN"    # P12: se identifica por tipo, no por nombre
TIPO_MULTIPORT_OUT = "MULTIPORT_OUT"
TIPO_STATIC_CONSTRAINT = "StaticConstraint"
TIPO_POINT_CONSTRAINT = "PointConstraint2"

# Tipos por los que la cadena de transformación pasa sin cambiar la matriz (R5, P42).
TRANSPARENTES = frozenset({
    "CurveModule", "OffsetModule", "AutoPatchModule", TIPO_GRUPO,
    TIPO_MULTIPORT_IN, TIPO_MULTIPORT_OUT, "PointConstraint2", "TransformationSwitch",
})

# P02: valores de options/metrics cuando el archivo no los trae.
METRICAS_POR_OMISION = {
    "unitAspectRatioX": 4.0,
    "unitAspectRatioY": 3.0,
    "numberOfUnitsX": 24.0,
    "numberOfUnitsY": 24.0,
    "numberOfUnitsZ": 12.0,
}

# Profundidad máxima al resolver cables a través de grupos (protección de ciclos).
PROFUNDIDAD_MAXIMA = 200

# Tipo de columna de exposición de dibujos (P16, P18).
COLUMNA_EXPOSICION = "0"
