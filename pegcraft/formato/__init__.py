"""Prototipo del formato de escena biunivoco con .xstage (ver (doc interna omitida).

  python -m pegcraft.formato ida <xstage> <salida.json[.gz]>
  python -m pegcraft.formato vuelta <entrada.json[.gz]> <salida.xstage>
  python -m pegcraft.formato verificar <xstage> [...]      # ida y vuelta en memoria, compara bytes
  python -m pegcraft.formato.medir                          # corpus banco\\ + <datos de trabajo omitidos> -> <datos de trabajo omitidos>
"""
from .xmlfiel import ida, vuelta, recorrer, attr, poner_attr, FORMATO, VERSION  # noqa: F401
