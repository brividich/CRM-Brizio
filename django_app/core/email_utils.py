"""
Utilità centrali per l'invio email con layout grafico NOVICROM HUB.

Tutte le email del portale devono passare da send_hub_mail() o render_hub_email_html()
per garantire il layout grafico uniforme (core/email/base_email.html).
"""
from __future__ import annotations

import html as _html
import re as _re
from typing import Sequence

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe


def render_hub_email_html(
    body_content_html: str,
    *,
    title: str = "",
    email_type: str = "Portale",
    badge: str = "",
    section_label: str = "",
    expires_html: str = "",
    cta_buttons: str = "",
    footer_note: str = "",
    preheader: str = "",
) -> str:
    """Renderizza il layout grafico base attorno a un frammento HTML."""
    return render_to_string("core/email/base_email.html", {
        "email_type": email_type,
        "badge": badge,
        "section_label": section_label,
        "title": title,
        "body_content": mark_safe(body_content_html),
        "expires_html": mark_safe(expires_html),
        "cta_buttons": mark_safe(cta_buttons),
        "footer_note": footer_note,
        "preheader": preheader,
    })


def text_to_html(text: str) -> str:
    """Converte plain text in un paragrafo HTML sicuro (escape + newline → <br>)."""
    return (
        f'<p style="color:#475569;font-size:15px;line-height:1.7;">'
        f'{_html.escape(text).replace(chr(10), "<br>")}'
        f'</p>'
    )


# ---------------------------------------------------------------------------
# Blocchi-contenuto riusabili per il corpo email (body_html_fragment)
#
# Tutti restituiscono frammenti HTML *email-safe*: solo tabelle + inline style,
# palette del frame NOVICROM HUB, contenuto utente sempre escapato. Da comporre
# e passare a ``send_hub_mail(..., body_html_fragment=...)``. Riproducono lo
# stile delle email di anomalie (card con barra laterale, pill di stato, tabella
# fatti, CTA) senza dipendere da <style>/CSS esterno (non supportato dai client).
# ---------------------------------------------------------------------------

# Toni pill: (background, foreground). Palette coerente col frame.
_BADGE_TONES = {
    "neutral": ("#f1f5f9", "#475569"),
    "info": ("#dbeafe", "#1e40af"),
    "success": ("#dcfce7", "#166534"),
    "warning": ("#fef3c7", "#92400e"),
    "danger": ("#fee2e2", "#991b1b"),
}


def email_badge(text: str, tone: str = "neutral") -> str:
    """Pill di stato inline. ``tone`` in neutral/info/success/warning/danger
    (sconosciuto → neutral). Il testo è escapato."""
    bg, fg = _BADGE_TONES.get(tone, _BADGE_TONES["neutral"])
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-size:11px;font-weight:700;border-radius:999px;padding:3px 9px;'
        f'line-height:1.4;">{_html.escape(str(text))}</span>'
    )


def email_facts_table(rows: Sequence[tuple[str, str]]) -> str:
    """Tabella "etichetta → valore" email-safe dentro un box arrotondato.

    ``rows``: sequenza di ``(etichetta, valore)``. Etichette e valori sono
    escapati. Ritorna stringa vuota se non ci sono righe.
    """
    rows = list(rows or [])
    if not rows:
        return ""
    cells = "".join(
        '<tr>'
        '<td style="padding:6px 14px 6px 0;font-size:13px;color:#64748b;'
        'vertical-align:top;white-space:nowrap;">' + _html.escape(str(label)) + '</td>'
        '<td style="padding:6px 0;font-size:14px;color:#182232;font-weight:600;'
        'vertical-align:top;">' + _html.escape(str(value)) + '</td>'
        '</tr>'
        for label, value in rows
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="width:100%;border-collapse:collapse;background:#f8fafc;'
        'border:1px solid #e2e8f0;border-radius:10px;">'
        '<tr><td style="padding:10px 16px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="width:100%;border-collapse:collapse;">' + cells + '</table>'
        '</td></tr></table>'
    )


def email_cta(label: str, url: str, note: str = "") -> str:
    """Bottone CTA coerente col frame + eventuale nota. ``url`` è escapato come
    attributo; ``label`` e ``note`` sono escapati come testo."""
    safe_url = _html.escape(str(url), quote=True)
    note_html = ""
    if note:
        note_html = (
            '<p style="margin:14px 0 0;font-size:12px;color:#94a3b8;'
            'line-height:1.5;word-break:break-all;">' + _html.escape(str(note)) + '</p>'
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="border-collapse:collapse;">'
        '<tr><td style="border-radius:10px;background:#12395f;">'
        f'<a href="{safe_url}" style="display:inline-block;padding:14px 32px;'
        'font-size:15px;font-weight:700;color:#ffffff;text-decoration:none;'
        'border-radius:10px;background:#12395f;mso-padding-alt:14px 32px;">'
        + _html.escape(str(label)) +
        '</a></td></tr></table>' + note_html
    )


def _safe_accent(color: str) -> str:
    """Sanifica il colore della barra laterale (non è contenuto utente, ma
    difendiamo il context CSS): solo hex/nome semplice, altrimenti default."""
    color = str(color or "")
    return color if _re.fullmatch(r"#?[0-9a-zA-Z]{3,20}", color) else "#1f5c91"


def email_item_cards(items: Sequence[dict]) -> str:
    """Elenco di card in stile anomalie (barra laterale colorata + contenuto).

    Ogni ``item`` è un dict con chiavi:
      - ``title`` (obbligatoria)
      - ``subtitle`` (opz.)
      - ``badge`` (opz.): stringa (pill neutra), tupla ``(text, tone)`` o dict
        ``{"text":.., "tone":..}``
      - ``note`` (opz.)
      - ``accent`` (opz.): colore barra laterale (default ``#1f5c91``)
    Titolo/sottotitolo/nota sono escapati. Ritorna "" se la lista è vuota.
    """
    items = list(items or [])
    if not items:
        return ""
    cards = []
    for it in items:
        parts = [
            '<div style="font-size:15px;color:#182232;font-weight:600;'
            'line-height:1.4;">' + _html.escape(str(it.get("title", ""))) + '</div>'
        ]
        subtitle = it.get("subtitle")
        if subtitle:
            parts.append(
                '<div style="margin-top:3px;font-size:13px;color:#64748b;">'
                + _html.escape(str(subtitle)) + '</div>'
            )
        badge = it.get("badge")
        if badge is not None and badge != "":
            if isinstance(badge, (tuple, list)) and len(badge) == 2:
                badge_html = email_badge(badge[0], badge[1])
            elif isinstance(badge, dict):
                badge_html = email_badge(badge.get("text", ""), badge.get("tone", "neutral"))
            else:
                badge_html = email_badge(str(badge), "neutral")
            parts.append('<div style="margin-top:8px;">' + badge_html + '</div>')
        note = it.get("note")
        if note:
            parts.append(
                '<div style="margin-top:8px;font-size:13px;color:#64748b;'
                'font-style:italic;">' + _html.escape(str(note)) + '</div>'
            )
        accent = _safe_accent(it.get("accent"))
        cards.append(
            '<tr><td style="padding:0 0 10px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="width:100%;border-collapse:collapse;background:#f8fafc;'
            'border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;">'
            '<tr>'
            f'<td style="width:6px;background:{accent};border-radius:10px 0 0 10px;">&nbsp;</td>'
            '<td style="padding:14px 16px;">' + "".join(parts) + '</td>'
            '</tr></table></td></tr>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="width:100%;border-collapse:collapse;">' + "".join(cards) + '</table>'
    )


def send_hub_mail(
    subject: str,
    body_text: str,
    recipients: list[str] | Sequence[str],
    *,
    title: str = "",
    email_type: str = "Portale",
    badge: str = "",
    section_label: str = "",
    body_html_fragment: str = "",
    footer_note: str = "",
    preheader: str = "",
    from_email: str | None = None,
    connection=None,
    attachments: list | None = None,
    fail_silently: bool = False,
) -> int:
    """
    Invia una email con layout grafico NOVICROM HUB.

    body_html_fragment: frammento HTML del corpo (senza <html>/<body>).
                        Se omesso, body_text viene convertito automaticamente in HTML.
    attachments: lista opzionale di tuple ``(filename, content, mimetype)`` allegate
                 al messaggio (es. un invito calendario .ics).
    """
    if not from_email:
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or None

    fragment = body_html_fragment or text_to_html(body_text)
    html_body = render_hub_email_html(
        fragment,
        title=title,
        email_type=email_type,
        badge=badge,
        section_label=section_label,
        footer_note=footer_note,
        preheader=preheader,
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=from_email,
        to=list(recipients),
        connection=connection,
    )
    msg.attach_alternative(html_body, "text/html")
    for att in (attachments or []):
        try:
            filename, content, mimetype = att
            msg.attach(filename, content, mimetype)
        except Exception:
            pass
    return msg.send(fail_silently=fail_silently)
