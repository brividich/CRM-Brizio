"""
Utilità centrali per l'invio email con layout grafico NOVICROM HUB.

Tutte le email del portale devono passare da send_hub_mail() o render_hub_email_html()
per garantire il layout grafico uniforme (core/email/base_email.html).
"""
from __future__ import annotations

import html as _html
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
    fail_silently: bool = False,
) -> int:
    """
    Invia una email con layout grafico NOVICROM HUB.

    body_html_fragment: frammento HTML del corpo (senza <html>/<body>).
                        Se omesso, body_text viene convertito automaticamente in HTML.
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
    return msg.send(fail_silently=fail_silently)
