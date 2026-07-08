"""Blocchi HTML per i digest/reminder email dell'anagrafica (scadenze).

Riusa i primitivi email-safe di ``core.email_utils`` (card + badge) e aggiunge:
- :func:`scadenza_badge` — pill di stato *scaduto* (rosso) / *in scadenza* (ambra);
- :func:`digest_fragment` — sezioni titolate, ognuna con l'elenco di card; salta
  automaticamente le sezioni senza elementi.

Il contenuto (titoli sezione, testi card) è sempre escapato dai primitivi core.
"""
from __future__ import annotations

import html as _html

from core.email_utils import email_item_cards


def scadenza_badge(giorni=None, *, scaduto: bool = False,
                   label_scaduto: str = "Scaduto",
                   label_scadenza: str = "In scadenza") -> tuple[str, str]:
    """Ritorna ``(testo, tone)`` pronto per il ``badge`` di ``email_item_cards``.

    ``scaduto=True`` → tono ``danger`` (rosso); altrimenti ``warning`` (ambra).
    ``giorni`` (se noto) arricchisce il testo con i giorni scaduti/residui.
    ``label_*`` permettono l'accordo di genere per dominio (visita→"Scaduta").
    """
    if scaduto:
        if giorni is not None:
            return (f"{label_scaduto} da {abs(int(giorni))} gg", "danger")
        return (label_scaduto, "danger")
    if giorni is not None:
        return (f"{label_scadenza} · {int(giorni)} gg", "warning")
    return (label_scadenza, "warning")


def _heading(text: str) -> str:
    return (
        '<div style="margin:20px 0 10px;font-size:13px;color:#64748b;'
        'font-weight:700;text-transform:uppercase;letter-spacing:.05em;">'
        + _html.escape(str(text)) + '</div>'
    )


def digest_fragment(sezioni, *, intro: str = "") -> str:
    """Costruisce il ``body_html_fragment`` di un digest a sezioni.

    ``sezioni``: iterable di ``(heading, cards)`` dove ``cards`` è la lista di
    dict per :func:`core.email_utils.email_item_cards`. Le sezioni senza card
    sono saltate. Se non c'è alcun contenuto ritorna stringa vuota (così il
    chiamante non passa un fragment vuoto e ``send_hub_mail`` usa il testo).
    """
    parts = []
    if intro:
        parts.append(
            '<p style="margin:0 0 8px;color:#475569;font-size:15px;line-height:1.6;">'
            + _html.escape(str(intro)) + '</p>'
        )
    has_content = False
    for heading, cards in sezioni:
        cards = list(cards or [])
        if not cards:
            continue
        has_content = True
        parts.append(_heading(heading))
        parts.append(email_item_cards(cards))
    return "".join(parts) if has_content else ""
