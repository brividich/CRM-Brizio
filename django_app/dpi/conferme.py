"""Conferma di ricevuta dei DPI via mail, al posto della firma al banco.

Il magazzino registra la consegna (resta lui a dire «consegnato»). Se non c'e'
firma (tablet) ne' ricevuta su carta, parte una mail con un link personale:
- al dipendente, se ha una mail di notifica aziendale (domini in Impostazioni DPI);
- altrimenti al suo caporeparto/responsabile/preposto (gli approvatori della richiesta);
- in mancanza di entrambi, ai referenti DPI.

Il link e' la credenziale (come ``automazioni.approval_links``): identifica la
conferma e il destinatario, a DB solo l'hash, monouso. Vive sotto
``/approval-actions/dpi/`` (unico prefisso pubblicato via Entra Application Proxy),
quindi si apre anche dal telefono senza login.

«Non li ho ricevuti» avvisa chi consegna (Magazzino o referenti). Dopo
``GIORNI_SOLLECITO`` giorni senza risposta parte un solo sollecito con un link nuovo.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from automazioni.managed_flows import event_flow

from . import flusso

logger = logging.getLogger(__name__)

GIORNI_SOLLECITO = 3
DECISIONI = {"conferma": "CONFERMATA", "contesta": "CONTESTATA"}


def hash_token(raw: str) -> str:
    return hashlib.sha256(str(raw or "").encode("utf-8")).hexdigest()


def _domini_aziendali() -> list[str]:
    from .models import DPIImpostazioni

    raw = DPIImpostazioni.get_singleton().domini_email_aziendali or ""
    return [d.strip().lower().lstrip("@") for d in raw.replace(";", ",").split(",") if d.strip()]


def email_aziendale(legacy_id: int | None) -> str:
    """Mail di notifica del dipendente se aziendale ("" altrimenti)."""
    if not legacy_id:
        return ""
    email = flusso._email_persona(legacy_id)
    if not email or "@" not in email:
        return ""
    domini = _domini_aziendali()
    if domini and email.rsplit("@", 1)[1].lower() not in domini:
        return ""
    return email


def destinatari(richiesta) -> tuple[str, list[str]]:
    """(tipo destinatario, email) per la conferma delle consegne di ``richiesta``."""
    from .models import ConfermaConsegnaDPI

    email = email_aziendale(richiesta.richiedente_legacy_id)
    if email:
        return ConfermaConsegnaDPI.Destinatario.DIPENDENTE, [email]
    capi = flusso.email_preposti(richiesta)
    if capi:
        return ConfermaConsegnaDPI.Destinatario.RESPONSABILE, capi
    return ConfermaConsegnaDPI.Destinatario.RESPONSABILE, flusso.destinatari_referenti()


def _url(raw: str, decisione: str) -> str:
    site_url = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
    return f"{site_url}/approval-actions/dpi/{raw}/{decisione}/"


def _righe_dpi(consegne) -> list[str]:
    return [f"- {flusso._riga_dpi(c.richiesta)} ({c.richiesta.numero})" for c in consegne]


@event_flow("dpi_conferma_ricevuta", skipped_result=0)
def _invia(conferma, consegne, *, sollecito: bool = False) -> int:
    """Crea un link per destinatario e manda la mail. Ritorna le mail inviate."""
    import html

    from core.email_utils import send_hub_mail

    from .models import ConfermaConsegnaDPI, LinkConfermaDPI

    prima = consegne[0]
    tipo, emails = destinatari(prima.richiesta)
    if tipo != conferma.destinatario_tipo:  # al sollecito la mail aziendale puo' essere cambiata
        conferma.destinatario_tipo = tipo
        conferma.save(update_fields=["destinatario_tipo"])
    per_dipendente = conferma.destinatario_tipo == ConfermaConsegnaDPI.Destinatario.DIPENDENTE
    data = prima.data_consegna.strftime("%d/%m/%Y") if prima.data_consegna else ""
    if per_dipendente:
        domanda = f"Il magazzino ha registrato che il {data} ti ha consegnato questi DPI. Confermi di averli ricevuti?"
    else:
        domanda = (f"Il magazzino ha registrato che il {data} ha consegnato questi DPI a {conferma.richiedente_nome}, "
                   "che non ha una mail aziendale. Come suo responsabile, confermi che li ha ricevuti?")
    righe = _righe_dpi(consegne)
    oggetto = ("[DPI] Promemoria: conferma la ricevuta dei DPI" if sollecito else "[DPI] Conferma la ricevuta dei DPI") + (
        "" if per_dipendente else f" - {conferma.richiedente_nome}"
    )
    inviate = 0
    for email in emails:
        raw = secrets.token_urlsafe(32)
        LinkConfermaDPI.objects.create(conferma=conferma, email=email.strip().lower(), token_hash=hash_token(raw))
        si, no = _url(raw, "conferma"), _url(raw, "contesta")
        testo = "\n".join([domanda, "", *righe, "", f"Confermo, ricevuti: {si}", f"Non ricevuti: {no}"])
        lista = "".join(f"<li>{html.escape(r[2:])}</li>" for r in righe)
        frammento = (
            f'<p style="color:#475569;font-size:15px;line-height:1.7;">{html.escape(domanda)}</p>'
            f'<ul style="color:#0f172a;font-size:14px;line-height:1.7;">{lista}</ul>'
            '<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:12px;"><tr>'
            f'<td style="padding:0 12px 0 0;"><a href="{si}" style="display:inline-block;padding:12px 22px;background:#16a34a;'
            'color:#ffffff;text-decoration:none;border-radius:9px;font-size:14px;font-weight:800;">Confermo, ricevuti</a></td>'
            f'<td><a href="{no}" style="display:inline-block;padding:12px 22px;background:#dc2626;'
            'color:#ffffff;text-decoration:none;border-radius:9px;font-size:14px;font-weight:800;">Non li ho ricevuti</a></td>'
            "</tr></table>"
        )
        try:
            inviate += send_hub_mail(
                subject=oggetto, body_text=testo, recipients=[email], title="Conferma ricevuta DPI",
                email_type="DPI", badge="Richiede azione", section_label="Consegne DPI",
                body_html_fragment=frammento, fail_silently=True,
            )
        except Exception:
            logger.warning("Mail di conferma DPI non inviata (%s)", conferma.pk, exc_info=True)
    return inviate


def richiedi(consegne, *, autore: str = ""):
    """Apre la conferma per le consegne fatte insieme a una persona e manda la mail.

    Ritorna (conferma, tipo destinatario, mail inviate) oppure (None, "", 0) se non
    c'e' nessuno a cui chiederla (0 inviate anche con la regola spenta in Automazioni). Fail-soft: un errore non annulla mai la consegna registrata."""
    from .models import ConfermaConsegnaDPI

    consegne = [c for c in consegne if c is not None]
    if not consegne:
        return None, "", 0
    try:
        r = consegne[0].richiesta
        tipo, emails = destinatari(r)
        if not emails:
            return None, "", 0
        with transaction.atomic():
            conferma = ConfermaConsegnaDPI.objects.create(
                richiedente_legacy_id=r.richiedente_legacy_id, richiedente_nome=r.richiedente_nome,
                destinatario_tipo=tipo, creata_da_nome=autore[:200],
            )
            for c in consegne:
                c.conferma = conferma
                c.save(update_fields=["conferma"])
        return conferma, tipo, _invia(conferma, consegne) or 0
    except Exception:
        logger.warning("Conferma di ricevuta DPI non aperta", exc_info=True)
        return None, "", 0


def link_da_token(raw: str):
    from .models import LinkConfermaDPI

    raw = str(raw or "").strip()
    if not raw or len(raw) > 128:
        return None
    return LinkConfermaDPI.objects.select_related("conferma").filter(token_hash=hash_token(raw)).first()


def decidi(link, decisione: str, nota: str = "") -> bool:
    """Registra la decisione come il destinatario del link. False se gia' decisa."""
    from .models import ConfermaConsegnaDPI, RichiestaDPICommento

    stato = DECISIONI[decisione]
    with transaction.atomic():
        aggiornate = ConfermaConsegnaDPI.objects.filter(
            pk=link.conferma_id, stato=ConfermaConsegnaDPI.Stato.IN_ATTESA
        ).update(stato=stato, decisa_il=timezone.now(), decisa_da_email=link.email, nota=(nota or "")[:500])
    if not aggiornate:
        return False
    conferma = ConfermaConsegnaDPI.objects.get(pk=link.conferma_id)
    consegne = list(conferma.consegne.select_related("richiesta", "richiesta__categoria", "richiesta__tipo_dpi",
                                                     "richiesta__modello_dpi", "richiesta__taglia_dpi"))
    if stato == ConfermaConsegnaDPI.Stato.CONFERMATA:
        testo = f"Ricevuta confermata via mail da {link.email}."
    else:
        testo = f"Ricevuta CONTESTATA via mail da {link.email}: «non li ho ricevuti»." + (f" Nota: {nota}" if nota else "")
    for c in consegne:
        RichiestaDPICommento.objects.create(richiesta=c.richiesta, autore_nome="Portale", testo=testo, is_interno=False)
    if stato == ConfermaConsegnaDPI.Stato.CONTESTATA and consegne:
        _avvisa_contestazione(conferma, consegne)
    return True


@event_flow("dpi_consegna_contestata", skipped_result=None)
def _avvisa_contestazione(conferma, consegne) -> None:
    try:
        r = consegne[0].richiesta
        corpo = "\n".join([
            f"{conferma.decisa_da_email} dice che {conferma.richiedente_nome} NON ha ricevuto questi DPI, "
            "registrati come consegnati:", "", *_righe_dpi(consegne),
            *( ["", f"Nota: {conferma.nota}"] if conferma.nota else [] ),
            "", "Verifica la consegna (DPI > Banco consegne, riquadro «Conferme di ricevuta»).",
        ])
        flusso._mail(f"[DPI] Consegna contestata - {conferma.richiedente_nome}", corpo,
                     flusso.destinatari_consegna(r), title="Consegna DPI contestata")
    except Exception:
        logger.warning("Avviso di consegna DPI contestata non inviato (%s)", conferma.pk, exc_info=True)


def sollecita(oggi=None) -> int:
    """Un solo sollecito per le conferme senza risposta da ``GIORNI_SOLLECITO`` giorni:
    link nuovi (i vecchi non valgono piu'). Chiamato dal task DPI delle 07:10."""
    from .models import ConfermaConsegnaDPI

    limite = timezone.now() - timedelta(days=GIORNI_SOLLECITO)
    inviati = 0
    for conferma in ConfermaConsegnaDPI.objects.filter(
        stato=ConfermaConsegnaDPI.Stato.IN_ATTESA, sollecitata_il__isnull=True, created_at__lt=limite
    ):
        consegne = list(conferma.consegne.select_related("richiesta", "richiesta__categoria", "richiesta__tipo_dpi",
                                                         "richiesta__modello_dpi", "richiesta__taglia_dpi"))
        if not consegne:
            continue
        conferma.link.all().delete()
        conferma.sollecitata_il = timezone.now()
        conferma.save(update_fields=["sollecitata_il"])
        inviati += 1 if _invia(conferma, consegne, sollecito=True) else 0
    return inviati
