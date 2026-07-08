"""#5 — Assegnazione + notifica delle nuove specifiche (in-app + email HTML).

`notifica_nuova_specifica(spec)` avvisa l'incaricato scelto, oppure — se non indicato — il
«gruppo IN1» (membri del reparto configurato, da anagrafica `area`, + utenti aggiuntivi della
config). Canali: notifica in-app (`core.notifiche`) e, se attiva, email HTML in stile HUB.
"""
from __future__ import annotations

import logging

from django.conf import settings

from core.notifiche import invia_notifica, invia_notifica_email

logger = logging.getLogger(__name__)

_TIPO = "specifica"


def _legacy_id(user):
    """legacy_user_id di un utente Django (per la notifica in-app), o None."""
    try:
        from core.legacy_utils import get_legacy_user
        lu = get_legacy_user(user)
        return int(lu.id) if lu and getattr(lu, "id", None) else None
    except Exception:  # noqa: BLE001
        return None


def _email_reparto(reparto: str) -> set[str]:
    """Email di notifica dei membri del reparto (gruppo IN1), da anagrafica."""
    reparto = (reparto or "").strip()
    if not reparto:
        return set()
    out: set[str] = set()
    try:
        from anagrafica.models import DipendenteAnagraficaAziendale
        for em in (DipendenteAnagraficaAziendale.objects
                   .filter(area__iexact=reparto)
                   .values_list("email_notifica", flat=True)):
            em = (em or "").strip()
            if em:
                out.add(em)
    except Exception:  # noqa: BLE001
        logger.debug("[gs] impossibile risolvere il reparto %s", reparto, exc_info=True)
    return out


def pool_utenti(cfg=None):
    """Utenti assegnabili singolarmente nel menu «Assegna a» (nomi aggiuntivi della config)."""
    from .models import NotificaConfig
    cfg = cfg or NotificaConfig.get_config()
    return cfg.utenti_aggiuntivi.filter(is_active=True).order_by("first_name", "last_name", "username")


def _url_scheda(spec) -> str:
    return f"/gestione-specifiche/{spec.pk}/"


def _invia_email_html(email: str, spec, url_rel: str) -> None:
    """Email HTML in stile HUB (frame condiviso) con tabella fatti + CTA.

    Usa send_hub_mail: il corpo `text/plain` è testo vero (niente HTML grezzo),
    l'alternativa HTML è instradata nel frame NOVICROM HUB.
    """
    try:
        from core.email_utils import email_cta, email_facts_table, send_hub_mail
        base = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
        url = (base + url_rel) if base else url_rel
        codice = getattr(spec, "codice", "") or ""
        rev = getattr(spec, "revisione", "") or ""
        titolo = getattr(spec, "titolo", "") or ""
        cliente = getattr(spec, "cliente", "") or ""

        rows = [("Codice", f"{codice} · r.{rev}" if rev else codice)]
        if titolo:
            rows.append(("Titolo", titolo))
        if cliente:
            rows.append(("Cliente", cliente))

        fragment = (
            '<p style="margin:0 0 16px;color:#475569;font-size:15px;line-height:1.6;">'
            'È stata inserita una nuova specifica che richiede la '
            '<strong>presa in carico</strong>.</p>'
            + email_facts_table(rows)
            + '<div style="height:18px;line-height:18px;font-size:0;">&nbsp;</div>'
            + email_cta("Apri la scheda e prendi in carico", url)
        )
        body_text = "\n".join(x for x in [
            "È stata inserita una nuova specifica da prendere in carico.",
            "",
            f"Codice: {codice}" + (f" · r.{rev}" if rev else ""),
            f"Titolo: {titolo}" if titolo else "",
            f"Cliente: {cliente}" if cliente else "",
            "",
            f"Apri la scheda: {url}",
        ] if x is not None)

        send_hub_mail(
            subject=f"Nuova specifica {codice} da prendere in carico",
            body_text=body_text,
            recipients=[email],
            title="Nuova specifica da prendere in carico",
            email_type="Gestione Specifiche",
            section_label="Presa in carico",
            body_html_fragment=fragment,
            fail_silently=True,
        )
    except Exception:  # noqa: BLE001
        logger.exception("[gs] invio email nuova specifica a %s fallito", email)


def notifica_nuova_specifica(spec) -> int:
    """Notifica l'incaricato (o il gruppo IN1) di una nuova specifica. Ritorna i destinatari."""
    from .models import NotificaConfig
    cfg = NotificaConfig.get_config()
    url = _url_scheda(spec)
    messaggio = f"Nuova specifica {spec.codice} da prendere in carico."
    destinatari: list[tuple[int | None, str]] = []
    if spec.incaricato_id:
        u = spec.incaricato
        destinatari.append((_legacy_id(u), (u.email or "").strip()))
    else:
        for u in cfg.utenti_aggiuntivi.filter(is_active=True):
            destinatari.append((_legacy_id(u), (u.email or "").strip()))
        for em in _email_reparto(cfg.reparto_in1):
            destinatari.append((None, em))

    n = 0
    email_fatte: set[str] = set()
    for lid, email in destinatari:
        if lid:
            invia_notifica(lid, _TIPO, messaggio, url)          # in-app diretto (utente Django)
        elif email:
            invia_notifica_email(email, _TIPO, messaggio, url)  # in-app via email→legacy
        if cfg.email_attiva and email and email.lower() not in email_fatte:
            email_fatte.add(email.lower())
            _invia_email_html(email, spec, url)
        n += 1
    return n
