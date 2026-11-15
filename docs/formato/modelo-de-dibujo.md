# Modelo de dibujo (v1)

Decisión y especificación del formato con que pegcraft guarda un dibujo **editable**. Implementación: `pegcraft/dibujo/`. Pruebas: `tests/test_dibujo.py`.

## Estado: en desarrollo

Este estándar está en construcción. La versión 1 es una primera implementación para converger en una sola forma de guardar un dibujo; se va a ampliar, y los cambios serán aditivos y subirán la versión.

Lo que resuelve hoy: guardar un dibujo como trazos editables (línea, grosor, color a cada lado, líneas invisibles, trazos que comparten puntos, las cuatro capas de arte y el color por id de paleta), en JSON y en SVG, con ida y vuelta comprobada.

Pendiente, sin fecha:

- el traductor hacia el JSON que el programa de origen acepta por su interfaz de scripts (el camino de vuelta de un dibujo editado);
- ampliar el dibujo sintético de `sightread/` con grosor variable y trazos que comparten puntos, para probar todo el modelo con datos sintéticos;
- que el lector avise del arte de mapa de bits y de la textura de lápiz, y entregue la matriz del degradado por trazo;
- descifrar el perfil de grosor en su forma alternativa y los números del perfil que hoy se guardan sin interpretar;
- un normalizador para SVG editados con otros programas;
- la tabla de tensores de dibujos, para análisis por lotes (sin diseñar).

## Decisión (15-11-2026)

**Contexto.** Un mismo dibujo se guardaba de seis maneras distintas según quién lo leyera (el archivo `.tvg`, el modelo del lector, el dibujo sintético de las pruebas, el JSON que entrega el programa de origen por script, el SVG aplanado del horneado y el dibujo simple del formato de destino). Ninguna servía para editar y volver. Además, el SVG del horneado no guarda trazos: guarda rellenos y líneas ya resueltos.

**Se decide:**

1. **Un solo modelo de dibujo**, con versión, y tres formas de guardarlo que dan ida y vuelta entre sí: **SVG con datos del trazo** (el archivo de verdad), **JSON** (pruebas, casos sintéticos y puente con el programa de origen) y, más adelante, una **tabla de tensores derivada** (análisis; sin diseñar).
2. **El dibujo se guarda como trazos, no como formas cerradas apiladas.** Cada trazo dice por dónde pasa, si se ve como línea (color y grosor) y **qué color hay a cada lado**. Una zona de color es lo que encierran los trazos que nombran ese color hacia adentro; por eso el color sigue a la línea al moverla.
3. **La forma cerrada rellena no es una pieza aparte:** es un trazo cerrado, sin línea, con color hacia adentro. Es como el programa de origen guarda lo que deja su pincel vectorial.
4. **Los datos del trazo mandan; la apariencia es derivada.** El SVG lleva la apariencia ya resuelta para que cualquier visor lo pinte, pero se regenera desde los datos y no se edita.
5. **Lo que no se descifra se declara, no se pierde en silencio:** el dibujo lleva la huella de su archivo de origen, su estado (`derived`, `adopted`, `new`) y la lista de lo que el origen trae y el lector no interpreta (`opaque`).
6. **Volver al programa de origen:** un dibujo `derived` vuelve como su archivo original, byte a byte. Un dibujo `adopted` o `new` lo escribe el propio programa de origen por su interfaz de scripts, a partir de la forma JSON. **pegcraft no escribe archivos `.tvg`**: llevan una firma sobre su contenido que solo el programa de origen produce.
7. **Los cambios al modelo son aditivos y suben la versión.**

La especificación general de este modelo es la de Lotte (decisión D-Draw y su enmienda del 15-11-2026); este documento es su aplicación en pegcraft más el anexo de lo que es propio de Harmony (los valores que empiezan con `x-`, `source` y `opaque`).

**Consecuencias.** El horneado y los rasterizadores no cambian: siguen dibujando la apariencia resuelta, que es la misma de antes. El SVG con datos pesa unas 3,3 veces más que el aplanado (medido), porque ahora lleva los trazos; el horneado sigue usando el aplanado mientras no se decida lo contrario. Lo nuevo que el editor necesite del formato de origen (texturas de lápiz, perfiles no descifrados, arte de mapa de bits) se aprende en `sightread/`, con su método, y entra aquí como campos nuevos.

## El modelo

### Dibujo

| campo | tipo | qué es |
|---|---|---|
| `version` | entero | `1` |
| `state` | texto | `derived` (igual a su origen), `adopted` (editado), `new` (creado aquí) |
| `units` | `{name, y}` | unidad de las coordenadas y sentido del eje vertical. Desde un `.tvg`: `{"name": "x-harmony", "y": "up"}` |
| `source` | `{kind, sha256, path}` | opcional: de dónde viene. `sha256` es la huella del archivo original |
| `opaque` | lista de textos | lo que el origen trae y no se descifró (abajo) |
| `palette` | `{id: color}` | colores que el dibujo conoce |
| `gradients` | `{id: [matriz]}` | matrices de los rellenos que no son sólidos (seis números cada una) |
| `arts` | lista | **siempre cuatro, en este orden:** `underlay`, `colour`, `line`, `overlay`. Cada una con `layers`, y cada capa con `strokes` |

### Trazo

| campo | tipo | qué es |
|---|---|---|
| `id` | texto | identificador estable y único en el dibujo. Desde un `.tvg`: `a<arte>-c<capa>-t<trazo>` |
| `points` | `[[x, y, es_ancla]]` | puntos en orden; `es_ancla` falso = tirador |
| `geometry_of` | id | en vez de `points`: toma los puntos de un trazo **anterior del mismo arte** (la línea y el borde del color son el mismo recorrido) |
| `closed` | booleano | el primer punto es igual al último |
| `line` | id de color | el trazo se ve como línea de este color |
| `width` | número | medio ancho de la línea (ancho total = 2 × `width`) |
| `profile` | objeto | grosor variable (abajo) |
| `fill_left`, `fill_right` | id de color | color a cada lado |
| `invisible` | `true` | no se dibuja como línea: solo cierra zonas o delimita color |

Los campos que no aplican se omiten. Un trazo lleva `points` o `geometry_of`, nunca los dos.

**Qué lado es cuál.** `fill_left` y `fill_right` son los lados **geométricos** al recorrer el trazo en el orden de sus puntos, con el eje vertical hacia arriba. Un contorno antihorario lleva su relleno en `fill_left`.

### Perfil de grosor

| campo | qué es |
|---|---|
| `knots` | `[[t, izquierda, derecha]]`: posición a lo largo del trazo (0 a 1, por longitud de arco) y medio ancho a cada lado |
| `interp` | cómo se interpola entre nudos: `linear`, `catmull-rom` o `x-harmony` |
| `raw` | opcional: ocho números por nudo que vienen del origen sin descifrar; se devuelven tal cual |

### Color

`{name, palette, kind, rgba}`. `kind` es `solid`, `gradient` o `texture`; `rgba` son cuatro enteros de 0 a 255, o nada si no es sólido. El **id** es el del origen (16 dígitos hexadecimales) y se conserva siempre: es lo que permite recolorear por paleta.

### `opaque`

| valor | qué significa |
|---|---|
| `text` | el origen trae una capa de texto, que no se lee |
| `profile-undecoded` | algún trazo trae un perfil de grosor en una forma que el lector no descifra; ese trazo queda con grosor constante |
| `palette-undecoded` | la paleta local no se pudo leer |
| `texture-fill` | hay colores de textura; se reconocen y no se dibujan |
| `block:<etiqueta>` | el archivo trae un bloque que el lector no interpreta (por ejemplo `block:TLAB`, arte de mapa de bits) |

## Forma SVG

```xml
<svg xmlns="http://www.w3.org/2000/svg" xmlns:lotte="https://lotte.dev/ns/draw" viewBox="…"
     lotte:version="1" lotte:precision="f32">
  <metadata>
    <lotte:drawing state="derived" units="x-harmony" y="up">
      <lotte:source kind="tvg" sha256="…" path="…"/>
      <lotte:opaque what="text"/>
      <lotte:color key="…" name="…" palette="…" kind="solid" rgba="220,40,40,255"/>
      <lotte:gradient color="…" m="1.0,0.0,0.0,1.0,0.0,0.0"/>
    </lotte:drawing>
  </metadata>
  <g transform="matrix(1 0 0 -1 0 0)"> … apariencia resuelta: DERIVADA … </g>
  <g lotte:role="data" display="none" transform="matrix(1 0 0 -1 0 0)">
    <g lotte:art="line"><g lotte:layer="0">
      <path id="a2-c0-t0" d="M 0 0 C 1 2 3 4 5 6" fill="none" stroke="none"
            lotte:line="…" lotte:width="1.5" lotte:knots="0,1.5,2.5;1,0.5,0.25" lotte:interp="x-harmony" lotte:raw="…"
            lotte:fill-left="…" lotte:fill-right="…" lotte:invisible="true"/>
      <path id="a2-c0-t1" lotte:geometry-of="a2-c0-t0" fill="none" stroke="none" lotte:fill-right="…"/>
    </g></g>
  </g>
</svg>
```

- El espacio de nombres se identifica por su dirección (`https://lotte.dev/ns/draw`); el prefijo es libre.
- **`d` es la línea central:** `M` y, por cada ancla, `L`, `Q` o `C` según lleve 0, 1 o 2 tiradores antes. Solo comandos absolutos. Si los puntos no caben en ese patrón, van en `lotte:points="x,y,1;x,y,0;…"` y no hay `d`.
- Los trazos de datos llevan `fill="none" stroke="none"`: no se pintan. Lo que se pinta es el primer grupo.
- **Números.** `lotte:precision="f32"` cuando todos los números del dibujo caben exactos en un real de 32 bits (es el caso de lo que viene de un `.tvg`): se escriben con las cifras justas y el lector los devuelve exactos. Si no, `f64` y se escriben completos.
- Un lector que no conozca el espacio de nombres ve un SVG corriente.

## Equivalencias

| modelo | lector (`sightread.tvg`) | JSON del script de Harmony |
|---|---|---|
| `arts[i]` | `artes[nombre]` | `arts[i]` (0 underlay, 1 colour, 2 line, 3 overlay) |
| `layers`, `strokes` | `capas`, `trazos` | `layers`, `strokes` |
| `points` `[x, y, es_ancla]` | `puntos` + `anclas` | `path` `{x, y, onCurve}` |
| `geometry_of` | `ref` (los dos trazos comparten la lista de puntos) | uniones (`joints`, `fromJoint`, `toJoint`) |
| `line`, `width` | `estilo.lapiz`, `estilo.ancho` | `pencilColorId`, `thickness` |
| `profile.knots` | `perfil` (t, primer valor de cada lado) | tabla `thicknessPaths` de la capa |
| `profile.raw` | los otros cuatro valores de cada lado | – |
| **`fill_left`** | **`estilo.der`** | **`shaderRight`** |
| **`fill_right`** | **`estilo.izq`** | **`shaderLeft`** |
| `invisible` | `estilo.invisible` | `invisible` |
| id de color | id de 16 dígitos | `colorId` |

Los nombres «izquierda» y «derecha» del origen quedan cruzados respecto de los lados geométricos con el eje vertical hacia arriba; el modelo usa los geométricos.

## Límites de la versión 1

- La matriz de un degradado se guarda por color, no por trazo: el lector no dice de qué trazo es cada una.
- El lector no expone la textura del lápiz ni avisa de ella; esos datos no llegan al modelo.
- La apariencia resuelta usa la paleta local del dibujo; la paleta de la escena se aplica al hornear.
- La interpolación `x-harmony` del perfil no está descifrada: se dibuja con rectas entre nudos.
- Si alguien edita la línea central con un editor de SVG que reescriba `d` en comandos relativos o borre los `id`, el lector lo rechaza. No hay normalizador todavía.
- No hay todavía escritor hacia el JSON del script de Harmony ni tabla de tensores.

## Cómo se comprueba

```
python -m pegcraft dibujo <carpeta o .tvg> --verificar [--tope N]
```

Por cada dibujo: está bien formado; dibujo → modelo del lector → dibujo, igual; dibujo → SVG → dibujo, igual; y la apariencia resuelta del SVG nuevo es, carácter a carácter, la que el lector daba antes. Medido el 15-11-2026 sobre una muestra privada de 2 482 dibujos de producción (124 214 trazos; 49 190 comparten puntos, 21 886 llevan perfil de grosor): los cuatro controles pasan en los 2 482.

```
python -m pegcraft dibujo dibujo.tvg -o dibujo.svg --json dibujo.json
```
