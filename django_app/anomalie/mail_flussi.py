"""Mail del modulo Anomalie dentro i flussi di Automazioni (uno per tipo di mail).

``invia(kind, msg)`` spedisce il messaggio dentro il flusso ``anomalie_mail_<kind>``:
flusso spento = la mail non parte; destinatari aggiunti/tolti, CC, oggetto e testo
del passaggio «Invia mail» valgono come per le altre mail del portale.

Ritorna (mail inviate oppure ``FERMATA`` se il flusso o una sua regola l'ha bloccata,
riga del registro già scritta). Un errore SMTP risale al chiamante come prima (ritentativi, dead-letter).
"""
from __future__ import annotations

from functools import lru_cache

from automazioni.event_notifications import ANOMALIE_MAIL_FLUSSI, codice_flusso_anomalie

FERMATA = -1


def _manda(msg, esito: dict) -> int:
    from core.email_utils import invia_con_regole_flusso

    try:
        inviate = invia_con_regole_flusso(msg)
    except Exception as exc:  # risale fuori dal flusso, che altrimenti lo inghiottirebbe
        esito["errore"] = exc
        return 0
    if not inviate:
        esito["registrata"] = True  # invia_con_regole_flusso ha già scritto «Non inviata» nel registro
        return FERMATA
    return inviate


@lru_cache(maxsize=None)
def _flusso(codice: str):
    from automazioni.managed_flows import event_flow

    return event_flow(codice, skipped_result=FERMATA)(_manda)


def invia(kind: str, msg) -> tuple[int, bool]:
    """(mail inviate o FERMATA, riga «Non inviata» già scritta nel registro)."""
    esito: dict = {}
    inviate = _flusso(codice_flusso_anomalie(kind))(msg, esito)
    if "errore" in esito:
        raise esito["errore"]
    return inviate, bool(esito.get("registrata"))


def codici() -> list[str]:
    return [codice_flusso_anomalie(k) for k, *_ in ANOMALIE_MAIL_FLUSSI]
