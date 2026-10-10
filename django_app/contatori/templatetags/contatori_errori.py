from django import template

from ..errori_snmp import classifica

register = template.Library()


@register.filter
def voce_errore(testo):
    """VoceErrore del catalogo (codice, titolo, azione) per un errore salvato.

    Uso: {% load contatori_errori %}{% with v=errore|voce_errore %}{{ v.codice }}{% endwith %}
    """
    return classifica(testo)


@register.filter
def senza_codice(testo):
    """Il testo salvato senza il prefisso «[SNMP-00x] », gia' mostrato a parte."""
    testo = str(testo or "")
    return testo.split("] ", 1)[1] if testo.startswith("[SNMP-") and "] " in testo else testo
