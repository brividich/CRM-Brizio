"""Mail con la scheda completa di una segnalazione del Diario del preposto, formato NOVICROM HUB.

Usata dal comando ``invia_mail_preposto``. Gli allegati si elencano sempre; si
allegano alla mail solo se richiesto e fino a ``LIMITE_ALLEGATI_BYTE`` in tutto.
"""
from __future__ import annotations

import html as _html
import mimetypes

from django.urls import reverse
from django.utils import timezone

from core.email_utils import email_badge, email_cta, email_facts_table, send_hub_mail

from .models import SegnalazionePreposto

NON_INDICATO = "—"
LIMITE_ALLEGATI_BYTE = 15 * 1024 * 1024


def _data(valore) -> str:
    if not valore:
        return NON_INDICATO
    if timezone.is_aware(valore):
        valore = timezone.localtime(valore)
    return valore.strftime("%d/%m/%Y %H:%M")


def _dimensione(byte: int | None) -> str:
    if not byte:
        return ""
    if byte < 1024 * 1024:
        return f" ({max(1, byte // 1024)} KB)"
    return f" ({byte / (1024 * 1024):.1f} MB)"


def leggi_allegati(s: SegnalazionePreposto) -> tuple[list[tuple[str, bytes, str]], list[str]]:
    """(allegati per la mail, nomi rimasti fuori perché illeggibili o oltre il limite)."""
    allegati, esclusi, totale = [], [], 0
    for a in s.allegati_attivi().order_by("uploaded_at", "pk"):
        try:
            with a.file.open("rb") as fh:
                contenuto = fh.read()
        except Exception:
            esclusi.append(a.nome_file)
            continue
        if totale + len(contenuto) > LIMITE_ALLEGATI_BYTE:
            esclusi.append(a.nome_file)
            continue
        totale += len(contenuto)
        tipo = mimetypes.guess_type(a.nome_file)[0] or "application/octet-stream"
        allegati.append((a.nome_file, contenuto, tipo))
    return allegati, esclusi


def componi(s: SegnalazionePreposto) -> dict:
    """Oggetto, testo semplice e frammento HTML della mail. Non invia niente."""
    codice = s.codice_identificativo or f"#{s.pk}"
    oggetto = f"[Sicurezza] Diario del preposto {codice} - {s.titolo}"
    stato, tono = ("Archiviata", "neutral") if s.is_eliminata else ("Nel registro", "info")

    fatti = [
        ("Codice", codice),
        ("Titolo", s.titolo or NON_INDICATO),
        ("Data segnalazione", _data(s.data_segnalazione)),
        ("Preposto", s.preposto or NON_INDICATO),
        ("Chi segnala", s.chi_segnala or NON_INDICATO),
        ("Registrata il", _data(s.created_at)),
    ]
    if s.is_eliminata:
        fatti += [("Archiviata il", _data(s.eliminata_il)), ("Motivo", s.motivo_eliminazione or NON_INDICATO)]
    allegati = [f"{a.nome_file}{_dimensione(a.dimensione)}" for a in s.allegati_attivi().order_by("uploaded_at", "pk")]

    from core.accounts.portal_links import portal_link

    link = portal_link(reverse("diario_preposto:dettaglio", args=[s.pk]))
    descrizione = _html.escape((s.descrizione or "").strip()).replace("\n", "<br>") or NON_INDICATO

    etichetta = (
        '<p style="margin:18px 0 6px;font-size:12px;font-weight:700;color:#64748b;'
        'text-transform:uppercase;letter-spacing:.04em;">{}</p>'
    )
    frammento = (
        '<p style="margin:0 0 14px;color:#475569;font-size:15px;line-height:1.65;">'
        "Buongiorno,<br>di seguito la segnalazione registrata nel Diario del preposto.</p>"
        f'<p style="margin:0 0 12px;">{email_badge(stato, tono)}</p>'
        + email_facts_table(fatti)
        + etichetta.format("Descrizione")
        + f'<p style="margin:0;color:#182232;font-size:14px;line-height:1.6;">{descrizione}</p>'
    )
    if allegati:
        voci = "".join(f"<li>{_html.escape(n)}</li>" for n in allegati)
        frammento += etichetta.format("Allegati") + (
            f'<ul style="margin:0;padding-left:18px;color:#182232;font-size:14px;line-height:1.6;">{voci}</ul>'
        )
    if link:
        frammento += '<div style="margin:22px 0 0;">' + email_cta("Apri la segnalazione", link) + "</div>"

    righe = ["Buongiorno,", "di seguito la segnalazione registrata nel Diario del preposto.", ""]
    righe += [f"{e}: {v}" for e, v in fatti]
    righe += ["", "Descrizione:", (s.descrizione or "").strip() or NON_INDICATO]
    if allegati:
        righe += ["", "Allegati:"] + [f"- {n}" for n in allegati]
    if link:
        righe += ["", f"Apri la segnalazione: {link}"]
    righe += ["", "Questo messaggio è generato da NOVICROM HUB."]

    return {
        "oggetto": oggetto[:255],
        "testo": "\n".join(righe),
        "frammento": frammento,
        "titolo": f"Diario del preposto {codice}",
    }


def invia(s: SegnalazionePreposto, destinatari: list[str], *, cc: list[str] | None = None,
          con_allegati: bool = False) -> tuple[int, list[str]]:
    """Manda la scheda; ritorna (mail inviate, allegati rimasti fuori). Finisce in «Mail inviate»."""
    mail = componi(s)
    allegati, esclusi = leggi_allegati(s) if con_allegati else ([], [])
    inviate = send_hub_mail(
        mail["oggetto"],
        mail["testo"],
        destinatari,
        cc=cc,
        title=mail["titolo"],
        email_type="Sicurezza",
        section_label="Diario del preposto",
        body_html_fragment=mail["frammento"],
        attachments=allegati,
    )
    return inviate, esclusi


def destinatari_automatici() -> list[str]:
    """Destinatari del flusso «scheda completa» (Automazioni → Notifiche di sistema → Modifica)."""
    from automazioni.mail_config import elenco_indirizzi
    from automazioni.mail_modulo import RSPP, SCHEDA_PREPOSTO
    from core.models import SiteConfig

    return elenco_indirizzi(SiteConfig.get(SCHEDA_PREPOSTO, RSPP) or "")


from automazioni.managed_flows import event_flow  # noqa: E402


@event_flow("diario_preposto_scheda", skipped_result=0)
def invia_alla_creazione(pk) -> int:
    """Flusso: alla nuova segnalazione del preposto, la scheda completa ai destinatari configurati."""
    s = SegnalazionePreposto.objects.filter(pk=pk).first()
    destinatari = destinatari_automatici()
    if s is None or not destinatari:
        return 0
    return invia(s, destinatari)[0]


def dopo_creazione(pk) -> None:
    """Dalla vista «Nuova segnalazione»: parte dopo il commit e non blocca mai il salvataggio."""
    import logging

    from django.db import transaction

    def _manda():
        try:
            invia_alla_creazione(pk)
        except Exception:
            logging.getLogger(__name__).warning("scheda della segnalazione preposto %s non inviata", pk, exc_info=True)

    transaction.on_commit(_manda)
