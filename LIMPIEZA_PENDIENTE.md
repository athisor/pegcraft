# Limitaciones conocidas

Este documento resume lo que falta para compilar y ejecutar pegcraft en una máquina ajena. No se ha probado la instalación fuera del equipo de origen.

## Dependencias externas que no están en este repositorio

1. **Lectores `.tvg` y `.plt`: resuelto.** Ya son del repositorio (`sightread/tvg/`, `sightread/plt/`, solo biblioteca estándar; `sightread/` es un git subtree) y el horneado no depende de código externo.
   Quedan sin cubrir (ver README, «Límites conocidos»): texto, texturas, `tGTI`/`TGRV`, formas F=4/5/6, y el degradado radial es un supuesto sin ejemplo medido.
   La versión del lector entra en la clave del almacén de activos (`compilar/almacen.version_conversor`: hash de `sightread/tvg`, `sightread/plt` y `bake/gradientes.py`).
2. **Forks `storytold` con `rev` fijo** (`egui`, `winit`, `craft-ui`) en `crates/pegcraft-viewer-craft/Cargo.toml`: dependen de GitHub; si una revisión desaparece, no compila.
   Falta `cargo vendor`. `cargo check --offline` pasó solo con la caché de cargo de la máquina de origen.
3. **Visor:** `abrir.rs` asume que se ejecuta desde la raíz del repositorio y que `python` está en el PATH. No se ejecutó el visor tras anonimizar rutas.4. **`Cargo.lock` de `pegcraft-gpu` y `pegcraft-viewer`** vienen de otro proyecto y conviene regenerarlos. Los crates no comparten workspace, y `pegcraft-viewer` es un spike duplicado.
5. **No hay escenas de producción de ejemplo.** Las pruebas del horneado usan los casos sintéticos de `sightread/tests/fixtures/lector/casos/`; las pocas que necesitan una escena propia
   (`PEGCRAFT_XSTAGE_PRUEBA`) o los dibujos `.tvg` se omiten solas (149 pruebas, 5 omitidas).
6. **Configuración de producción que antes iba fija en el código** (ahora por entorno, vacía por omisión): `PEGCRAFT_EXCLUIR` (regex de rutas de nodo que no se dibujan; antes
   fija) y `PEGCRAFT_Z_EXCEPCIONES` (nombres de piezas con Z conocida, solo informativo).
7. **Z con tolerancia en el apilado** (`bake/apilado.TOL_Z`, `PEGCRAFT_TOL_Z`): el lector calcula la Z exacta y el apilado trata como empatadas las que difieren menos de 6e-6.
   Es un valor ajustado a un banco de 36 horneados; conviene medirlo con más planos o contra Harmony (hay Z reales separadas por 1e-5).
8. **Sesgo (skew):** `bake/matriz_causal` aplica el sesgo con `K = [[1, tan], [0, 1]]` y signo supuesto; el lector, en modo paridad, lo ignora en su propia matriz (R4) y en modo
   `harmony` lo aplica como `K(θ)=[[1, sin θ],[0, cos θ]]` medido. Falta unificar y medir (ver ADR-0010).

## Estado del proyecto

- Nombre de trabajo; puede cambiar.
- Licencia: `MIT OR Apache-2.0` (ver `LICENSE-MIT`, `LICENSE-APACHE`, `NOTICE`). Procedencia de lo consultado: `ATTRIBUTION.md`.
- Los comentarios «MEDIDO en…» citan mediciones hechas contra renders de referencia que no se publican.
