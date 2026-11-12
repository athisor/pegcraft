# Procedencia del lector `.xstage`

Este documento dice de dónde sale cada hecho del formato que asume el lector (`lector/`). En el código, cada regla cita un identificador
(`P41`, `A4-05`, `A7b-02`, `R4`...); aquí se resuelve ese identificador.

## Alcance de la sala limpia

La sala limpia cubre **solo** este repositorio (paquete `sightread`):

- `lector/**` (lector `.xstage`, columnas, evaluación),
- `tvg/**` y `plt/**` (lectores de dibujos `.tvg` y de paletas `.plt`; sus reglas citan `TVG-v1`, `TVG-v0` y `CENSO-n`, el mismo método de arriba aplicado
  a esos formatos: observación de archivos propios, medición y convención declarada; el registro de los `CENSO-n` vive fuera de este repositorio),
- `sintetico/**` (generador de escenas sintéticas y cálculo de valores esperados),
- `tools/coherencia_path3d.py`,
- sus pruebas (`tests/**`) y los fixtures sintéticos de `tests/fixtures/lector/`.

El proyecto que consume este paquete (pegcraft: horneado, compilador, deformadores, visores) **no se presenta como sala limpia por este documento**. Usa el
lector a través de `lector/compat.py`, y su procedencia no se declara aquí. Ver también `NOTICE`.

## Método

1. **Fuentes permitidas.** Solo tres: (a) observación de archivos propios del estudio (la estructura XML, contada y medida con scripts propios);
   (b) medición en Harmony como caja negra, sobre escenas sintéticas; (c) convenciones de compatibilidad, declaradas como tales y no como verdad del
   formato. No se consulta código ni documentación de terceros, ni material del fabricante del programa, ni se ejecuta ni lee otro lector del formato.
2. **Jerarquía de verdad.** Medición en Harmony > observación de archivos propios > convención de compatibilidad. Cuando una convención de compatibilidad
   contradice una medición, la medición manda en el modo `harmony` y la convención se conserva, rotulada, en el modo por omisión.
3. **Cada hecho con su fuente.** Todo hecho del formato que el código asume lleva su identificador. En el código solo se citan identificadores,
   nunca nombres de escenas ni de personajes.
4. **Los atributos.** Los atributos se guardan como texto y se convierten según su uso (número, booleano, lista, enlace a columna). La lista de atributos
   y sus formas de valor sale de un censo propio de atributos sobre escenas del estudio (clases de atributo, valores y tipos de nodo en que aparecen);
   lo dudoso se mide en Harmony con escenas sintéticas.
5. **Pruebas sintéticas.** Ninguna escena de producción entra al repositorio. Los fixtures los genera `sintetico/generador.py` desde una
   especificación JSON, con nombres inventados, sin rutas absolutas, sin `metas`/firmas y de menos de 200 KB. El generador es determinista
   (`--verificar` regenera byte a byte). Los valores esperados (`*.esperado.json`) declaran su origen: `regla`, `paridad` (convención de compatibilidad) o
   `harmony` (sección `medicion`).
6. **Tolerancias por clase.** Exacto: textos, grafo, cables, orden, dibujo, apagado, padre, cadena. Canales y Z: <= 1e-6 en cuadros de llave y <= 1e-4
   entre llaves. Matriz: <= 2e-5 en estático y <= 1e-3 entre llaves. Las mediciones en Harmony tienen un error de lectura de ~5e-6 (matriz) y 3,4e-5
   campos (Z, que Harmony cuantiza).
7. **Mediciones: se edita una escena vacía del usuario.** Toda escena que se abre en Harmony se obtiene **editando una copia de una escena vacía creada
   y guardada por el usuario**: se insertan o cambian nodos, enlaces, columnas y elementos dentro de su XML, y todo lo demás se conserva byte a byte
   (también cualquier firma o metadato, como dato opaco). La herramienta nunca crea, recalcula, interpreta ni copia una firma de un archivo a otro.
   Para los `.tvg`, que llevan una firma sobre el contenido, cualquier dibujo nuevo o cambiado lo produce el Harmony del usuario.
8. **Dependencia en un solo sentido.** Este código no incorpora ni importa código de otros proyectos; otros proyectos pueden usarlo como dependencia.
   Un fallo hallado al usarlo se reporta como comportamiento (escena, valor esperado, valor obtenido), nunca como código ajeno.

### Modos del evaluador

- **`paridad` (por omisión):** modo de compatibilidad, el que consume el horneado de pegcraft. Sus convenciones, explícitas: la matriz va en campos
  componiendo directamente, sin compensar el aspecto de la escena (anisótropa); el sesgo no se aplica a la matriz (R4); un PEG apagado cuenta en la
  cadena y suma su Z (R7). Son convenciones, **no verdad medida**: Harmony las contradice (A4-01, A4-02, A4-05, A7b-02, A7b-03).
- **`harmony`:** medido en Harmony sobre escenas sintéticas. PEG apagado = identidad; sesgo `K(θ)`; composición en espacio de matriz y devolución en
  campos con `F = D⁻¹·M·D`. Se prueba contra los fixtures medidos (sección `medicion`).

### Tipos de fuente (columna «Fuente» de las tablas)

| Clave | Tipo |
|---|---|
| **Obs** | observación de archivos propios (estructura XML y recuentos sobre escenas del estudio) |
| **Harmony** | medición en Harmony como caja negra sobre escenas sintéticas editadas desde una escena vacía del usuario |
| **Compat** | convención de compatibilidad (reglas del modo por omisión; no medidas, o contradichas por una medición) |

## Hechos citados en el código

### Estructura del archivo

| ID | Hecho | Fuente |
|---|---|---|
| P01 | Raíz `<project source version build creator>` con hijos `elements, options, timelineMarkers, scenes, symbols, timeline, metas` | Obs |
| P02 | `options/metrics`: `unitAspectRatioX/Y`, `numberOfUnitsX/Y/Z` (por omisión 4, 3, 24, 24, 12) | Obs |
| P03 | `options/framerate`, `pixelPerModelUnitForVectorLayers` y `resolution` | Obs |
| P04 | `scenes/scene@{name,id,nbframes,startFrame,stopFrame}`; el número de fotogramas es `nbframes` | Obs |
| P05 | Hijos de `scene`: `columns, options, rootgroup, unconnectedComposite, timelineOrderer` | Obs |
| P06 | `rootgroup` y `group` contienen `options, nodeslist, linkedlist`; `group` añade `attrs` y a veces `backdrops` | Obs |
| P07 | `module@{type,name,pos,publishUnderTab}`; `pos="x,y,n"` | Obs |
| P08 | Un grupo es `<group name pos>` sin atributo `type`; el lector lo tipifica `GROUP` | Obs |
| P09 | `link@{in,out}` con `inport`/`outport` opcionales (0 si faltan) | Obs |
| P10 | Los enlaces nombran nodos por nombre dentro del grupo que los contiene | Obs |
| P11 | La salida k de un grupo es la fuente de la entrada k de su `MULTIPORT_OUT`; la entrada del grupo alimenta al nodo conectado a su `MULTIPORT_IN`; vale anidado | Obs |
| P12 | La salida de un grupo se identifica por **tipo** `MULTIPORT_OUT`, no por nombre (hay nodos con el mismo nombre en grupos distintos) | Obs |
| P14 | Apagado = `options/disabled@val="true"` (módulo o grupo) | Obs |
| P15 | Herencia del apagado de un grupo a sus hijos: no se sabía por observación; se midió en Harmony (A4-04, A7b-04) | Obs + Harmony |
| P16 | Tipos de columna presentes en escenas del estudio: 0 (exposición), 1 (sonido), 2 (trayectoria 3D), 3 (función), 10 (script/controlador) | Obs |
| P17 | Columna tipo 3: `<step>`, `<points version="2"><pt constSeg x yLocal y ...>`; `x` puede ser lista o rangos (`"1-2,82,91-97"`); los `pt` no vienen ordenados | Obs |
| P18 | Columna tipo 0: `<elementSeq exposures val id>`; `id` es el id del **elemento**, no de la columna | Obs |
| P19 | Columna tipo 2: `infoX/Y/Z/Velocity`, `path3D@{useVeloX,Y,Z,constantZ}` con `pt@{val="x,y,z",lockedInTime}` y `<velocity type="3">` anidada | Obs |
| P20 | `elements/element@{id,elementName,elementFolder,...}` con `drawings/dwg@name`; un READ obtiene su dibujo de la columna del atributo `drawing/element@col` | Obs |
| P21 | Un atributo animado lleva `col="..."` en su propio elemento; el `val` es el valor de reposo | Obs |
| P22 | La posición animada de un PEG va en `position/attr3dpath@col` (columna tipo 2) si `position/separate="false"` | Obs |
| P23 | `angle` y `rotation/anglez` apuntan a la misma columna | Obs |
| P24 | Existen `scale/separate`, `rotation/separate`, `position/separate`; `scale/inFields` es siempre `false` | Obs |
| P25 | Los valores de atributo pueden contener saltos de línea, crudos o como `&#10;` | Obs |
| P26 | La firma `checksumValidation` es opaca y no hace falta para leer | Obs |

### Columnas

| ID | Hecho | Fuente |
|---|---|---|
| P30 | Exposición: cada cuadro nombrado muestra su dibujo y los demás nada (sin sostenido); reglas de solape en orden de archivo; un `elementSeq` con id de elemento inexistente se ignora | Harmony |
| P31 | Bézier `corner`: cúbica en (cuadro, valor) con manijas guardadas relativas (ausentes = 0); `constSeg` = escalón; fuera de rango vale el extremo | Harmony |
| P32 | `straight` y `smooth` evalúan igual: alinear manijas en puntos interiores y recortar por tramo | Harmony |
| P33 | `yLocal` manda sobre `y` | Obs + Harmony |
| P34 | Trayectoria 3D: spline Hermite (tensión/continuidad/sesgo) muestreada en 50 pasos por tramo; avance por longitud de arco en espacio de matriz con `K = (2aX/(aY·nY), 2/nY, KX·nX/nZ)`; `velocity` = fracción de la longitud total | Harmony |
| P35 | Los `<pt>` no vienen ordenados; se ordenan por `x` | Obs |
| P36 | Las columnas de sonido (1) y de script/controlador (10) se leen como opacas, sin evaluarlas | Obs |
| A3-01 | Guardas de robustez de la trayectoria 3D: 0 puntos = (0,0,0); 1 punto = constante; dos cuerdas nulas = pesos 0,5; longitud nula = primer punto. No lanzar nunca | Compat |
| A3-02 | Existen columnas tipo 2 sin `path3D` y `path3D` sin puntos; se tratan como opacas | Obs |
| A4-08 | Una trayectoria con puntos repetidos no debe lanzar `ZeroDivisionError` (regresión cubierta por prueba) | Obs |
| A7b-05 | Velocity con `y` fuera de [0,1] en llaves fijas: Harmony no extrapola ni retrocede | Harmony |
| A7b-06 | Velocity con llave en el cuadro de un punto fijo: normalización por tramo; con llaves solo en los extremos, `y` es fracción de la longitud total | Harmony (parcial) |
| A7b-07 | Puntos coincidentes de una trayectoria: entre llaves avanza con la velocity por omisión; solo en la llave vale el punto | Harmony |
| A7b-08 | Harmony cambia `&` por `_` en el nombre de un nodo al abrir la escena; el texto de los atributos se conserva (LF, CRLF, entidades) | Harmony |
| A7b-09 | Harmony abre sin rechazo las 20 escenas sintéticas de medición (BOM, trayectorias de un punto o de puntos coincidentes) y conserva nodos, cables y marcas de apagado | Harmony |
| A7b-10 | Sesgo animado y cadenas de dos PEG con traslación, pivote, rotación, escala no uniforme, sesgo y offset de READ: el modelo del modo `harmony` coincide con error 0 | Harmony |

### Evaluación de escena

| ID | Hecho | Fuente |
|---|---|---|
| P40 | Convención de matriz `[[a,b,tx],[c,d,ty]]`, `x' = a·x + b·y + tx`; rotación `anglez` antihoraria en grados; traslación en campos | Compat |
| P41 | Matriz local de un PEG con sesgo 0: `T(pos)·T(pivote)·R(anglez)·S(sx,sy)·T(−pivote)` | Compat |
| P42 | Matriz mundo = producto de las matrices locales de los PEG aguas arriba por el puerto 0; `CurveModule`, `OffsetModule`, `AutoPatchModule`, grupos y `MULTIPORT_*` no la cambian | Compat |
| P43 | La cadena a través de constraints, conmutadores y controladores no está medida; se aplica la convención de R5 | Compat |
| P44 | Z de un READ = suma de `posicion.z` de los PEG de su cadena | Compat |
| P45 | Un PEG apagado cuenta en la suma de Z en el modo por omisión; Harmony lo trata como identidad (A4-01) | Compat |
| P46 | `offset.z` del propio READ y `translate.z` de un `StaticConstraint` suman a la Z (A4-03 para el READ) | Compat + Harmony |
| P48 | `padre` es el grupo contenedor sin `Top` (`"G/H"`), `None` en la raíz | Obs |
| P49 | El orden de `nodos(f)` es el preorden de documento | Obs |
| P52 | `atributo` devuelve el texto crudo de `val` sin evaluar la columna | Obs |
| A2-01 | `backdrop@topLeft` y `@bottomRight` son `"x,y"`; un nodo está «en» el backdrop si su `pos` cae dentro del rectángulo, bordes incluidos | Obs |
| A2-03 | `resumen.composites` cuenta todo tipo que contiene «COMPOSITE» (incluye los de deformación) | Compat |
| A2-06 | Un `group` puede traer `options/disabled@val="true"`, igual que un módulo | Obs |
| A4-01 | Un PEG con marca propia de apagado es identidad: no transforma ni suma Z | Harmony |
| A4-02 | `getMatrix` está en espacio de matriz: posición, offset y pivote se escalan por `K=(KX,KY,KZ)` antes de componer; en campos, `F = D⁻¹·M·D`, `D=diag(KX,KY,KZ,1)` | Harmony |
| A4-03 | El READ aplica `T(offset)·T(piv)·R·S·T(−piv)` a la derecha de la cadena; `offset.z` suma a la Z | Harmony |
| A4-04 | Un grupo apagado impide dibujar los READ de dentro, pero no cambia ninguna matriz; `apagado_efectivo` (propio o de un grupo ascendente) solo decide el dibujo | Harmony |
| A4-05 | Sesgo: `K(θ)=[[1, sin θ],[0, cos θ]]`, orden `R·K·S`; el READ sesga igual que un PEG | Harmony |
| A6-01 | Apilado: dos Z que difieren en menos de `TOL_Z = 6e-6` son la misma Z (el horneado compara contra Z redondeadas) | Compat |
| A6-02 | El volcado de un PEG de cámara se redondea a 5 decimales para que un ruido de 3e-7 siga contando como identidad | Compat |
| A7-01 | Un enlace se escribe `link out=<origen> in=<destino> [inport] [outport]`; se omiten los puertos 0 | Obs |
| A7b-01 | La traslación `tx, ty, z` de un PEG sin padre ni pivote es su posición en campos tal cual, con `F = D⁻¹·M·D` | Harmony |
| A7b-02 | La matriz de compatibilidad (sin compensar el aspecto) difiere de la de Harmony cuando hay rotación; coinciden sin rotación | Harmony |
| A7b-03 | PEG apagado = identidad también en otra escena (confirma A4-01); el READ se dibuja | Harmony |
| A7b-04 | Grupos apagados anidados: un READ no se dibuja si cualquier grupo ascendente está apagado | Harmony |

### Reglas de evaluación R1-R12

| ID | Regla | Fuente |
|---|---|---|
| R1 | Valor de un atributo: columna (`col`) si existe; si no `val`; si no `defaultValue`. En columnas tipo 3, `yLocal` primero | Obs (P21, P33) |
| R2 | Columnas: exposición sin sostenido; Bézier corner/straight/smooth; trayectoria 3D de 50 pasos con guardas | Harmony + Compat (A3-01) |
| R3 | Canales del PEG: posición de `attr3dpath` si `position/separate="false"`, si no `position/x|y|z`; escala `scale/x|y`; rotación `rotation/anglez`; sesgo `skew`; pivote `pivot/x|y` | Obs (P21-P24) |
| R4 | Matriz local del PEG = `T(pos)·T(piv)·R·S·T(−piv)`; en el modo por omisión el sesgo no se aplica a la matriz (con aviso) | Compat |
| R5 | Matriz mundo = producto aguas arriba por el puerto 0; transparentes: `CurveModule`, `OffsetModule`, `AutoPatchModule`, `GROUP`, `MULTIPORT_*`, `PointConstraint2`, `TransformationSwitch`; `StaticConstraint` = matriz estática; la cadena se corta si llega por otro `READ` o por un `COMPOSITE` | Compat |
| R6 | El READ aplica su transformación propia a la derecha de la cadena | Compat; medido en A4-03 |
| R7 | Z = suma de `posicion.z` de los PEG de la cadena (apagados incluidos en el modo por omisión) + `translate.z` de `StaticConstraint` + `offset.z` del READ; 0 si la cadena se corta | Compat |
| R8 | `apagado` = bandera propia; `apagado_efectivo` aparte | Obs (P14) |
| R9 | `padre` = grupo contenedor sin `Top` | Obs (P48) |
| R10 | Orden de `nodos(f)` = preorden de documento | Obs (P49) |
| R11 | Dibujo: `drawing/element@col` → exposición → elemento por `id`; sin dibujo se omite con `solo_con_dibujo` | Obs (P18, P20, P30) |
| R12 | `invertido` no se calcula; `avisos` no forman parte de las comparaciones | Compat |

## Lo que no está respaldado

Cadena a través de constraints y conmutadores (P43), manijas de velocity fuera de [0,1] entre llaves interiores no monótonas, `splineOffset`,
`faceCamera`, `cameraAlignment`, `enable3d`, `useDrawingPivot`, `flipHor/flipVert` y `position/separate="true"` con columna en `x/y/z`
(la matriz de Harmony no se mueve cuando `separate="false"` y hay columna en `position/x`). El código no debe asumirlos.
