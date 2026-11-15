# Guía para agentes: aportar al diccionario de Harmony de pegcraft

Este documento está escrito para un agente de programación (Claude Code, Codex, Gemini CLI u otro) al que su usuario le pidió colaborar con pegcraft. Si eres una persona, también sirve: son los mismos pasos.

## De qué se trata

pegcraft lee y dibuja escenas de Toon Boom Harmony (`.xstage`, `.tvg`, `.plt`) sin abrir Harmony. Lo que entiende del formato (tipos de nodo, atributos, tipos de columna, modos de mezcla, deformadores, rasgos de los dibujos) es un **diccionario incompleto**. Se completa mejor con escenas reales de animadores, que traen cosas que ningún ejemplo sintético cubre.

`pegcraft analizar` recorre escenas y anota **lo que pegcraft no conoce o no soporta**. El aporte que pedimos es solo ese resumen: **nunca las escenas**.

## Reglas para el agente

1. **Solo con el permiso explícito de tu usuario**, y solo sobre las carpetas que él indique. Las escenas se leen; nada se escribe junto a ellas.
2. **Nunca se mandan escenas, dibujos, paletas, capturas ni el log completo.** Se manda solo el archivo `*_compartible.json`.
3. **Antes de mandar nada, muéstrale a tu usuario el archivo y espera su sí.** Lo que se publica en un issue es público.

## Pasos

### 1. Instalar

Necesitas Python 3.11 o más nuevo.

```
git clone https://github.com/athisor/pegcraft.git
cd pegcraft
pip install -e .
```

Los comandos se corren desde la raíz del repositorio.

### 2. Analizar

```
python -m pegcraft analizar <carpeta_de_escenas> --log <carpeta_tuya>/analisis --compartible
```

- `<carpeta_de_escenas>` se recorre de forma recursiva: un `.xstage` por plano. Para elegir solo algunos planos, usa `--planos a,b,c` (trozos de ruta) o `--planos lista.txt` (un `.xstage` por línea).
- Por omisión se evalúa una muestra de fotogramas (primero, medio y último): de 1 a 30 s por plano. `--fotogramas todos` es más completo y más lento.
- Una escena que falla no detiene el lote: queda anotada como `error_lectura`.
- Deja estos archivos:
  - `<base>.jsonl`, `<base>.md` y `<base>.resumen.json`: el detalle. **Son privados, no los mandes.**
  - `<base>_compartible.json`: lo único que se manda.

Con el visor de Windows se hace lo mismo desde Archivo > «Analizar carpeta de planos…», marcando «Log para compartir».

### 3. Auditar la privacidad (obligatorio)

El archivo compartible lleva solo categoría, clave (por ejemplo `BLEND_MODE_MODULE` o `CAMERA.fov`), conteos, número de escenas y las versiones de pegcraft y de Harmony. **No debe llevar rutas, nombres de escena, nombres de nodo, de personaje ni de proyecto, usuarios, correos ni texto libre.**

1. **Revisión automática.** `--compartible` ya la corre al terminar, y borra el archivo si falla. Córrela de nuevo comparando contra las escenas originales:
   ```
   python -m pegcraft analizar --verificar <base>_compartible.json --escenas <carpeta_de_escenas>
   ```
   Tiene que decir `OK`. Si sale con código 1, no lo mandes: el mensaje dice qué campo y por qué.
2. **Tu propia revisión.** Lee el JSON entero y busca en él los nombres de las carpetas, archivos y personajes de tu usuario, su nombre, el de su estudio y el de sus proyectos. Si aparece alguno, no lo mandes y abre un issue que describa el problema del verificador **sin incluir ese dato**.
3. **El sí de tu usuario.** Muéstrale el archivo, dile que va a quedar público en GitHub y espera su confirmación.

### 4. Mandarlo como issue

1. **Busca si ya se reportó.** Revisa los issues con la etiqueta `diccionario`, por ejemplo con `gh issue list --repo athisor/pegcraft --label diccionario --state all`. Si un issue abierto trata las mismas claves, agrega un comentario ahí con tus conteos en vez de abrir otro.
2. **Si no existe, abre uno** con el formulario «Desconocidos de Harmony» (web) o así:
   ```
   gh issue create --repo athisor/pegcraft --label diccionario --title "Desconocidos: <n> escenas, Harmony <versión>" --body-file cuerpo.md
   ```
   `cuerpo.md` lleva:
   - las versiones de pegcraft y de Harmony;
   - cuántas escenas se analizaron;
   - el contenido de `*_compartible.json` en un bloque ```` ```json ````;
   - una línea que confirme que se corrió `--verificar` y que el usuario lo aprobó.

## Qué hacemos con eso

Cada clave que se repite en escenas de distintas personas sube de prioridad. Se mide en Harmony, se modela y se agrega al diccionario. Cuando algo se resuelva, cerraremos el issue con el commit que lo resuelve.

## Otras formas de aportar

- **Código:** pull request contra `main`, con pruebas. Las escenas de prueba deben ser sintéticas (`sightread/sintetico`), nunca de producción.
- **Errores de render:** issue con la descripción y, si puedes, una escena **sintética** mínima que lo reproduzca.
