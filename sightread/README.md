# sightread

Lectores de **sala limpia** de los formatos de escena de Harmony, solo con la biblioteca estándar de Python (3.11 o más nuevo):

| Subpaquete | Lee |
|---|---|
| `sightread.lector` | escenas `.xstage`: grafo de nodos y cables, columnas (exposición, funciones Bézier, trayectorias 3D) y evaluación de un nodo en un fotograma |
| `sightread.tvg` | dibujos vectoriales `.tvg` (decodificación y conversión a SVG) |
| `sightread.plt` | paletas `.plt` / `palette-library` (colores y degradados) |

Además: `sightread.rutas` (búsqueda de archivos tolerante a mayúsculas) y `sightread.sintetico` (generador de escenas y dibujos sintéticos, con el cálculo de sus valores esperados).

> Implementación de sala limpia: parte de observar archivos propios y de medir un programa como caja negra sobre escenas sintéticas, sin código ni
> documentación del fabricante. **No está afiliado a Toon Boom Animation Inc.**; «Harmony» es marca de su dueño y aquí solo nombra el formato.
> De dónde sale cada regla: [`docs/PROCEDENCIA.md`](docs/PROCEDENCIA.md). Licencia `MIT OR Apache-2.0`.

## Uso

```python
from sightread.lector import abrir, Evaluador
from sightread.tvg import decodificar, a_svg
from sightread import plt

escena = abrir("escena.xstage")
```

El nombre que se importa es `sightread`, así que **la carpeta del repositorio debe llamarse `sightread`** (en pegcraft es `sightread/` en la raíz). Si algún día va a PyPI,
la distribución se llama `sightreader` (el nombre `sightread` está reservado allí); el paquete sigue siendo `sightread`.

Dos modos de evaluación (`Evaluador(escena, modo=...)`): `"paridad"` (por omisión, convenciones de compatibilidad explícitas) y `"harmony"` (medido).

## Pruebas

Desde la raíz del repositorio (PowerShell 5.1):

```powershell
python -I -m unittest discover -s . -t .. -p "test_*.py"
```

`-t ..` hace que el directorio padre sea la raíz de importación, de modo que el paquete se importa como `sightread`. Las pruebas son sintéticas: los fixtures de
`tests/fixtures/lector/casos/` los genera `sintetico/generador.py` desde una especificación JSON (ver `sintetico/LEEME.md`). No hay escenas de producción.

Si el repositorio está dentro de otro (pegcraft), desde la raíz de ese:

```powershell
python -I -m unittest discover -s sightread -t . -p "test_*.py"
```

## Uso dentro de pegcraft (git subtree)

pegcraft lleva una copia de este repositorio en su carpeta `sightread/` con `git subtree`, para seguir siendo autocontenido. `<remoto>` es la URL (o ruta) de este repositorio.

Traer a pegcraft los cambios hechos aquí (desde la raíz de pegcraft, con el árbol limpio):

```powershell
git subtree pull --prefix sightread <remoto> main
```

Devolver aquí los cambios hechos dentro de pegcraft (a una rama, nunca directo a `main`):

```powershell
git subtree push --prefix sightread <remoto> mi-rama
```

Después se fusiona `mi-rama` en `main` de este repositorio y se vuelve a hacer `pull` en pegcraft. Los cambios a `sightread/` en pegcraft van en commits
separados de los demás, para que `subtree push` los pueda aislar.

## Reglas

1. Solo biblioteca estándar. 2. Ninguna escena, dibujo ni paleta de producción entra al repositorio (`.gitignore` los excluye fuera de `tests/`).
3. Cada regla del formato cita su procedencia en el código. 4. No se consulta código ni documentación de terceros.
