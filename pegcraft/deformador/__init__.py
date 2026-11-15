"""deformador: deformadores PARAMETRICOS (spike 12-11-2026, (doc interna omitida), <datos de trabajo omitidos>).

En vez de aplastar cada estado deformado en un SVG nuevo por cuadro (bake/deformadores.py), se guarda el SVG en REPOSO y los
parametros del deformador (esquema.py) y los puntos se deforman al renderizar (evaluador.py). No toca pegcraft/bake: importa su
matematica (curva de Bezier del eje, punto mas cercano, giro de la tangente) y solo separa lo que entra a ella.

  esquema.extraer(xs, f, dir_base)   .xstage + fotograma -> {ruta_read: spec}  (JSON serializable)
  evaluador.Plantilla(svg_reposo)    parseo y subdivision UNA vez por dibujo
  evaluador.deformar(plantilla, spec) -> puntos / SVG deformado por cuadro
  escena.armar(...)                  escena.json con los SVG deformados regenerados desde (reposo + parametros)
"""
import sys
sys.dont_write_bytecode = True
