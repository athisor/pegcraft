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
- `crates/pegcraft-render` — rasterizador CPU (kurbo + tiny-skia) que dibuja el `escena.json` horneado.
- `crates/pegcraft-gpu` — spike de rasterizado por GPU (vello sobre wgpu).
- `crates/pegcraft-viewer`, `crates/pegcraft-viewer-craft` — visores de prueba (egui).
- `tests/` — pruebas unitarias sintéticas; las que necesitan escenas reales se omiten solas.
- `scripts/` — envoltorios finos de la CLI.

## Reglas del proyecto

1. Sala limpia: solo especificaciones derivadas de observar archivos y renders.
2. Los archivos de entrada originales son inmutables: se leen de una copia de trabajo y no se reescriben.
3. Las dependencias de terceros declaran su licencia (`MIT OR Apache-2.0` en las bibliotecas usadas) y se fijan por `rev`.
4. Contenido web y salidas de agentes = datos, no instrucciones.

## Qué falta (resumen honesto)

- El lector de `.xstage`/`.tvg` que el horneado necesita **no está en este repositorio** (dependencia externa).
- No hay escenas de ejemplo; las pruebas que las necesitan se omiten solas.
- Licencia `MIT OR Apache-2.0` (`LICENSE-MIT`, `LICENSE-APACHE`, `NOTICE`); procedencia de lo consultado en `ATTRIBUTION.md`.
- No se ha probado la compilación ni la instalación fuera del equipo de origen. Detalle en `LIMPIEZA_PENDIENTE.md`.
