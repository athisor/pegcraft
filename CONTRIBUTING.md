# Cómo aportar a pegcraft

Gracias por el interés. Hay tres formas de aportar:

1. **Completar el diccionario de Harmony (lo más útil).** Analiza tus escenas con `pegcraft analizar ... --compartible` y abre un issue con el formulario «Desconocidos de Harmony». Solo se manda un resumen de tipos y conteos, nunca escenas ni nombres. Paso a paso, con la auditoría de privacidad: [`docs/aportar/AGENTE.md`](docs/aportar/AGENTE.md). Está escrito para que lo siga tu agente de programación, y una persona también puede seguirlo.
2. **Reportar un error de render:** abre un issue. Describe qué se ve distinto de Harmony y, si puedes, adjunta una escena **sintética** mínima que lo reproduzca. No subas escenas, dibujos ni paletas de producción.
3. **Código:** pull request contra `main`, con pruebas (`python -m unittest discover -s tests` y `python -m unittest discover -s sightread/tests -t .`). Reglas del proyecto en el [README](README.md#reglas-del-proyecto).

Lo que se publica en un issue o en un pull request es público: no incluyas rutas, nombres de proyectos, personajes ni clientes.
