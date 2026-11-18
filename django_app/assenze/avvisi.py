"""Campanella delle assenze: esito al dipendente, modifiche e cancellazioni a capo e dipendente.

Le mail restano dove sono (``mail_*_service`` e automazioni); qui solo l'avviso nell'HUB.
Il link porta il numero della richiesta (``?richiesta=<id>``): le notifiche di due richieste
diverse non si confondono e non si scartano a vicenda come doppioni (vedi automazioni.campanella).
Chi compie l'azione non riceve l'avviso. Best effort: mai eccezioni.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def url_dipendente(item_id=None) -> str:
    return f"/assenze/le-mie-richieste/?richiesta={item_id}" if str(item_id or "").isdigit() else "/assenze/le-mie-richieste/"


def url_capo(item_id=None) -> str:
    return f"/assenze/car/dashboard?richiesta={item_id}" if str(item_id or "").isdigit() else "/assenze/car/dashboard"


def _periodo(record: dict) -> str:
    try:
        from .mail_esito_service import _humanize_dt

        dal, al = _humanize_dt(record.get("data_inizio")), _humanize_dt(record.get("data_fine"))
    except Exception:
        return ""
    if dal and al and dal != al:
        return f"dal {dal} al {al}"
    return f"del {dal or al}" if (dal or al) else ""


def _norm(email) -> str:
    return str(email or "").strip().lower()


def _al_dipendente(record: dict, *, tipo: str, messaggio: str, autore_email: str = "") -> None:
    from core.notifiche import invia_notifica, invia_notifica_email

    email = _norm(record.get("email_esterna"))
    if "@" not in email:
        email = ""
    if email and email == _norm(autore_email):
        return
    url = url_dipendente(record.get("id"))
    try:
        utente_id = int(record.get("utente_id") or 0)
    except (TypeError, ValueError):
        utente_id = 0
    try:
        if utente_id:
            invia_notifica(utente_id, tipo, messaggio[:480], url)
        elif email:
            invia_notifica_email(email, tipo, messaggio[:480], url)
    except Exception:
        logger.warning("Assenze: campanella al dipendente non creata (id=%s)", record.get("id"), exc_info=True)


def _al_capo(record: dict, capo_email: str, *, tipo: str, messaggio: str, autore_email: str = "") -> None:
    from core.notifiche import invia_notifica_email

    capo = _norm(capo_email)
    if not capo or capo == _norm(autore_email):
        return
    try:
        invia_notifica_email(capo, tipo, messaggio[:480], url_capo(record.get("id")))
    except Exception:
        logger.warning("Assenze: campanella al capo non creata (id=%s)", record.get("id"), exc_info=True)


def esito(record: dict, *, consenso: str, tipo_display: str = "", note: str = "", deciso_da: str = "") -> None:
    approvata = consenso == "Approvato"
    cosa = (tipo_display or "assenza").strip()
    periodo = _periodo(record)
    msg = f"{cosa.capitalize()} {periodo} {'approvata' if approvata else 'rifiutata'}".replace("  ", " ").strip()
    if deciso_da:
        msg += f" da {deciso_da}"
    msg += "."
    if note and not approvata:
        msg += f" Nota: {note}"
    _al_dipendente(record, tipo="assenza_approvata" if approvata else "assenza_rifiutata", messaggio=msg)


def modificata(record: dict, *, capo_email: str, tipo_display: str = "", chi: str = "", autore_email: str = "") -> None:
    cosa = (tipo_display or "assenza").strip()
    nome = str(record.get("copia_nome") or "").strip()
    periodo = _periodo(record)
    da = f" da {chi}" if chi else ""
    _al_capo(record, capo_email, tipo="assenza_modificata", autore_email=autore_email,
             messaggio=f"{nome}: {cosa} {periodo} modificata{da}.".strip())
    _al_dipendente(record, tipo="assenza_modificata", autore_email=autore_email,
                   messaggio=f"La tua richiesta di {cosa.lower()} {periodo} è stata modificata{da}.")


def cancellata(record: dict, *, capo_email: str, tipo_display: str = "", chi: str = "", autore_email: str = "") -> None:
    cosa = (tipo_display or "assenza").strip()
    nome = str(record.get("copia_nome") or "").strip()
    periodo = _periodo(record)
    da = f" da {chi}" if chi else ""
    _al_capo(record, capo_email, tipo="assenza_cancellata", autore_email=autore_email,
             messaggio=f"{nome}: {cosa} {periodo} cancellata{da}. Non serve più decidere.".strip())
    _al_dipendente(record, tipo="assenza_cancellata", autore_email=autore_email,
                   messaggio=f"La tua richiesta di {cosa.lower()} {periodo} è stata cancellata{da}.")
