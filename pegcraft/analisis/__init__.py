"""Analisis de escenas para detectar LO QUE PEGCRAFT NO CONOCE O NO SOPORTA, y dejar un log para mejorar el sistema.

    python -m pegcraft analizar <carpeta|xstage...> [--planos lista] --log <ruta_base> [--fotogramas muestra]

`escena.analizar_escena(xstage)` -> hallazgos de UNA escena; `lote.analizar(...)` recorre varias y escribe `<base>.jsonl` (una linea por hallazgo y por escena,
incremental), `<base>.md` y `<base>.resumen.json`. Solo lectura sobre las escenas (se pueden analizar planos de produccion).
"""
CATEGORIAS = {
    "nodo_tipo_no_soportado": "tipo de nodo que ninguna etapa del horneado modela (lista unica: pegcraft.bake.apilado.TIPOS_MODELADOS)",
    "efecto_no_soportado": "nodo de efecto/mezcla que se compone como transparente o con un modo/parametro no modelado (BLEND_MODE, GLOW, otros)",
    "atributo_no_leido": "atributo con valor fuera de su defecto (o animado) en un nodo que el lector SI evalua, pero que ninguna etapa lee",
    "columna_opaca": "columna que el lector no evalua (sonido, script, tipo desconocido, tipo 2 sin path3D, columna que no se pudo construir)",
    "columna_aviso": "aviso de una columna al construirla o evaluarla (valores no numericos, cuadros invalidos, funciones raras)",
    "deformador_no_soportado": "valor de un deformador (Offset/Curve/DeformationComposite/KinematicOutput) fuera de lo modelado",
    "apilado_aviso": "estructura del grafo de imagen que el recorrido no resuelve del todo (cutter sin matte, READ por dos caminos, sin raiz...)",
    "matriz_aviso": "transformacion que no se aplica o se infiere (sesgo, PointConstraint2 no medido, camara sin metricas o con zoom/offset)",
    "escena_aviso": "aviso del lector al abrir la escena (sin rootgroup, sin metricas, nodo repetido, cable roto...)",
    "tvg_no_reconocido": "rasgo del .tvg que el lector no reconoce (forma, registro o version) o dibujo ilegible",
    "plt_no_reconocido": "rasgo de la paleta .plt que no se reconoce o que no se dibuja (linea desconocida, textura, degradado sin color)",
    "dibujo_faltante": "READ dibujado sin elemento o sin .tvg en disco",
    "paleta_faltante": "paleta declarada sin archivo o color usado que no esta en ninguna paleta",
    "aviso_otro": "aviso del horneado que no encaja en las demas categorias",
    "error_lectura": "una etapa del analisis reventó con una excepcion (tipo y mensaje corto en la clave)",
}
