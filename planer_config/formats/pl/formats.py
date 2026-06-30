"""Format daty: zawsze europejski dd.mm.yyyy (decyzja Sebastiana — spójność
w całym programie niezależnie od języka UI). Widgety dat mają explicit
``format="%Y-%m-%d"`` (type=date), więc input nie jest złamany; tu sterujemy
tylko WYŚWIETLANIEM bare-dat + adminem.
"""

DATE_FORMAT = "d.m.Y"
DATETIME_FORMAT = "d.m.Y H:i"
SHORT_DATE_FORMAT = "d.m.Y"
SHORT_DATETIME_FORMAT = "d.m.Y H:i"
# Parsowanie inputów: ISO (z <input type=date>) ORAZ dd.mm.yyyy (ręczne).
DATE_INPUT_FORMATS = ["%Y-%m-%d", "%d.%m.%Y"]
