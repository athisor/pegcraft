# Fixtures del lector `.xstage`

Escenas SINTETICAS, generadas desde una especificacion JSON por `sintetico/generador.py`. No hay escenas de produccion aqui:
nombres inventados, sin rutas absolutas, sin `checksumValidation` ni `metas`, menos de 200 KB cada una.

Cada caso en `casos/`:

| Archivo | Que es |
|---|---|
| `<caso>.json` | especificacion (nodos, grupos, enlaces, columnas, elementos) y `evaluar`: los fotogramas a calcular |
| `<caso>.xstage` | escena generada (determinista) |
| `<caso>.esperado.json` | resultado esperado, calculado por `sintetico/esperado.py` desde la especificacion |

Regenerar y comprobar (desde la raiz del repo):

    python -I sintetico/generador.py --dir tests/fixtures/lector/casos
    python -I sintetico/esperado.py --dir tests/fixtures/lector/casos
    python -I sintetico/generador.py --dir tests/fixtures/lector/casos --verificar
    python -I sintetico/esperado.py --dir tests/fixtures/lector/casos --verificar
    python -I -m unittest discover -s sintetico

## Formato de `<caso>.esperado.json`

- `origen`: `"regla"` (calculado por reglas medidas) o `"paridad"` (nombre historico del modo de compatibilidad: reproduce lo que hace pegcraft y aun no esta medido en Harmony); `origen_por_bloque` lo desglosa. `medicion`: valores medidos en Harmony (ver el final); `{"estado": "pendiente"}` si el caso aun no se midio.
- `nodos`: preorden de documento; `ruta` con `Top/`, `padre` sin `Top` (`"G/H"`, `null` en la raiz), `apagado` propio y `apagado_efectivo`.
- `cables_literales`: `[grupo, origen, puerto_origen, destino, puerto_destino]`, rutas completas, tal como estan en el archivo.
- `fuentes`: por nodo y puerto de entrada, las fuentes resueltas a traves de grupos (`[ruta, puerto_salida]`); una salida de grupo vacia resuelve a `[grupo, k]`.
- `puertos_composite`: puertos de entrada con cable, ascendentes.
- `atributos`: texto crudo (`val`) de los atributos citados en `atributos_texto` de la especificacion.
- `evaluacion[<fotograma>][<ruta>]` (READ y PEG): `canales` (escala, rotacion, sesgo, pivote, posicion u offset), `cadena` (transformadores, del mas cercano al mas lejano), `cortada`, `z`, `matriz` (`[[a,b,tx],[c,d,ty]]`, `null` = sin referencia), `dibujo` (READ), `padre`, `apagado`, `apagado_efectivo` y `origen` por campo.
- La matriz de `regla`/`paridad` solo se da si la traslacion y el pivote son 0. El sesgo se ignora en esa matriz (R4). Lo que Harmony hace de verdad esta en `medicion`.

## Seccion `medicion` (origen `harmony`)

Medida con Harmony 24 `-batch` sobre una copia de una escena vacia creada por el usuario, a la que se le inserto el contenido del caso editando su XML; la firma de la escena del usuario se conserva sin tocar (ver `sintetico/LEEME.md`); el fixture publico no lleva `metas`. No sustituye a `regla`/`paridad`: convive con ellas y el modo «harmony» del lector se prueba contra ella (`docs/PROCEDENCIA.md`).

- `estado` (`"medido"`), `origen` (`"harmony"`), `version_harmony`, `fecha`, `metodo`.
- `unidades`: la matriz y la `z` van en CAMPOS: `F = D^-1 M D` con `D = diag(KX, KY, KZ, 1)` (`K`, `metricas`); `matriz = [[a,b,tx],[c,d,ty]]`. La traslacion `tx, ty, z` es la posicion en campos tal cual. Con 4:3 los terminos cruzados de una rotacion llevan los factores 0,75 y 1,333 (no es la matriz isotropa del modo de compatibilidad).
- `error_lectura`: `matriz_campos_xy` (5,1e-6) y `z_campos` (la Z se cuantiza a 1/65536 en espacio de matriz: 3,4e-5 campos).
- `nodos[<ruta>].fotogramas[<f>]`: `matriz`, `z`, `dibujo_expuesto` (READ, ruta relativa), `error_vs_modelo_harmony` (contra el modelo del modo «harmony»), `dif_vs_esperado_matriz` y `dif_vs_esperado_z` cuando `regla`/`paridad` dan referencia. Pueden aparecer fotogramas que `evaluacion` no tiene (c07, c08, c09, c19).
- `se_dibuja` (casos de apagado: c10, c11, c20): por READ, si el render del cuadro 1 lo dibuja, y el mismo render con todo encendido como control.
- `trayectoria_vs_evaluador` (c07, c08, c09, c19): posicion medida contra `sightread.lector.columnas` en cada fotograma.
- `atributos_texto_en_harmony` (c13, c14), `reinterpretacion_al_guardar` (nodos y cables antes y despues de que Harmony abra y guarde), `discrepancias_con_regla_paridad` y `notas`.
- `sintetico/esperado.py` conserva este bloque al regenerar; se incrusta con `esperado.py ESPEC.json --medicion bloque.json`.
