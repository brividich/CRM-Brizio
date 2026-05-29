"""
Servizio di rendering per ApprovalEmailTemplate.

Responsabilità:
- Costruire HTML + testo email di approvazione da un template strutturato
- Generare link mailto: per modalità mail_reply / hybrid
- Fornire un context mock per preview admin
- Esporre la mailbox tecnica di default da SiteConfig

Questo modulo NON contiene logica di invio. La parte SMTP resta in services.py.
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from django.conf import settings


# ── Costanti ─────────────────────────────────────────────────────────────────

APPROVAL_MAILBOX_SITE_CONFIG_KEY = "automazioni_approval_mailbox"
APPROVAL_MAILBOX_SETTINGS_KEY = "AUTOMAZIONI_APPROVAL_MAILBOX"
APPROVAL_MAILBOX_DEFAULT = ""

# Placeholder speciali iniettati automaticamente nel contesto al momento del render
# Sono disponibili nei template di soggetto, corpo e mailto:
#   {approval_token}  — UUID univoco dell'AutomationApproval
#   {approval_id}     — PK intero dell'AutomationApproval
#   {approve_url}     — URL portale per approvare (portal_links / hybrid)
#   {reject_url}      — URL portale per rifiutare (portal_links / hybrid)

# Dati campione per preview / test (modulo assenze come caso d'uso principale)
DEMO_PAYLOAD: dict[str, Any] = {
    "id": "ABS-2026-00125",
    "dipendente_nome": "Mario Rossi",
    "dipendente_email": "mario.rossi@cnovicrom.local",
    "tipo_assenza": "Ferie",
    "data_inizio": "2026-05-05",
    "data_fine": "2026-05-09",
    "note": "Vacanza estiva",
    "reparto": "Produzione",
    "capo_email": "luigi.bianchi@cnovicrom.local",
    "approval_token": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "approval_id": "999",
    "approve_url": "#approva",
    "reject_url": "#rifiuta",
}


# ── Helpers interni ───────────────────────────────────────────────────────────

def _render(template_str: str | None, context: dict[str, Any]) -> str:
    """Rendering semplice {placeholder} — riusa la stessa logica di services.render_template_string."""
    # Import locale per evitare dipendenza circolare (services importa già questo modulo)
    from .services import render_template_string
    return render_template_string(template_str, context)


def _parse_facts_lines(facts_lines: str, context: dict[str, Any]) -> list[dict[str, str]]:
    """Parsa righe 'Etichetta | {placeholder}' e le rende nel contesto."""
    facts: list[dict[str, str]] = []
    for raw_line in facts_lines.splitlines():
        line = raw_line.strip()
        if not line or "|" not in line:
            continue
        label, value_tpl = line.split("|", 1)
        label = label.strip()
        if not label:
            continue
        facts.append({
            "name": label,
            "value": _render(value_tpl.strip(), context),
        })
    return facts


def _escape_html(text: str) -> str:
    """Escape minimo per inserimento in HTML."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_facts_html(facts: list[dict[str, str]]) -> str:
    if not facts:
        return ""
    rows = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#475569;white-space:nowrap;'
        f'vertical-align:top;">{_escape_html(f["name"])}</td>'
        f'<td style="padding:6px 0 6px 12px;color:#0f172a;">{_escape_html(f["value"])}</td></tr>'
        for f in facts
    )
    return (
        '<table style="border-collapse:collapse;width:100%;margin:12px 0;">'
        f"{rows}"
        "</table>"
    )


def _button_html(label: str, url: str, color: str) -> str:
    return (
        f'<a href="{url}" class="ecta" style="display:inline-block;padding:12px 22px;background:{color};'
        f'color:#ffffff;text-decoration:none;border-radius:9px;font-size:14px;font-weight:800;'
        f'margin:0 10px 10px 0;">'
        f"{_escape_html(label)}</a>"
    )


def _mailto_url(mailbox: str, subject: str, body: str) -> str:
    params = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    return f"mailto:{mailbox}?{params}"


# ── Mailbox tecnica ───────────────────────────────────────────────────────────

def get_default_approval_mailbox() -> str:
    """
    Risolve la mailbox tecnica di default nell'ordine:
    1. SiteConfig (chiave automazioni_approval_mailbox)
    2. settings.AUTOMAZIONI_APPROVAL_MAILBOX
    3. stringa vuota
    """
    try:
        from core.models import SiteConfig
        val = SiteConfig.get_many({APPROVAL_MAILBOX_SITE_CONFIG_KEY: APPROVAL_MAILBOX_DEFAULT}).get(
            APPROVAL_MAILBOX_SITE_CONFIG_KEY, ""
        )
        if val:
            return str(val).strip()
    except Exception:
        pass
    return str(getattr(settings, APPROVAL_MAILBOX_SETTINGS_KEY, "") or "").strip()


def resolve_mailto_mailbox(template: Any) -> str:
    """Risolve la mailbox per un template: template.mailto_mailbox > default globale."""
    template_mailbox = str(getattr(template, "mailto_mailbox", "") or "").strip()
    return template_mailbox or get_default_approval_mailbox()


# ── Rendering pubblico ────────────────────────────────────────────────────────

def build_template_context(
    payload_context: dict[str, Any],
    *,
    approval: Any = None,
    approve_url: str = "",
    reject_url: str = "",
) -> dict[str, Any]:
    """
    Costruisce il context finale per il rendering del template.
    Inietta le chiavi speciali approvazione sopra il payload originale.
    """
    ctx: dict[str, Any] = dict(payload_context)
    if approval is not None:
        ctx["approval_token"] = str(getattr(approval, "token", "") or "")
        ctx["approval_id"] = str(getattr(approval, "pk", "") or "")
    ctx.setdefault("approve_url", approve_url)
    ctx.setdefault("reject_url", reject_url)
    return ctx


def build_mailto_approve_link(template: Any, context: dict[str, Any]) -> str:
    mailbox = resolve_mailto_mailbox(template)
    if not mailbox:
        return ""
    subject = _render(template.approval_mailto_subject_template or "CMD APPROVO RID {approval_token}", context)
    body = _render(template.approval_mailto_body_template or "CMD: APPROVO\nRID: {approval_token}", context)
    return _mailto_url(mailbox, subject, body)


def build_mailto_reject_link(template: Any, context: dict[str, Any]) -> str:
    mailbox = resolve_mailto_mailbox(template)
    if not mailbox:
        return ""
    subject = _render(template.rejection_mailto_subject_template or "CMD RIFIUTO RID {approval_token}", context)
    body = _render(template.rejection_mailto_body_template or "CMD: RIFIUTO\nRID: {approval_token}\nMOTIVO: ", context)
    return _mailto_url(mailbox, subject, body)


def render_approval_email(
    template: Any,
    context: dict[str, Any],
    *,
    approve_url: str = "",
    reject_url: str = "",
) -> dict[str, str]:
    """
    Renderizza il template e ritorna un dict con:
      subject    — oggetto email
      html_body  — corpo HTML completo
      text_body  — fallback testo

    Parametri:
      template     — istanza ApprovalEmailTemplate
      context      — dict payload già arricchito (inclusi approval_token, approval_id, approve_url, reject_url)
      approve_url  — URL portale approvazione (per portal_links / hybrid)
      reject_url   — URL portale rifiuto (per portal_links / hybrid)
    """
    ctx = dict(context)
    ctx.setdefault("approve_url", approve_url)
    ctx.setdefault("reject_url", reject_url)

    subject = _render(template.subject_template, ctx) or "Richiesta di approvazione"
    approval_label = str(template.approval_label or "Approva")
    rejection_label = str(template.rejection_label or "Rifiuta")

    # ── Sezione CTA ──────────────────────────────────────────────────────────
    portal_cta_html = ""
    portal_cta_text = ""
    mailto_cta_html = ""
    mailto_cta_text = ""

    if template.uses_portal_links() and approve_url and reject_url:
        portal_cta_html = (
            _button_html(approval_label, approve_url, "#16a34a")
            + _button_html(rejection_label, reject_url, "#dc2626")
        )
        portal_cta_text = (
            f"{approval_label}: {approve_url}\n"
            f"{rejection_label}: {reject_url}\n"
        )

    if template.uses_mailto() and template.include_mailto_actions:
        mailto_approve = build_mailto_approve_link(template, ctx)
        mailto_reject = build_mailto_reject_link(template, ctx)
        if mailto_approve:
            mailto_cta_html += _button_html(f"{approval_label} (email)", mailto_approve, "#0f766e")
            mailto_cta_text += f"{approval_label} (email): {mailto_approve}\n"
        if mailto_reject:
            mailto_cta_html += _button_html(f"{rejection_label} (email)", mailto_reject, "#9f1239")
            mailto_cta_text += f"{rejection_label} (email): {mailto_reject}\n"

    # ── Corpo ─────────────────────────────────────────────────────────────────
    title = _render(template.title_template, ctx)

    if template.body_template:
        # Corpo libero: l'admin ha scritto HTML custom
        inner_html = _render(template.body_template, ctx)
    else:
        parts_html: list[str] = []
        parts_text: list[str] = []

        intro = _render(template.intro_template, ctx)
        if intro:
            parts_html.append(f'<p style="color:#334155;line-height:1.6;">{_escape_html(intro)}</p>')
            parts_text.append(intro + "\n")

        if template.include_facts and template.facts_lines:
            facts = _parse_facts_lines(template.facts_lines, ctx)
            if facts:
                parts_html.append(_build_facts_html(facts))
                parts_text.extend(f"{f['name']}: {f['value']}" for f in facts)
                parts_text.append("")

        inner_html = "\n".join(parts_html)

    # ── Assemblaggio HTML completo via base template ──────────────────────────
    all_cta_html = ""
    if portal_cta_html or mailto_cta_html:
        all_cta_html = portal_cta_html + mailto_cta_html

    expires_at = ctx.get("expires_at")
    expires_html = ""
    expires_text = ""
    if expires_at:
        expires_label = str(expires_at)
        expires_html = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;">'
            f'<tr><td style="padding:14px 16px;border-left:4px solid #d69e2e;background:#fffaf0;border-radius:10px;'
            f'color:#6b4f0f;font-size:13px;line-height:1.55;">'
            f'La richiesta scade il <strong>{_escape_html(expires_label)}</strong>.'
            f'</td></tr></table>'
        )
        expires_text = f"\nScade il: {expires_label}"

    from django.template.loader import render_to_string
    from django.utils.safestring import mark_safe

    section_label = str(getattr(template, "section_label", "") or "").strip() or "Workflow approvazione"
    email_type = str(getattr(template, "email_type_label", "") or "").strip() or "Automazioni"

    html_body = render_to_string("core/email/base_email.html", {
        "email_type": email_type,
        "badge": "Richiede azione",
        "section_label": section_label,
        "title": title,
        "body_content": mark_safe(inner_html),
        "expires_html": mark_safe(expires_html),
        "cta_buttons": mark_safe(all_cta_html),
        "footer_note": "Messaggio automatico generato da NOVICROM HUB. Non rispondere direttamente a questa email.",
    })

    # ── Testo plain ───────────────────────────────────────────────────────────
    text_parts: list[str] = []
    if title:
        text_parts.append(title)
        text_parts.append("=" * len(title))
    if template.body_template:
        # Strip HTML tags approssimativo per il testo plain
        import re
        text_parts.append(re.sub(r"<[^>]+>", "", _render(template.body_template, ctx)))
    else:
        if template.intro_template:
            text_parts.append(_render(template.intro_template, ctx))
        if template.include_facts and template.facts_lines:
            for f in _parse_facts_lines(template.facts_lines, ctx):
                text_parts.append(f"{f['name']}: {f['value']}")
    text_parts.append("")
    if portal_cta_text:
        text_parts.append(portal_cta_text)
    if mailto_cta_text:
        text_parts.append(mailto_cta_text)
    text_parts.append(expires_text)

    text_body = "\n".join(text_parts).strip()

    return {
        "subject": subject,
        "html_body": html_body,
        "text_body": text_body,
    }


def render_approval_email_preview(template: Any, payload: dict[str, Any] | None = None) -> dict[str, str]:
    """
    Rendering preview con dati mock o payload personalizzato.
    Usato dalla view admin per la preview live.
    """
    ctx = {**DEMO_PAYLOAD, **(payload or {})}
    return render_approval_email(
        template,
        ctx,
        approve_url=ctx.get("approve_url", "#approva"),
        reject_url=ctx.get("reject_url", "#rifiuta"),
    )


def find_unresolved_placeholders(rendered: str) -> list[str]:
    """
    Identifica placeholder {campo} non risolti nel testo renderizzato.
    Utile nella preview per segnalare campi mancanti.
    """
    import re
    pattern = re.compile(r"\{([^{}]+)\}")
    return list(dict.fromkeys(m.group(1) for m in pattern.finditer(rendered)))
