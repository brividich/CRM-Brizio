"""SLA dei ticket in orario di lavoro (audit P10/P11, 23/11/2026).

Le ore SLA di una categoria contano solo dentro l'orario di lavoro (di base
8-17, da lunedì a venerdì) e saltano festivi e chiusure del calendario comune
(``core.calendario_it``). L'orario si cambia da Impostazioni ticket e vale per
tutti i ticket.

Le categorie e l'orario stanno in cache per un minuto: l'elenco dei ticket
legge le scadenze di ogni riga senza una query per ticket. La cache si svuota
quando una categoria o l'orario cambiano.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

from django.core.cache import cache
from django.utils import timezone

KEY_ORA_INIZIO = "tickets_sla_ora_inizio"
KEY_ORA_FINE = "tickets_sla_ora_fine"
ORA_INIZIO_DEFAULT = 8
ORA_FINE_DEFAULT = 17

# Promemoria «SLA scaduto»: il primo alla scadenza, poi un richiamo ogni N giorni.
RICHIAMO_GIORNI = 3

_CACHE_CATEGORIE = "tickets_sla_categorie"
_CACHE_ORARIO = "tickets_sla_orario"
_CACHE_SECONDI = 60
_GIORNI_MAX = 3660  # tetto di sicurezza del calcolo (dieci anni di calendario)


def _ora(raw, default: int) -> int:
    try:
        valore = int(raw)
    except (TypeError, ValueError):
        return default
    return valore if 0 <= valore <= 24 else default


def _leggi_orario() -> tuple[int, int]:
    from core.models import SiteConfig

    inizio = _ora(SiteConfig.get(KEY_ORA_INIZIO, ""), ORA_INIZIO_DEFAULT)
    fine = _ora(SiteConfig.get(KEY_ORA_FINE, ""), ORA_FINE_DEFAULT)
    if fine <= inizio:
        return ORA_INIZIO_DEFAULT, ORA_FINE_DEFAULT
    return inizio, fine


def orario_sla() -> tuple[int, int]:
    """(ora di inizio, ora di fine) della giornata lavorativa per gli SLA."""
    valore = cache.get(_CACHE_ORARIO)
    if valore is None:
        valore = _leggi_orario()
        cache.set(_CACHE_ORARIO, valore, _CACHE_SECONDI)
    return tuple(valore)


def salva_orario_sla(inizio: int, fine: int) -> bool:
    """Salva l'orario; False se non valido (fine non dopo l'inizio, ore fuori 0-24)."""
    from core.models import SiteConfig

    inizio, fine = _ora(inizio, -1), _ora(fine, -1)
    if inizio < 0 or fine < 0 or fine <= inizio:
        return False
    ok = SiteConfig.set(KEY_ORA_INIZIO, str(inizio), "SLA ticket: inizio della giornata lavorativa (ora)")
    ok = SiteConfig.set(KEY_ORA_FINE, str(fine), "SLA ticket: fine della giornata lavorativa (ora)") and ok
    cache.delete(_CACHE_ORARIO)
    return ok


def categorie_sla() -> dict[str, SimpleNamespace]:
    """{codice categoria: ore SLA} per tutte le categorie, in una query ogni minuto."""
    righe = cache.get(_CACHE_CATEGORIE)
    if righe is None:
        from .models import CategoriaTicket

        righe = {}
        for codice, risposta, risoluzione in CategoriaTicket.objects.order_by("pk").values_list(
            "codice", "sla_ore_risposta", "sla_ore_risoluzione"
        ):
            righe.setdefault(codice, (risposta, risoluzione))
        cache.set(_CACHE_CATEGORIE, righe, _CACHE_SECONDI)
    return {
        codice: SimpleNamespace(sla_ore_risposta=r, sla_ore_risoluzione=s)
        for codice, (r, s) in righe.items()
    }


def svuota_cache_categorie() -> None:
    cache.delete(_CACHE_CATEGORIE)


def _festivi_anno(anno: int) -> set[date]:
    """Festivi e chiusure dell'anno, in cache cinque minuti: l'elenco dei ticket calcola
    la scadenza di ogni riga senza rileggere ogni volta impostazioni e chiusure."""
    chiave = f"tickets_sla_festivi_{anno}"
    valore = cache.get(chiave)
    if valore is None:
        from core.calendario_it import festivi_tra

        valore = festivi_tra(date(anno, 1, 1), date(anno, 12, 31))
        cache.set(chiave, valore, 300)
    return valore


def scadenza_lavorativa(inizio: datetime, ore: int, *, orario: tuple[int, int] | None = None) -> datetime:
    """Il momento in cui scadono ``ore`` ore di lavoro contate da ``inizio``.

    Contano solo le ore dentro l'orario, da lunedì a venerdì, fuori da festivi e
    chiusure aziendali. Un ticket aperto la sera o nel fine settimana comincia a
    contare dall'apertura del giorno lavorativo successivo.
    """
    from core.calendario_it import is_lavorativo

    ora_inizio, ora_fine = orario or orario_sla()
    tz = timezone.get_current_timezone()
    locale = timezone.localtime(inizio, tz)
    restante = timedelta(hours=ore)
    festivi_per_anno: dict[int, set[date]] = {}
    giorno = locale.date()
    cursore = locale
    for _ in range(_GIORNI_MAX):
        if giorno.year not in festivi_per_anno:
            festivi_per_anno[giorno.year] = _festivi_anno(giorno.year)
        if is_lavorativo(giorno, festivi_per_anno[giorno.year], sabato=False):
            apertura = timezone.make_aware(datetime.combine(giorno, time(ora_inizio % 24)), tz)
            chiusura = (timezone.make_aware(datetime.combine(giorno + timedelta(days=1), time(0)), tz)
                        if ora_fine == 24 else timezone.make_aware(datetime.combine(giorno, time(ora_fine)), tz))
            partenza = max(cursore, apertura)
            if partenza < chiusura:
                disponibile = chiusura - partenza
                if restante <= disponibile:
                    return partenza + restante
                restante -= disponibile
        giorno += timedelta(days=1)
        cursore = timezone.make_aware(datetime.combine(giorno, time(0)), tz)
    return inizio + timedelta(hours=ore)  # calendario senza giorni lavorativi: orologio continuo
