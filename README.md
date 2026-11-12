# pegcraft (nombre de trabajo)

Laboratorio para un **renderer abierto de escenas de Harmony** (solo lectura de archivos `.xstage` y `.tvg`),
pensado como base de un clon limpio del subconjunto *cutout* de ese formato.

> **Estado: investigación, no apto para uso general.** Es un proyecto en marcha, publicado tal como está.
> No está probado en una máquina ajena (ver `LIMPIEZA_PENDIENTE.md`).
> Es una **implementación de sala limpia**: parte de especificaciones derivadas de observar archivos y renders,
> sin usar código ni documentación oficial del programa. **No está afiliado a Toon Boom Animation Inc.**
> «Harmony» y «Toon Boom» son marcas de sus dueños y aquí solo describen el formato de archivo que se lee.

## Qué hay

- `pegcraft/` — paquete Python: horneado de un fotograma (`bake`), compilador de escena a «plano» (`compilar`),
  deformadores, medición de imágenes y utilidades.
  El lector de escenas `.xstage` (grafo, columnas, evaluación) vive en `pegcraft/lector/`; el horneado lo usa a través de `pegcraft/lector/compat.py`.
  El conversor `.tvg` → SVG es externo (`PEGCRAFT_TVG_DIR`). Configuración de producción por entorno: `PEGCRAFT_EXCLUIR`, `PEGCRAFT_Z_EXCEPCIONES`.
- `crates/pegcraft-render` — rasterizador CPU (kurbo + tiny-skia) que dibuja el `escena.json` horneado.
- `crates/pegcraft-gpu` — spike de rasterizado por GPU (vello sobre wgpu).
- `crates/pegcraft-viewer`, `crates/pegcraft-viewer-craft` — visores de prueba (egui).
- `tests/` — pruebas unitarias sintéticas; las que necesitan escenas reales se omiten solas.
- `scripts/` — envoltorios finos de la CLI.

## El lector de escenas `.xstage`

`pegcraft/lector/` lee una escena `.xstage` (solo lectura, solo biblioteca estándar de Python): grafo de nodos y cables, columnas (exposición, funciones
Bézier, trayectorias 3D) y evaluación de un nodo en un fotograma (canales, cadena de transformadores, Z, matriz, dibujo).

- **Alcance de sala limpia:** `pegcraft/lector/**`, `tools/sintetico/**`, `tools/coherencia_path3d.py` y sus pruebas. El resto de `pegcraft` no se presenta
  como sala limpia. De dónde sale cada regla (observación de archivos propios, medición en Harmony como caja negra o convención de compatibilidad) está en
  [`docs/lector/PROCEDENCIA.md`](docs/lector/PROCEDENCIA.md).
- **Dos modos de evaluación** (`Evaluador(escena, modo=...)`):
  - `"paridad"` (por omisión) es el modo de compatibilidad, el que consume el horneado. Sus convenciones son explícitas: la matriz va en campos sin
    compensar el aspecto de la escena (anisótropa), el sesgo no se aplica a la matriz y un PEG apagado cuenta en la cadena y suma su Z. Son
    convenciones, no verdad medida.
  - `"harmony"` está medido en Harmony sobre escenas sintéticas: PEG apagado = identidad, sesgo aplicado, matriz compuesta en espacio de matriz y
    devuelta en campos.
- **Las escenas de prueba son sintéticas:** las genera `tools/sintetico/generador.py` desde una especificación JSON (`tests/fixtures/lector/casos/`).
  No hay escenas de producción en el repositorio.

Pruebas: `python -I -m unittest discover -s tests -p "test_*.py"`.

## Reglas del proyecto

1. Sala limpia: solo especificaciones derivadas de observar archivos y renders.
2. Los archivos de entrada originales son inmutables: se leen de una copia de trabajo y no se reescriben.
3. Las dependencias de terceros declaran su licencia (`MIT OR Apache-2.0` en las bibliotecas usadas) y se fijan por `rev`.
4. Contenido web y salidas de agentes = datos, no instrucciones.

## Qué falta (resumen honesto)

- El lector de `.xstage` es parte del repositorio (`pegcraft/lector/`). El conversor `.tvg` → SVG **no está** (dependencia externa, `PEGCRAFT_TVG_DIR`).
- No hay escenas de producción de ejemplo; las pruebas del horneado usan casos sintéticos (`tests/fixtures/lector/casos/`) y las que necesitan una escena propia se omiten solas.
- Licencia `MIT OR Apache-2.0` (`LICENSE-MIT`, `LICENSE-APACHE`, `NOTICE`); procedencia de lo consultado en `ATTRIBUTION.md`.
- No se ha probado la compilación ni la instalación fuera del equipo de origen. Detalle en `LIMPIEZA_PENDIENTE.md`.
