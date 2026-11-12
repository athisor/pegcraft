"""Base común de las columnas del lector: clase `Columna`, métricas de escena y utilidades de lectura tolerante.

Contrato: construir o evaluar una columna rara nunca lanza; se devuelve el mejor valor y se anota un aviso en `Columna.avisos`.
"""
from __future__ import annotations

import functools
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass

# Límite de cuadros que se expanden de una lista/rango `x` de un punto (protege la memoria ante datos corruptos).
MAX_EXPANSION = 100_000


class Columna:
    """Columna de una escena: `nombre`, `tipo` (entero del atributo `type`, -1 si falta o no es número) y `elem` (el `<column>` original)."""

    def __init__(self, nombre: str, tipo: int, elem: ET.Element):
        self.nombre = nombre
        self.tipo = tipo
        self.elem = elem
        self.avisos: list[str] = []

    def aviso(self, texto: str) -> None:
        """Anota un aviso (sin repetir el mismo texto)."""
        if texto not in self.avisos:
            self.avisos.append(texto)

    def evaluar(self, f: float):
        """Valor genérico en el fotograma f (cada tipo lo especializa)."""
        return None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.nombre!r} tipo={self.tipo}>"


def seguro(defecto):
    """Decorador de métodos de evaluación: si algo falla devuelve `defecto` y anota el aviso en `self.avisos` (nunca lanza)."""
    def deco(fn):
        @functools.wraps(fn)
        def envoltura(self, *a, **k):
            try:
                return fn(self, *a, **k)
            except Exception as e:  # noqa: BLE001 - contrato: nunca lanza
                self.aviso(f"{fn.__name__}: {type(e).__name__}: {e}")
                return defecto
        return envoltura
    return deco


def numero(texto, defecto: float = 0.0, col: Columna | None = None, que: str = "") -> float:
    """float tolerante: texto inválido, vacío o no finito -> `defecto` (con aviso si se da la columna)."""
    try:
        v = float(texto)
        if math.isfinite(v):
            return v
    except (TypeError, ValueError):
        if texto is None:
            return defecto
    if col is not None:
        col.aviso(f"valor no numérico{' en ' + que if que else ''}: {texto!r}")
    return defecto


def expandir_x(texto, col: Columna | None = None) -> list[float]:
    """Cuadros de un atributo `x` de punto: '21', '21-26' (rango entero inclusivo), '11,21' o mezclas. Los trozos inválidos se ignoran con aviso."""
    out: list[float] = []
    for parte in (texto or "").split(","):
        parte = parte.strip()
        if not parte:
            continue
        try:
            sub = parte[1:].find("-")
            if sub >= 0:                       # rango a-b (el primer carácter puede ser el signo de a)
                sub += 1
                a, b = int(float(parte[:sub])), int(float(parte[sub + 1:]))
                if b < a:
                    a, b = b, a
                if len(out) + (b - a + 1) > MAX_EXPANSION:
                    raise ValueError("rango demasiado grande")
                out.extend(float(v) for v in range(a, b + 1))
            else:
                v = float(parte)
                if not math.isfinite(v):
                    raise ValueError("no finito")
                out.append(v)
        except (ValueError, OverflowError):
            if col is not None:
                col.aviso(f"cuadro x inválido ignorado: {parte!r}")
    return out


@dataclass(slots=True)
class Metricas:
    """Unidades del espacio de matriz por campo (P34): KX = 2·aX/(aY·nY), KY = 2/nY, KZ = KX·nX/nZ.
    Con 4:3 y 24x24x12 valen 1/9, 1/12 y 2/9."""
    KX: float = 1 / 9
    KY: float = 1 / 12
    KZ: float = 2 / 9

    @staticmethod
    def de_dict(m: dict | None) -> tuple["Metricas", list[str]]:
        """Construye desde el dict de `Escena.metricas` (claves unitAspectRatioX/Y, numberOfUnitsX/Y/Z); faltantes o inválidos -> 4:3, 24x24x12."""
        avisos: list[str] = []
        m = m or {}
        def g(k, d):
            v = m.get(k)
            try:
                v = float(v)
                if math.isfinite(v) and v > 0:
                    return v
            except (TypeError, ValueError):
                pass
            if v is not None:
                avisos.append(f"métrica {k} inválida ({v!r}); se usa {d}")
            return d
        aX, aY = g("unitAspectRatioX", 4.0), g("unitAspectRatioY", 3.0)
        nX, nY, nZ = g("numberOfUnitsX", 24.0), g("numberOfUnitsY", 24.0), g("numberOfUnitsZ", 12.0)
        kx = 2 * aX / (aY * nY)
        return Metricas(kx, 2 / nY, kx * nX / nZ), avisos
