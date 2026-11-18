"""Campanella dalle mail delle regole: chi riceve la mail di una regola trova anche la notifica nell'HUB.

Vale per le sorgenti che non creano già la notifica da sé (ticket e assenze); per le altre
una regola la chiede con ``"campanella": true`` nella configurazione dell'azione «Invia mail»,
e ``"campanella": false`` la spegne. Solo i destinatari diretti (``to``), mai copia e ccn.
Una notifica uguale (stessa persona, stesso link) negli ultimi minuti non si ripete: copre
le mail che partono insieme all'avviso già creato dal modulo.
"""
from __future__ import annotations

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

SORGENTI_PREDEFINITE = {"tickets": "ticket_avviso", "assenze": "assenze_avviso"}
# Richieste di approvazione (azione «Chiedi approvazione»): chi deve decidere.
TIPI_APPROVAZIONE = {"assenze": "assenza_in_attesa"}
FINESTRA_DOPPIONI = timedelta(minutes=3)


def _url(sorgente: str, payload: dict, email: str, approvazione: bool = False) -> str:
    pk = payload.get("id") or payload.get("record_id") or payload.get("pk")
    if sorgente == "tickets" and str(pk or "").isdigit():
        richiedente = str(payload.get("richiedente_email") or "").strip().lower()
        return f"/tickets/{pk}/" if email == richiedente else f"/tickets/gestione/{pk}/"
    if sorgente == "assenze":
        # Il numero della richiesta nel link: due richieste diverse non sono doppioni.
        from assenze.avvisi import url_capo, url_dipendente

        capo = str(payload.get("capo_email") or "").strip().lower()
        if approvazione or (email and email == capo):
            return url_capo(pk)
        return url_dipendente(pk)
    return ""


def da_mail(action, payload: dict, destinatari: list[str], oggetto: str, *, approvazione: bool = False) -> int:
    """Crea la notifica per i destinatari della mail appena inviata. Best effort: mai eccezioni.

    ``approvazione``: la mail chiede una decisione (Approva/Rifiuta); il link porta a dove si decide."""
    try:
        config = action.config_json if isinstance(getattr(action, "config_json", None), dict) else {}
        sorgente = str(getattr(getattr(action, "rule", None), "source_code", "") or "")
        scelta = config.get("campanella")
        if scelta is False or (scelta is not True and sorgente not in SORGENTI_PREDEFINITE):
            return 0
        from core.models import Notifica
        from core.notifiche import invia_notifica, legacy_user_ids_for_email
        from core.notifiche_meta import TIPO_META
        from django.utils import timezone

        tipo = SORGENTI_PREDEFINITE.get(sorgente, "automazione")
        if approvazione:
            tipo = TIPI_APPROVAZIONE.get(sorgente, tipo)
            oggetto = f"Da decidere: {oggetto}" if oggetto and not str(oggetto).lower().startswith("da decidere") else oggetto
        messaggio = (oggetto or "").strip()[:480] or "Nuovo avviso"
        soglia = timezone.now() - FINESTRA_DOPPIONI
        modulo = TIPO_META[tipo]["modulo"]
        tipi_modulo = [t for t, m in TIPO_META.items() if m.get("modulo") == modulo]
        creati = 0
        for email in dict.fromkeys(str(e or "").strip().lower() for e in destinatari):
            if not email:
                continue
            url = _url(sorgente, payload or {}, email, approvazione)
            for uid in legacy_user_ids_for_email(email):
                if Notifica.objects.filter(legacy_user_id=uid, url_azione=url, created_at__gte=soglia,
                                           tipo__in=tipi_modulo).exists():
                    continue
                invia_notifica(uid, tipo, messaggio, url)
                creati += 1
        return creati
    except Exception:
        logger.warning("Campanella dalla mail della regola non creata", exc_info=True)
        return 0
