"""Riepilogo mattutino personale delle scadenze, per mail.

Chi lo chiede (Impostazioni notifiche → «Riepilogo scadenze via mail») riceve
ogni mattina dei giorni feriali le voci dello Scadenzario globale che *lui* può
vedere: le scadute e quelle entro 7 o 30 giorni. Stesse sorgenti, stesse
regole e stessi permessi della pagina ``/scadenze``: si chiama ``collect_all``
con una richiesta costruita per l'utente destinatario, quindi nessuno riceve
per mail qualcosa che non potrebbe aprire nel portale.

Niente mail se non c'è niente; al massimo una al giorno per utente
(``NotificaCanali.digest_ultimo_invio``).
"""
from __future__ import annotations

import logging
from datetime import date

from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from .scadenze_providers import SOURCE_LABELS, collect_all

logger = logging.getLogger(__name__)

MAX_VOCI_MAIL = 40


def _richiesta_per(user):
    """Richiesta sintetica per valutare i permessi come se l'utente aprisse /scadenze."""
    request = HttpRequest()
    request.method = "GET"
    request.path = request.path_info = reverse("scadenze_globali")
    request.META = {"SERVER_NAME": "localhost", "SERVER_PORT": "80", "REQUEST_METHOD": "GET"}
    request.user = user
    request.session = {}
    return request


def voci_per_utente(user, *, giorni: int, oggi: date | None = None) -> list:
    oggi = oggi or timezone.localdate()
    voci = collect_all(_richiesta_per(user), oggi=oggi)
    return [v for v in voci if v.giorni is not None and v.giorni <= giorni]


def _email_utente(user) -> str:
    # Stessa regola del calendario Outlook: email_notifica dell'anagrafica
    # (la mailbox reale), poi l'email dell'account.
    from tasks.outlook_reminder import _notification_email_for_user

    return _notification_email_for_user(user)


def _card(v) -> dict:
    from anagrafica.services.email_digest import scadenza_badge

    giorni = v.giorni if v.giorni is not None else None
    soggetto = f" · {v.soggetto}" if v.soggetto else ""
    return {
        "title": v.titolo or v.kind_label,
        "subtitle": f"{SOURCE_LABELS.get(v.source, v.source)} · {v.kind_label}{soggetto}",
        "badge": scadenza_badge(giorni, scaduto=v.scaduta, label_scaduto="Scaduta"),
        "note": f"Scadenza {v.data_scadenza:%d-%m-%Y}" if v.data_scadenza else "",
        "accent": "#dc2626" if v.scaduta else "#f59e0b",
    }


def invia_digest_utente(canali, *, oggi: date | None = None, dry_run: bool = False) -> str:
    """Manda il riepilogo a un utente. Ritorna l'esito: inviato / vuoto / gia_inviato /
    senza_email / errore."""
    from anagrafica.services.email_digest import digest_fragment
    from core.email_utils import send_hub_mail

    oggi = oggi or timezone.localdate()
    if canali.digest_ultimo_invio == oggi:
        return "gia_inviato"
    user = canali.user
    if not user.is_active:
        return "vuoto"
    email = _email_utente(user)
    if not email:
        return "senza_email"
    voci = voci_per_utente(user, giorni=int(canali.digest_giorni or 7), oggi=oggi)
    if not voci:
        return "vuoto"
    if dry_run:
        return "inviato"

    scadute = [v for v in voci if v.scaduta]
    prossime = [v for v in voci if not v.scaduta]
    resto = max(0, len(voci) - MAX_VOCI_MAIL)
    scadute_mail = scadute[:MAX_VOCI_MAIL]
    prossime_mail = prossime[: max(0, MAX_VOCI_MAIL - len(scadute_mail))]
    base = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
    link = f"{base}{reverse('scadenze_globali')}" if base else reverse("scadenze_globali")
    intro = (
        f"{len(scadute)} scadute e {len(prossime)} in scadenza entro {canali.digest_giorni} giorni. "
        f"Elenco completo: {link}"
    )
    if resto:
        intro += f" (in questa mail le prime {MAX_VOCI_MAIL}, le altre {resto} sono nel portale)."
    fragment = digest_fragment([
        (f"Scadute ({len(scadute)})", [_card(v) for v in scadute_mail]),
        (f"Entro {canali.digest_giorni} giorni ({len(prossime)})", [_card(v) for v in prossime_mail]),
    ], intro=intro)
    righe = [intro, ""] + [
        f"- {v.data_scadenza:%d-%m-%Y} {SOURCE_LABELS.get(v.source, v.source)}: {v.titolo} {v.soggetto}".rstrip()
        for v in (scadute_mail + prossime_mail) if v.data_scadenza
    ]
    try:
        send_hub_mail(
            f"[SCADENZE] {len(scadute)} scadute, {len(prossime)} entro {canali.digest_giorni} giorni - {oggi:%d-%m-%Y}",
            "\n".join(righe),
            [email],
            email_type="Scadenzario",
            section_label="Il tuo riepilogo scadenze",
            body_html_fragment=fragment,
            footer_note="Lo ricevi perché l'hai attivato in Notifiche → Impostazioni. Da lì lo puoi spegnere.",
            fail_silently=False,
        )
    except Exception:
        logger.exception("Riepilogo scadenze: invio fallito per user %s", user.pk)
        return "errore"
    canali.digest_ultimo_invio = oggi
    canali.save(update_fields=["digest_ultimo_invio", "updated_at"])
    return "inviato"


def invia_digest_scadenze(*, oggi: date | None = None, dry_run: bool = False) -> dict:
    """Riepilogo a tutti gli utenti che l'hanno attivato. Solo giorni feriali."""
    from core.models import NotificaCanali

    oggi = oggi or timezone.localdate()
    esiti: dict[str, int] = {}
    if oggi.weekday() >= 5:
        return {"saltato": "weekend"}
    for canali in NotificaCanali.objects.filter(digest_scadenze=True, user__is_active=True).select_related("user"):
        try:
            esito = invia_digest_utente(canali, oggi=oggi, dry_run=dry_run)
        except Exception:
            logger.exception("Riepilogo scadenze: errore per user %s", canali.user_id)
            esito = "errore"
        esiti[esito] = esiti.get(esito, 0) + 1
    return esiti
