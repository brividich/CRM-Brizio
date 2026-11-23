"""Calendario lavorativo unico del portale (audit K1-K3).

Festivi nazionali calcolati qui; patrono, sabato lavorativo e chiusure aziendali si
impostano una volta sola nelle **Impostazioni di Assenze** e valgono per tutti i moduli
(anomalie, attivita', specifiche, scadenzario, carichi macchina, RENTRI).

- ``festivi_aziendali(anno)``: nazionali + patrono.
- ``festivi_tra(inizio, fine)``: giorni non lavorativi dell'intervallo (festivi + chiusure);
  con ``chiusure=False`` solo i festivi, per i termini di legge (RENTRI).
- ``is_lavorativo(giorno)``: lun-ven (piu' il sabato se lavorativo) e non in ``festivi_tra``.

Le impostazioni di Assenze si leggono con import ritardato (core non dipende da un'app)
e con ripiego sui soli festivi nazionali se la lettura fallisce. Restano in memoria
per un minuto, cosi' un conteggio su molti giorni non rilegge il database a ogni giorno.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Festivi nazionali a data fissa (mese, giorno, nome).
_FESTIVI_FISSI = (
    (1, 1, "Capodanno"),
    (1, 6, "Epifania"),
    (4, 25, "Festa della Liberazione"),
    (5, 1, "Festa del Lavoro"),
    (6, 2, "Festa della Repubblica"),
    (8, 15, "Ferragosto"),
    (11, 1, "Ognissanti"),
    (12, 8, "Immacolata Concezione"),
    (12, 25, "Natale"),
    (12, 26, "Santo Stefano"),
)

_TTL_SECONDI = 60
_cache: dict = {}


def _in_cache(chiave, calcola):
    from django.conf import settings

    ttl = getattr(settings, "CALENDARIO_CACHE_SECONDI", _TTL_SECONDI)
    adesso = time.monotonic()
    voce = _cache.get(chiave)
    if ttl and voce and adesso - voce[0] < ttl:
        return voce[1]
    valore = calcola()
    _cache[chiave] = (adesso, valore)
    return valore


def svuota_cache() -> None:
    """Dopo una modifica delle impostazioni o delle chiusure (e nei test)."""
    _cache.clear()


def pasqua(anno: int) -> date:
    """Domenica di Pasqua (computus di Gauss/Meeus, calendario gregoriano)."""
    a = anno % 19
    b = anno // 100
    c = anno % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - nome dell'algoritmo
    m = (a + 11 * h + 22 * l) // 451
    mese = (h + l - 7 * m + 114) // 31
    giorno = ((h + l - 7 * m + 114) % 31) + 1
    return date(anno, mese, giorno)


def festivita_nazionali(anno: int) -> dict[date, str]:
    """Festivi nazionali dell'anno con il nome: fissi, Pasqua, Lunedi' dell'Angelo, San Francesco dal 2026."""
    out = {date(anno, mese, giorno): nome for mese, giorno, nome in _FESTIVI_FISSI}
    p = pasqua(anno)
    out[p] = "Pasqua"
    out[p + timedelta(days=1)] = "Lunedì dell'Angelo"
    if anno >= 2026:
        # Legge 151/2025: San Francesco d'Assisi torna festa nazionale dal 2026.
        out[date(anno, 10, 4)] = "San Francesco d'Assisi"
    return out


def festivi_nazionali(anno: int) -> set[date]:
    """Date dei festivi nazionali dell'anno."""
    return set(festivita_nazionali(anno))


def _impostazioni():
    def _leggi():
        try:
            from assenze.models import AssenzeImpostazioniHR

            return AssenzeImpostazioniHR.get_solo()
        except Exception:
            logger.warning("calendario: impostazioni di Assenze non leggibili, solo festivi nazionali", exc_info=True)
            return None
    return _in_cache(("imp",), _leggi)


def _patrono_legacy_scadenzario() -> tuple[int, int, str] | None:
    """Patrono scritto un tempo solo nello Scadenzario (SiteConfig «scadenzario_patrono» = "MM-GG Nome").

    Vale solo se in Assenze il patrono non e' impostato, per non perderlo nel passaggio.
    """
    try:
        from core.models import SiteConfig

        valore = (SiteConfig.get("scadenzario_patrono", "") or "").strip()
        data_txt, _, nome = valore.partition(" ")
        mese, giorno = (int(x) for x in data_txt.split("-", 1))
        date(2024, mese, giorno)
        return mese, giorno, nome.strip() or "Santo patrono"
    except Exception:
        return None


def patrono() -> tuple[int, int, str] | None:
    """(mese, giorno, nome) del patrono dalle impostazioni di Assenze, o None."""
    imp = _impostazioni()
    if imp is not None and getattr(imp, "patrono_giorno", None) and getattr(imp, "patrono_mese", None):
        nome = (getattr(imp, "patrono_nome", "") or "").strip()
        return int(imp.patrono_mese), int(imp.patrono_giorno), f"Patrono{': ' + nome if nome else ''}"
    return _in_cache(("patrono_scadenzario",), _patrono_legacy_scadenzario)


def sabato_lavorativo() -> bool:
    imp = _impostazioni()
    return bool(getattr(imp, "sabato_lavorativo", False))


def festivita_aziendali(anno: int) -> dict[date, str]:
    """Festivi nazionali + patrono, con il nome."""
    out = festivita_nazionali(anno)
    p = patrono()
    if p:
        try:
            out.setdefault(date(anno, p[0], p[1]), p[2])
        except ValueError:  # 29 febbraio negli anni non bisestili
            pass
    return out


def festivi_aziendali(anno: int) -> set[date]:
    return set(festivita_aziendali(anno))


def chiusure_tra(inizio: date, fine: date) -> dict[date, str]:
    """Giorni di chiusura aziendale (Impostazioni di Assenze) nell'intervallo, con la descrizione."""
    def _leggi():
        try:
            from assenze.models import ChiusuraAziendale

            righe = list(ChiusuraAziendale.objects.filter(data_inizio__lte=fine, data_fine__gte=inizio)
                         .values_list("data_inizio", "data_fine", "descrizione"))
        except Exception:
            logger.warning("calendario: chiusure aziendali non leggibili", exc_info=True)
            return {}
        out: dict[date, str] = {}
        for da, a, descrizione in righe:
            d = max(da, inizio)
            while d <= min(a, fine):
                out.setdefault(d, descrizione or "Chiusura aziendale")
                d += timedelta(days=1)
        return out
    return _in_cache(("chiusure", inizio, fine), _leggi)


def festivi_tra(inizio: date, fine: date, *, chiusure: bool = True) -> set[date]:
    """Giorni non lavorativi (festivi aziendali + chiusure) di tutti gli anni toccati dall'intervallo.

    ``chiusure=False``: solo festivi nazionali e patrono (termini di legge).
    """
    giorni: set[date] = set()
    for anno in range(inizio.year, fine.year + 1):
        giorni |= festivi_aziendali(anno)
    if chiusure:
        giorni |= set(chiusure_tra(date(inizio.year, 1, 1), date(fine.year, 12, 31)))
    return giorni


def is_lavorativo(giorno: date, festivi: set[date] | None = None, *, sabato: bool | None = None) -> bool:
    """Giorno lavorativo: lun-ven (piu' il sabato se lavorativo in Assenze) e non in ``festivi``.

    Senza ``festivi`` usa il calendario aziendale completo dell'anno del giorno.
    """
    if festivi is None:
        festivi = festivi_tra(giorno, giorno)
    lavora_sabato = sabato_lavorativo() if sabato is None else sabato
    settimana = giorno.weekday() < 5 or (giorno.weekday() == 5 and lavora_sabato)
    return settimana and giorno not in festivi
