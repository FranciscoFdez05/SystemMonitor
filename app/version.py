"""Version del proyecto, en un solo sitio.

Los scripts de despliegue la leen de aqui con sed para etiquetar la imagen, de
modo que la vuelta atras de docker-update.sh tenga a donde volver. Si esto
viviese solo dentro de la llamada a FastAPI, habria que parsear Python desde sh.
"""

__version__ = "1.0.0"
