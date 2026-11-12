# Limitaciones conocidas

Este documento resume lo que falta para compilar y ejecutar pegcraft en una máquina ajena. No se ha probado la instalación fuera del equipo de origen.

## Dependencias externas que no están en este repositorio

1. **Lector de escenas `.xstage` (`lector_xstage`).** El horneado importa `lector_xstage.core.scene_graph`,
   `lector_xstage.propuesta_layout.{evaluar,cadena,lectura,caja,pose}` y `lector_xstage.utils.escena_io`.
   Hoy se espera la variable `PEGCRAFT_XSTAGE_API` (ruta a un `api.py` fachada) y `PEGCRAFT_XSTAGE_DIR` (carpeta que contiene el paquete).
   Sin él, `python -m pegcraft hornear` y `compilar` no funcionan.
2. **Lector `.tvg` (conversor a SVG).** `PEGCRAFT_TVG_DIR` apunta a la carpeta con sus módulos. Se usa en `bake/gradientes.py` y `compilar/almacen.py`.
3. **Forks `storytold` con `rev` fijo** (`egui`, `winit`, `craft-ui`) en `crates/pegcraft-viewer-craft/Cargo.toml`: dependen de GitHub; si una revisión desaparece, no compila.
   Falta `cargo vendor`. `cargo check --offline` pasó solo con la caché de cargo de la máquina de origen.
4. **Visor:** `abrir.rs` asume que se ejecuta desde la raíz del repositorio y que `python` está en el PATH. No se ejecutó el visor tras anonimizar rutas.
5. **`Cargo.lock` de `pegcraft-gpu` y `pegcraft-viewer`** vienen de otro proyecto y conviene regenerarlos. Los crates no comparten workspace, y `pegcraft-viewer` es un spike duplicado.
6. **No hay escenas de ejemplo.** Las pruebas que las necesitan se omiten solas (58 pasan, 5 se omiten sin el lector externo).

## Estado del proyecto

- Nombre de trabajo; puede cambiar.
- Licencia: `MIT OR Apache-2.0` (ver `LICENSE-MIT`, `LICENSE-APACHE`, `NOTICE`). Procedencia de lo consultado: `ATTRIBUTION.md`.
- Los comentarios «MEDIDO en…» citan mediciones hechas contra renders de referencia que no se publican.
