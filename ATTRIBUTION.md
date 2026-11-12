# Atribución

pegcraft es un proyecto independiente de sala limpia (ver [NOTICE](NOTICE)). Durante el diseño se consultó la familia
de aplicaciones y bibliotecas de código abierto **ArtCraft** (organización de GitHub `storytold`). Este archivo registra,
**por separado para cada paquete**, qué se (1) *usó como dependencia*, (2) *solo se observó* como referencia de diseño,
(3) *se copió o adaptó* y (4) *se extendió o modificó*, y qué *no se usó en absoluto*.

Etiquetas de evidencia: **[M]** verificado en el código, los manifiestos o el historial (se hizo una comparación de texto contra las fuentes originales);
**[I]** inferido de documentación o lectura; **[N]** no verificado. Nada se afirma como copiado si no lleva [M].

Todos los paquetes declaran `license = "MIT OR Apache-2.0"` en su `Cargo.toml` y traen `LICENSE-MIT`, `LICENSE-APACHE` y un `NOTICE` que dice
«Copyright (c) 2026 ArtCraft Team and the *\<paquete\>* contributors» [M, leído en los repositorios originales].
pegcraft no usa los nombres ArtCraft, AniCraft, VectorCraft, EffectCraft, FilmCraft, MaterialCraft ni SoundCraft como nombre o marca propios.

## Resumen

| Paquete | Dependencia | Solo observado | Copiado / adaptado | Extendido |
|---|---|---|---|---|
| craft-ui / craft-libs | **sí** (git, rev fijo) | ejemplo de docking | sin código [M] | no |
| forks de egui / winit (`storytold/egui`, `storytold/winit`) | **sí** (git `[patch]`, revs fijos) | – | el bloque `[patch]`, copiado del manifiesto de FilmCraft [M] | no |
| FilmCraft | no | lectura adelantada, shuttle, notas de composición | bloque `[patch]` + una línea de comentario; `Cargo.lock` sembrado [M] | no |
| AniCraft | no | rasterizador, trazos, recortes/máscaras, UI de línea de tiempo y escenario | **nada** [M] | no |
| VectorCraft | no | uso de `vello_cpu`, trazos de ancho variable, pruebas doradas | nada [N: no se comparó código] | no |
| EffectCraft | no | máscaras tiny-skia/kurbo, track matte, keyframes, dock | nada [M en dock y panel kit; N en el panel de capas] | no |
| MaterialCraft | no | patrones del editor de nodos | nada [M] | no |
| SoundCraft | no | solo arquitectura | nada | no |

## craft-ui y craft-libs  (`storytold/craft-libs`)

1. **Dependencia [M].** `craft-ui` desde `https://github.com/storytold/craft-libs`, fijado en la revisión
   `6e03f65bf45181db77ba6229716e6624db9eb25b`, características `serde` y `system_fonts` (ver `crates/pegcraft-viewer-craft/Cargo.toml`).
   Se usa para el docking (`craft_ui::docking`, `craft_ui::layout`) y la pila de fuentes (`craft_ui::fonts`). Licencia: MIT OR Apache-2.0.
   Vienen con él crates transitivos de craft-libs (por ejemplo de i18n y fuentes) [I]. La API es inestable (v0.1.0) y solo se obtiene por git.
2. **Observado [M].** `crates/ui/examples/docking_native.rs`: la idea de un `enum` de paneles más un `Layout<Panel>` dibujado por una implementación de `DockContent`.
3. **Copiado/adaptado.** Ningún código. Una comparación de líneas normalizadas entre `docking_native.rs` y `crates/pegcraft-viewer-craft/src/main.rs` halló solo 5 líneas comunes de 354,
   todas del arranque estándar de `eframe` o de las firmas obligatorias de `DockContent` (`body`, `logical_label`) [M]. Los cuerpos son distintos.
4. **Extendido.** Nada se modifica; pegcraft solo llama a la API pública.

## Forks de egui y winit  (`storytold/egui`, `storytold/winit`)

1. **Dependencia [M].** Mediante `[patch.crates-io]` en `crates/pegcraft-viewer-craft/Cargo.toml`: `storytold/egui` en `6d518fc799681571963842f95b55a6b68431b15a`
   (egui, epaint, ecolor, emath, egui-winit, egui-wgpu, egui_glow, egui_extras, egui_kittest y otros) y `storytold/winit` en
   `a517b3846ee8457d84ee4975110bfda6797c44dc`. Licencias: MIT OR Apache-2.0 (fork de egui) y Apache-2.0 (fork de winit, según detecta GitHub) [M].
   La característica `default_fonts` de egui trae sus fuentes incluidas, con sus propias licencias (OFL / Ubuntu Font Licence) [I]; este repositorio no las redistribuye.
2. **Observado.** –
3. **Copiado.** La lista de URL de git y revisiones fijas del bloque `[patch.crates-io]` (ver FilmCraft abajo).
4. **Modificado.** No.
Riesgo: las revisiones solo viven en GitHub; conviene `cargo vendor` antes de depender de ellas.

## FilmCraft  (`storytold/filmcraft`)

1. **Dependencia.** Ningún crate de FilmCraft es dependencia [M].
2. **Observado [I].** Documentación y cabeceras: un lector con lectura adelantada y un control shuttle en el crate de UI, y un compositor CPU en f32 premultiplicado de luz lineal.
   La comparación de código de `play_ahead.rs` y `shuttle.rs` contra `main.rs` no halló líneas comunes [M].
3. **Copiado/adaptado [M].** `crates/pegcraft-viewer-craft/Cargo.toml`:
   - el bloque `[patch.crates-io]` (unas 20 entradas git con revisiones fijas) y la línea de comentario que lo precede, tomados del `Cargo.toml` raíz de FilmCraft.
     11 de las 19 líneas normalizadas de ese manifiesto son idénticas a líneas de FilmCraft. Son datos de configuración, pero están copiados.
     Licencia de origen: MIT OR Apache-2.0. Se añadió un aviso de procedencia al inicio del archivo de destino.
   - `crates/pegcraft-viewer-craft/Cargo.lock` se sembró con el `Cargo.lock` de FilmCraft (el comentario del manifiesto lo dice; 331 de sus 342 pares paquete/versión aparecen también en el lock de FilmCraft) [M]. Son datos generados y no admiten cabecera.
4. **Extendido.** El manifiesto se redujo a las dependencias que el visor necesita.

## AniCraft  (`storytold/anicraft`)

1. **Dependencia.** No [M].
2. **Observado [M lo leído, I la lección].**
   - `crates/render/src/raster.rs` y `lib.rs`: cobertura exacta por acumulación de áreas firmadas de las aristas, una suma por fila, reglas de relleno (no-cero / par-impar),
     tolerancia de aplanado, composición f32 premultiplicada, bandas de filas deterministas. Lección: la precisión de cobertura en bordes con antialias podría explicar diferencias residuales;
     medirlo contra renders de referencia quedó escrito como experimento.
   - `crates/render/src/stroke.rs` y los ADR (ancho variable, clipPath como máscara, tolerancias de aceptación de GPU): trazos como unión de polígonos no-cero compuestos una sola vez; los trazos finos se desvanecen en vez de desaparecer.
   - Fuentes del crate de UI (`timeline.rs`, `stage.rs`, `panels.rs`, `library.rs`): transporte + lista de capas + rejilla de fotogramas virtualizada; escenario con caché por teselas.
   - `README`, `NOTICE`, `ATTRIBUTION.md`, `docs/brand/`: términos de licencia y de marca.
3. **Copiado/adaptado: nada [M].** Una nota de planificación temprana proponía copiar `raster.rs` al renderizador CPU. **No se hizo**:
   `crates/pegcraft-render` rasteriza con `tiny_skia::Pixmap::fill_path` y no tiene código de acumulación de áreas firmadas.
   La comparación por líneas normalizadas y por nombres de función entre `raster.rs` y `lib.rs` y `pegcraft-render/src/main.rs` y `pegcraft-gpu/src/main.rs` no halló nombres de función comunes y
   solo 3 líneas comunes, todas llamadas genéricas del codificador PNG o del cronómetro (`set_color`, `set_depth`, `elapsed`); el `main.rs` del visor comparte 1 línea trivial (`let ctx = ui.ctx().clone();`) con las fuentes de escenario y línea de tiempo.
4. **Extendido.** –

## VectorCraft  (`storytold/vectorcraft`)

1. **Dependencia.** No [M]. (`pegcraft-gpu` usa `vello` 0.10 de crates.io, que es un proyecto de Linebender y no de la familia ArtCraft [M].)
2. **Observado [I].** Documentación y fuentes leídas por la API de GitHub: delegación en `vello_cpu` (tiras dispersas, modos calidad/velocidad), contornos de trazo de ancho variable con perfiles monótonos (Fritsch–Carlson),
   pruebas de imagen dorada con aserciones por muestras de píxel. Lección: comparar imágenes con estadísticas y tolerancias, no con hashes.
3. **Copiado/adaptado.** Nada. No se comparó texto de ningún archivo de VectorCraft [N], pero ningún crate de VectorCraft es dependencia y ningún archivo lleva cabecera de VectorCraft.
4. **Extendido.** –

## EffectCraft  (`storytold/effectcraft`)

1. **Dependencia.** No [M]. (Un plan temprano de depender de su crate de keyframes no se llevó a cabo.)
2. **Observado [I].** `fill_coverage` con `tiny_skia::Mask`, aplicación de track matte (alfa / luma, invertidos), crate de keyframes (interpolación temporal Bézier y trayectoria espacial), dock y panel kit.
   Su pila de raster (kurbo + tiny-skia) es la misma que usa `pegcraft-render`; la elección de esos crates es una decisión independiente sobre crates públicos [I].
3. **Copiado/adaptado: nada [M en `dock.rs` y `panel_kit.rs`**, comparados con las fuentes del visor sin líneas comunes no triviales**]**. El panel de capas no se pudo descargar para compararlo **[N]**.
4. **Extendido.** –

## MaterialCraft  (`storytold/materialcraft`)

1. **Dependencia.** No [M].
2. **Observado [M].** El editor de nodos de `crates/ui-egui/src/graph/`: cámara (desplazar/zoom), tarjetas de nodo, cables Bézier, puertos numerados, rejilla, navegación por grupos.
   La cabecera de `crates/pegcraft-viewer-craft/src/nodos.rs` dice que se imitó el *patrón* de cámara/tarjetas/cables y que el código es original.
3. **Copiado/adaptado: nada [M].** Se compararon ocho archivos originales (`wire_geometry`, `graph_camera`, `node_card`, `port_hit`, `grid`, `node_layout`, `canvas`, `node_style`) con `nodos.rs`:
   sin líneas normalizadas comunes ni nombres de función comunes.
4. **Extendido.** `nodos.rs` es un visor de solo lectura alimentado por una exportación JSON del grafo de la escena; no edita nada.

## SoundCraft  (`storytold/soundcraft`)

1. **Dependencia.** No [M].
2. **Observado [I].** Solo documentos de arquitectura (crates en capas, registro de comandos). Sus funciones de forma de onda y mezcla se juzgaron fuera de alcance.
3. **Copiado/adaptado.** Nada. 4. **Extendido.** –

## Archivos que adaptan código propio de pegcraft

No es material de ArtCraft; se listan porque sus cabeceras dicen «adaptación»: `crates/pegcraft-viewer*/src/render.rs` adapta `crates/pegcraft-render/src/main.rs` (mismo repositorio, copias idénticas byte a byte en los dos visores),
y `crates/pegcraft-gpu/src/main.rs` copia la lógica de lectura de escenas de `pegcraft-render`.

## No usado

- El nombre **ArtCraft**, su wordmark y logos, el ícono de la app AniCraft y todo lo de `docs/brand/`: son marcas y **no** están cubiertas por las licencias de código abierto; aquí no se usan ni se distribuyen.
- Fuentes y conjuntos de íconos (Lucide, Feather, fuentes Ubuntu / Noto, `egui-phosphor`): no se incluye ninguno. Los íconos del visor se dibujan en código (`iconos.rs`).
- Documentos de muestra, corpus XFL, fixtures de prueba, imágenes doradas, presets, shaders y otros recursos de cualquier app ArtCraft.
- Cualquier código de Adobe, Toon Boom u otros productos comerciales (pegcraft es de sala limpia; ver NOTICE).

## Bibliotecas de terceros (no ArtCraft)

Rust: `kurbo`, `tiny-skia`, `roxmltree`, `serde_json`, `png`, `pollster`, `rfd`, `vello`/`wgpu`, `egui`/`eframe`; Python: `numpy`, `Pillow`, `safetensors`, entre otras.
Cada una conserva su propia licencia (ver los manifiestos y los archivos lock). Los textos de licencia no se reverificaron para este archivo **[N]**.
