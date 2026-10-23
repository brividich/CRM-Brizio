"""Eventi di sicurezza del portale verso il SOC: un canale unico.

Ogni momento del portale che il SOC deve vedere (PIN bloccato, accesso bloccato,
sessione spostata su un altro PC, impersonazione…) passa da :func:`segnala`, che
crea un ``SecurityEventRecord`` nella sorgente «Portale · accessi» e lo fa
valutare subito dal motore regole del SOC (soppressioni, alert, notifiche).

Per aggiungere un evento:

1. una riga in :data:`CATALOGO` (codice, etichetta, severità, se apre un alert);
2. la chiamata ``segnala("codice", ...)`` nel punto del portale dove succede.

Il resto è automatico: la regola generica del SOC (``security.services.rule_engine``)
apre l'alert per i tipi che lo prevedono, e ``/soc/impostazioni/`` mostra un
interruttore per ogni tipo (sezione «Eventi di sicurezza del portale»).

Regole: :func:`segnala` non solleva mai e non blocca la richiesta (il SOC può
mancare o essere giù); nel payload solo nome utente, IP e i dettagli passati,
mai segreti.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

FONTE_SOC = "Portale · accessi"


@dataclass(frozen=True)
class TipoEvento:
    codice: str
    etichetta: str
    severita: str  # valori di security.models.Severity
    alert: bool  # apre un alert nel SOC (se l'interruttore in /soc/impostazioni/ è acceso)
    descrizione: str = ""
    # False: il SOC ha una regola dedicata (rule_engine), niente interruttore generico.
    interruttore: bool = True


CATALOGO: tuple[TipoEvento, ...] = (
    TipoEvento("accesso_nuovo_dispositivo", "Accesso al portale da un dispositivo nuovo", "info", False,
               "La persona è avvisata con notifica e mail; nel SOC solo KPI.", interruttore=False),
    TipoEvento("accesso_non_riconosciuto", "Accesso al portale non riconosciuto («Non ero io»)", "high", True,
               "La persona ha premuto «Non ero io»: la sessione è chiusa.", interruttore=False),
    TipoEvento("login_bloccato", "Accesso al portale bloccato per troppe password sbagliate", "warning", True,
               "Cinque password sbagliate per lo stesso nome utente dallo stesso IP: blocco di un'ora."),
    TipoEvento("twofa_bloccato", "Verifica in due passaggi bloccata per troppi codici sbagliati", "warning", True,
               "Password giusta ma codice del secondo fattore sbagliato più volte."),
    TipoEvento("postazione_pin_bloccato", "PIN di una postazione condivisa bloccato", "warning", True,
               "Cinque PIN sbagliati di fila per la stessa persona su un PC condiviso."),
    TipoEvento("postazione_altro_pc", "Sessione di una postazione condivisa usata da un altro PC", "high", True,
               "La sessione nata su un PC condiviso è arrivata da un altro indirizzo: è stata chiusa."),
    TipoEvento("impersonazione_avviata", "Un amministratore ha iniziato a impersonare un utente", "info", False,
               "Assistenza o verifica dei permessi; resta anche nell'audit."),
)
TIPI: dict[str, TipoEvento] = {t.codice: t for t in CATALOGO}


def chiave_interruttore(codice: str) -> str:
    """Chiave dell'impostazione SOC che accende o spegne l'alert di un tipo."""
    return f"portale.alert.{codice}"


def _ip(request) -> str:
    if request is None:
        return ""
    try:
        from core.net import client_ip

        return client_ip(request) or ""
    except Exception:  # noqa: BLE001
        return ""


def _username(utente) -> str:
    if utente is None:
        return ""
    if isinstance(utente, str):
        return utente[:150]
    try:
        return utente.get_username()
    except Exception:  # noqa: BLE001
        return str(getattr(utente, "pk", "") or "")


def segnala(codice: str, *, utente=None, request=None, chiave: tuple = (), titolo: str = "",
            dettaglio: dict | None = None, extra: dict | None = None,
            finestra_minuti: int = 0, una_volta: bool = False):
    """Crea l'evento SOC ``codice`` e lo fa valutare. Ritorna l'evento, o None.

    - ``chiave``: cosa identifica la situazione (es. persona, PC). Eventi con la stessa
      chiave condividono l'alert finché è aperto. Vuota = ogni evento è a sé.
    - ``finestra_minuti``: niente evento nuovo se ce n'è già uno con la stessa chiave
      in questi minuti (anti-raffica). ``una_volta``: mai più di un evento per chiave.
    - ``titolo``: titolo dell'alert (default l'etichetta del tipo).
    - ``dettaglio``: dati utili al SOC; ``extra``: campi in cima al payload (compatibilità).
    """
    tipo = TIPI.get(codice)
    if tipo is None:
        logger.error("Evento di sicurezza sconosciuto: %s", codice)
        return None
    try:
        from security.models import SecurityEventRecord, SecuritySource, SourceType
        from security.services import soc_settings
        from security.services.dedup import make_hash
    except Exception:  # noqa: BLE001 - SOC non installato
        return None
    try:
        if not soc_settings.value("portale.eventi.attivo"):
            return None
        ora = timezone.now()
        fonte, _ = SecuritySource.objects.get_or_create(
            name=FONTE_SOC, defaults={"source_type": SourceType.API, "vendor": "novicrom"})
        parti = tuple(chiave) if chiave else (ora.isoformat(),)
        dedup = make_hash(fonte.pk, codice, *parti)
        gia = SecurityEventRecord.objects.filter(source=fonte, event_type=codice, dedup_hash=dedup)
        if una_volta and gia.exists():
            return None
        if finestra_minuti and gia.filter(occurred_at__gte=ora - timedelta(minutes=finestra_minuti)).exists():
            return None
        payload = {
            "utente": _username(utente),
            "ip": _ip(request),
            **(extra or {}),
            "evento_portale": True,
            "etichetta": tipo.etichetta,
            "titolo": (titolo or tipo.etichetta)[:250],
            "dettaglio": dettaglio or {},
            "alert_candidate": tipo.alert,
        }
        evento = SecurityEventRecord.objects.create(
            source=fonte, event_type=codice, occurred_at=ora, severity=tipo.severita,
            fingerprint=dedup, dedup_hash=dedup, payload=payload,
        )
    except Exception:  # noqa: BLE001 - il portale non si ferma per il SOC
        logger.exception("Evento di sicurezza %s non registrato", codice)
        return None
    try:
        from security.services.rule_engine import evaluate_event

        evaluate_event(evento)
    except Exception:  # noqa: BLE001 - resta da valutare: lo riprende il giro periodico
        logger.exception("Evento di sicurezza %s non valutato subito", codice)
    return evento


def collega_segnali() -> None:
    """Eventi che arrivano da librerie (axes): collegati una volta da ``CoreConfig.ready``."""
    try:
        from axes.signals import user_locked_out
    except Exception:  # noqa: BLE001
        return
    user_locked_out.connect(_al_blocco_login, dispatch_uid="core.eventi_sicurezza.login_bloccato")


def _al_blocco_login(sender, request=None, username=None, ip_address=None, **kwargs):
    # axes lo manda a ogni tentativo durante il blocco: un evento per nome utente e IP ogni ora.
    segnala("login_bloccato", utente=str(username or "")[:150], request=request,
            chiave=(str(username or "").lower(), ip_address or ""), finestra_minuti=60,
            titolo=f"Accesso al portale bloccato: {username} da {ip_address}",
            dettaglio={"ip_address": ip_address or ""})
