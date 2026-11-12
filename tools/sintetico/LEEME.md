# Escenas sintéticas (`tools/sintetico`)

- `generador.py`: escribe un `.xstage` sintético y determinista desde una especificación JSON (`--verificar` regenera byte a byte).
- `esperado.py`: calcula el `<caso>.esperado.json` desde la especificación (nunca desde el `.xstage` ni desde un lector).
- Uso y formato de los fixtures: `tests/fixtures/lector/LEEME.md`. Procedencia de las reglas: `docs/lector/PROCEDENCIA.md`.

## Cómo se hacen las mediciones en Harmony

Las escenas sintéticas de este directorio son para las pruebas públicas: no las abre Harmony. Las mediciones (la sección `medicion` de los esperados)
se hacen aparte, con esta práctica:

1. El insumo es una **escena vacía creada y guardada por el usuario** en su propio Harmony.
2. Toda escena que va a abrir Harmony se obtiene **editando una copia** de esa escena vacía: se insertan o cambian nodos, enlaces, columnas y
   elementos dentro de su XML, y todo lo demás se conserva byte a byte (incluido cualquier metadato o firma, tratado como dato opaco).
3. **Nunca se copia una firma de un archivo a otro**, y la herramienta nunca crea, recalcula ni interpreta firmas. «Escena nueva» es una escena vacía
   que el usuario guarda en Harmony y que la herramienta rellena.
4. Los valores medidos se leen de Harmony como caja negra y se guardan en el gemelo privado de la escena; en el repo solo queda el valor medido.
5. Para los `.tvg`, cuya firma cubre el contenido, cualquier dibujo nuevo o cambiado lo produce el Harmony del usuario.
