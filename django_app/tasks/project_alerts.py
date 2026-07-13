"""Alert automazioni sul progetto KICK-OFF (impatto sicurezza, VRF non caricato).

Destinatari dinamici (PM/capo commessa) risolti in Python: il `send_email` generico
del motore non può leggere le email dai FK utente. Riusa il layout email HUB.
"""
from __future__ import annotations


def project_recipients(project) -> list[str]:
    """Email di PM e capo commessa del progetto (deduplicate)."""
    emails: list[str] = []
    for user in (getattr(project, "project_manager", None), getattr(project, "capo_commessa", None)):
        if user is None:
            continue
        email = (getattr(user, "email", "") or "").strip()
        if email and email not in emails:
            emails.append(email)
    return emails


def _split_extra(extra_to) -> list[str]:
    if not extra_to:
        return []
    if isinstance(extra_to, (list, tuple)):
        items = extra_to
    else:
        items = str(extra_to).replace(";", ",").split(",")
    return [e.strip() for e in items if e and "@" in str(e)]


def _kickoff(project) -> str:
    return str(getattr(project, "kickoff_number", "") or "")


def build_safety_alert(project) -> tuple[str, str, str]:
    from core.email_utils import email_facts_table, text_to_html

    n = _kickoff(project)
    subject = f"⚠️ Impatto sicurezza — KICK-OFF {n}: {project.name}"
    facts = [
        ("KICK-OFF", n),
        ("Progetto", project.name or "—"),
        ("Part number", (getattr(project, "part_number", "") or "—") or "—"),
        ("Cliente", (getattr(project, "client_name", "") or "—") or "—"),
        ("Fase", getattr(project, "get_phase_display", lambda: getattr(project, "phase", ""))()),
    ]
    intro = (
        "Questo KICK-OFF è stato marcato con <b>impatto sulla sicurezza</b>. "
        "Verificare requisiti DPI, valutazione rischi (VRF/MOD.073) e coinvolgimento RSPP/preposto."
    )
    html = f"<p>{intro}</p>" + email_facts_table(facts)
    text = "Impatto sulla sicurezza sul KICK-OFF.\n" + "\n".join(f"{k}: {v}" for k, v in facts)
    return subject, text, html


def build_vrf_pending_alert(project) -> tuple[str, str, str]:
    from core.email_utils import email_facts_table

    n = _kickoff(project)
    subject = f"VRF non ancora caricato — KICK-OFF {n}: {project.name}"
    vrf_disp = getattr(project, "get_vrf_status_display", lambda: getattr(project, "vrf_status", ""))()
    facts = [
        ("KICK-OFF", n),
        ("Progetto", project.name or "—"),
        ("Fase", getattr(project, "get_phase_display", lambda: getattr(project, "phase", ""))()),
        ("Stato VRF", vrf_disp),
    ]
    intro = (
        "Il progetto sta andando in <b>esecuzione</b> ma il documento <b>VRF (MOD.073)</b> "
        "non risulta ancora caricato. Caricare/approvare il VRF prima di avviare i lavori."
    )
    html = f"<p>{intro}</p>" + email_facts_table(facts)
    text = "VRF non caricato mentre il progetto va in esecuzione.\n" + "\n".join(f"{k}: {v}" for k, v in facts)
    return subject, text, html


_BUILDERS = {
    "safety": build_safety_alert,
    "vrf_pending": build_vrf_pending_alert,
}


def send_project_alert(project, kind: str, *, extra_to=None) -> dict:
    """Invia l'alert di progetto (kind = 'safety' | 'vrf_pending') a PM/capo commessa + extra_to."""
    builder = _BUILDERS.get(kind)
    if builder is None:
        return {"sent": False, "recipients": [], "reason": "unknown_kind"}

    recipients: list[str] = []
    for email in project_recipients(project) + _split_extra(extra_to):
        if email not in recipients:
            recipients.append(email)
    if not recipients:
        return {"sent": False, "recipients": [], "reason": "no_recipients"}

    from core.email_utils import send_hub_mail

    subject, body_text, body_html = builder(project)
    sent = send_hub_mail(
        subject,
        body_text,
        recipients,
        title=f"KICK-OFF {_kickoff(project)}",
        email_type="VRF - KICK-OFF",
        body_html_fragment=body_html,
        fail_silently=False,
    )
    if not sent:
        return {"sent": False, "recipients": recipients, "reason": "send_error"}
    return {"sent": True, "recipients": recipients, "reason": ""}
