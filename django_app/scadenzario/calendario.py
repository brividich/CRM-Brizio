"""Servizi della pagina ``/scadenze`` (calendario): festività, presa in carico,
«solo le mie», viste salvate e fotografia giornaliera per l'andamento.

Le viste stanno in ``dashboard/views_scadenze.py`` (pagina) e
``scadenzario/views_calendario.py`` (azioni in POST).
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Festività italiane (+ patrono da SiteConfig «scadenzario_patrono» = "MM-GG Nome")
# ---------------------------------------------------------------------------

_FESTE_FISSE = (
    (1, 1, "Capodanno"), (1, 6, "Epifania"), (4, 25, "Liberazione"), (5, 1, "Festa del lavoro"),
    (6, 2, "Festa della Repubblica"), (8, 15, "Ferragosto"), (11, 1, "Ognissanti"),
    (12, 8, "Immacolata"), (12, 25, "Natale"), (12, 26, "Santo Stefano"),
)
CHIAVE_PATRONO = "scadenzario_patrono"


def pasqua(anno: int) -> date:
    """Domenica di Pasqua (calendario gregoriano, algoritmo di Meeus/Butcher)."""
    a, b, c = anno % 19, anno // 100, anno % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mese = (h + m - 7 * n + 114) // 31
    giorno = (h + m - 7 * n + 114) % 31 + 1
    return date(anno, mese, giorno)


def _patrono() -> tuple[int, int, str] | None:
    try:
        from core.models import SiteConfig

        valore = (SiteConfig.get(CHIAVE_PATRONO, "") or "").strip()
    except Exception:
        return None
    if not valore:
        return None
    data, _, nome = valore.partition(" ")
    try:
        mese, giorno = (int(x) for x in data.split("-", 1))
        date(2024, mese, giorno)  # anno bisestile: valida anche il 29 febbraio
    except (ValueError, TypeError):
        logger.warning("scadenzario: %s non valido (atteso «MM-GG Nome»)", CHIAVE_PATRONO)
        return None
    return mese, giorno, nome.strip() or "Santo patrono"


def festivi(anni) -> dict[date, str]:
    """Giorni festivi degli anni indicati: data → nome."""
    patrono = _patrono()
    esito: dict[date, str] = {}
    for anno in sorted(set(anni)):
        for mese, giorno, nome in _FESTE_FISSE:
            esito[date(anno, mese, giorno)] = nome
        p = pasqua(anno)
        esito.setdefault(p, "Pasqua")
        esito.setdefault(p + timedelta(days=1), "Lunedì dell'Angelo")
        if patrono:
            try:
                esito.setdefault(date(anno, patrono[0], patrono[1]), patrono[2])
            except ValueError:  # 29 febbraio negli anni non bisestili
                pass
    return esito


def non_lavorativo(giorno: date | None, feste: dict[date, str]) -> str:
    """«domenica», «sabato» o il nome della festa; vuoto nei giorni lavorativi."""
    if not giorno:
        return ""
    if giorno in feste:
        return feste[giorno]
    if giorno.weekday() == 6:
        return "domenica"
    if giorno.weekday() == 5:
        return "sabato"
    return ""


# ---------------------------------------------------------------------------
# Identità della singola scadenza e presa in carico
# ---------------------------------------------------------------------------

def chiave_scadenza(v) -> str:
    """Impronta stabile di una scadenza: fonte, tipo, elemento, link e data.

    Soggetto e titolo distinguono voci altrimenti uguali (stesso corso e stessa data per
    due persone, due FIR dello stesso giorno). Le generiche hanno già l'attività in
    ``elemento``: rinominarle non deve far decadere la presa in carico.
    """
    parti = [v.source or "", v.kind or "", v.elemento or "", v.url or "",
             v.data_scadenza.isoformat() if v.data_scadenza else ""]
    if v.source != "generiche":
        parti += [v.soggetto or "", v.titolo or ""]
    base = "|".join(parti)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def descrizione_scadenza(v) -> str:
    data = v.data_scadenza.strftime("%d/%m/%Y") if v.data_scadenza else ""
    return f"{v.source_label} · {v.kind_label}: {v.soggetto} — {v.titolo} ({data})"[:400]


def prese_in_carico(chiavi) -> dict:
    from .models import PresaInCarico

    chiavi = [c for c in set(chiavi) if c]
    if not chiavi:
        return {}
    esito = {}
    for i in range(0, len(chiavi), 500):  # SQL Server: niente IN con migliaia di parametri
        for p in PresaInCarico.objects.select_related("utente", "fornitore").filter(chiave__in=chiavi[i:i + 500]):
            esito[p.chiave] = p
    return esito


def nome_utente(user) -> str:
    if not user:
        return ""
    return (user.get_full_name() or "").strip() or user.get_username()


# ---------------------------------------------------------------------------
# «Solo le mie»: le scadenze che riguardano chi guarda
# ---------------------------------------------------------------------------

def chiavi_persona_di(request) -> set[str]:
    """Nominativi di chi guarda (utente del portale e anagrafica), normalizzati
    con la stessa regola dei confronti per nome dei fornitori."""
    from fornitori.nomi import chiave_persona

    user = getattr(request, "user", None)
    nomi = {(user.get_full_name() or "") if user else ""}
    try:
        from core.legacy_models import AnagraficaDipendente

        from .visibilita import identita_di

        legacy_id = identita_di(request).legacy_user_id
        if legacy_id:
            for nome, cognome in AnagraficaDipendente.objects.filter(utente_id=int(legacy_id)).values_list("nome", "cognome"):
                nomi.add(f"{nome or ''} {cognome or ''}")
    except Exception:
        logger.warning("scadenzario: anagrafica di chi guarda non leggibile", exc_info=True)
    return {k for k in (chiave_persona(n) for n in nomi) if k}


def e_mia(v, *, user_id, chiavi_persona: set[str]) -> bool:
    from fornitori.nomi import chiave_persona

    presa = getattr(v, "presa", None)
    if presa is not None and user_id and (
        presa.utente_id == user_id or (presa.fornitore_id and presa.assegnato_da_id == user_id)
    ):
        return True  # in carico a me, o affidata da me a un fornitore esterno
    extra = v.extra or {}
    if user_id and user_id in (extra.get("responsabile_id"), extra.get("utente_id")):
        return True
    if not chiavi_persona:
        return False
    return any(chiave_persona(t) in chiavi_persona for t in (v.soggetto, v.titolo) if t)


# ---------------------------------------------------------------------------
# Viste salvate
# ---------------------------------------------------------------------------

PARAMETRI_VISTA = ("vista", "sorgente", "stato", "reparto", "q", "mie")


def pulisci_parametri(querystring: str) -> str:
    """Solo i filtri (niente mese, pagina, schermo intero o export)."""
    coppie = [(k, v[:80]) for k, v in parse_qsl(querystring or "", keep_blank_values=False)
              if k in PARAMETRI_VISTA and v]
    return urlencode(coppie[:60])


# ---------------------------------------------------------------------------
# Fotografia giornaliera (andamento)
# ---------------------------------------------------------------------------

def scatta_foto(oggi: date | None = None) -> dict:
    """Numeri di oggi per fonte, sulla raccolta di sistema (tutte le voci accese
    nel pannello, senza permessi di chi guarda). Rilanciabile: sovrascrive il giorno."""
    from django.db import transaction
    from django.utils import timezone

    from dashboard.scadenze_providers import ORIZZONTE_GIORNI, PROVIDERS, collect_sistema

    from .models import FotoScadenze
    from .visibilita import Configurazione, chiavi_voce

    oggi = oggi or timezone.localdate()
    conf = Configurazione.carica()
    conta = defaultdict(lambda: [0, 0, 0])
    for v in collect_sistema(oggi=oggi):
        if v.giorni is None or v.giorni > ORIZZONTE_GIORNI or not conf.attiva(chiavi_voce(v)):
            continue
        riga = conta[v.source]
        riga[2] += 1
        if v.giorni < 0:
            riga[0] += 1
        elif v.giorni <= 30:
            riga[1] += 1
    with transaction.atomic():
        FotoScadenze.objects.filter(data=oggi).delete()
        for fonte in PROVIDERS:
            s, e, t = conta.get(fonte, (0, 0, 0))
            FotoScadenze.objects.create(data=oggi, fonte=fonte, scadute=s, entro_30=e, totale=t)
    return {"data": oggi.isoformat(), "fonti": len(PROVIDERS), "scadute": sum(r[0] for r in conta.values())}
