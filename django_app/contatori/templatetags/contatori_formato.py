from django import template

register = template.Library()


@register.filter
def durata(secondi):
    """Secondi -> "40 g 3 h", "5 h 12 min", "45 s". Vuoto se non numerico."""
    try:
        secondi = int(secondi)
    except (TypeError, ValueError):
        return ""
    giorni, resto = divmod(max(0, secondi), 86400)
    ore, resto = divmod(resto, 3600)
    minuti = resto // 60
    if giorni:
        return f"{giorni} g {ore} h"
    if ore:
        return f"{ore} h {minuti} min"
    return f"{minuti} min" if minuti else f"{secondi} s"
