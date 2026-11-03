"""Riga «Certificato arrivato: Sì/No» nelle mail delle richieste di Malattia.

Le mail delle regole automazioni (avviso e approvazione) hanno il testo salvato
nella regola: la riga si aggiunge qui, in testa al corpo, cosi' vale per tutte
le regole senza toccarne i testi. Best-effort: un errore non blocca la mail.
"""
from __future__ import annotations

import html
import logging

logger = logging.getLogger(__name__)

ETICHETTA = "Certificato arrivato"


def _valore(payload: dict) -> tuple[str, object] | None:
    """(tipo, certificato) dal payload; se manca qualcosa li legge dalla richiesta."""
    tipo = payload.get("tipo_assenza")
    if tipo not in (None, "") and "certificato_medico" in payload:
        return str(tipo), payload.get("certificato_medico")
    try:
        item_id = int(payload.get("id"))
    except (TypeError, ValueError):
        return (str(tipo), None) if tipo not in (None, "") else None
    from .views import _helpers

    row = _helpers._get_assenza(item_id) or {}
    return str(tipo or row.get("tipo_assenza") or ""), row.get("certificato_medico")


def certificato_arrivato(tipo, valore) -> bool | None:
    """True/False per la Malattia, None per gli altri tipi."""
    from .views import _helpers

    if _helpers._norm_tipo(tipo) != "Malattia":
        return None
    return bool(_helpers._certificato_medico_for_tipo(tipo, valore))


def etichetta_si_no(arrivato: bool) -> str:
    return "Sì" if arrivato else "No"


def blocco_mail(source_code, payload) -> tuple[str, str]:
    """(testo, html) da mettere in testa alle mail; vuoti se non è una Malattia."""
    if str(source_code or "") != "assenze" or not isinstance(payload, dict):
        return "", ""
    try:
        dati = _valore(payload)
        if dati is None:
            return "", ""
        arrivato = certificato_arrivato(*dati)
    except Exception:
        logger.warning("assenze: stato del certificato medico non letto", exc_info=True)
        return "", ""
    if arrivato is None:
        return "", ""
    riga = f"{ETICHETTA}: {etichetta_si_no(arrivato)}"
    colore, sfondo, testo = ("#15803d", "#f0fdf4", "#14532d") if arrivato else ("#b45309", "#fffbeb", "#78350f")
    html_blocco = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="width:100%;border-collapse:collapse;margin:0 0 16px;">'
        f'<tr><td style="padding:12px 16px;border-left:4px solid {colore};background:{sfondo};border-radius:10px;'
        f'color:{testo};font-size:14px;line-height:1.6;">'
        f"<strong>{html.escape(riga)}</strong>"
        "</td></tr></table>"
    )
    return f"{riga}\n\n", html_blocco
