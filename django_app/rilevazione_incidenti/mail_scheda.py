"""Mail con la scheda completa di una segnalazione di sicurezza, nel formato NOVICROM HUB.

Usata dal comando ``invia_mail_segnalazione`` (per esempio per rimandare a mano una
mail non arrivata). Il contenuto viene dal record locale ``RilevazioneIncidente``,
la stessa tabella su cui girano le regole AU3.
"""
from __future__ import annotations

import html as _html

from django.urls import reverse
from django.utils import timezone

from core.email_utils import email_badge, email_cta, email_facts_table, send_hub_mail

from .models import RilevazioneIncidente

NON_INDICATO = "—"


def _si_no(valore: bool) -> str:
    return "Sì" if valore else "No"


def _data(valore) -> str:
    if not valore:
        return NON_INDICATO
    if hasattr(valore, "hour"):
        if timezone.is_aware(valore):
            valore = timezone.localtime(valore)
        return valore.strftime("%d/%m/%Y %H:%M")
    return valore.strftime("%d/%m/%Y")


def stato(r: RilevazioneIncidente) -> tuple[str, str]:
    """(etichetta, tono) come nell'elenco del modulo: Chiuso / Approvato / Aperto."""
    if r.chiusura_rspp:
        return "Chiuso", "success"
    if (r.approvazione_rls or "").strip().lower() == "approvato":
        return "Approvato", "info"
    return "Aperto", "warning"


def _blocco_testo(titolo: str, testo: str) -> str:
    corpo = _html.escape((testo or "").strip()).replace("\n", "<br>")
    return (
        '<p style="margin:18px 0 6px;font-size:12px;font-weight:700;color:#64748b;'
        'text-transform:uppercase;letter-spacing:.04em;">' + _html.escape(titolo) + "</p>"
        '<p style="margin:0;color:#182232;font-size:14px;line-height:1.6;">' + corpo + "</p>"
    )


def _sezioni_testo(r: RilevazioneIncidente) -> list[tuple[str, str]]:
    sezioni = [
        ("Attività svolta durante l'accaduto", r.descrizione_attivita),
        ("Descrizione dell'avvenimento", r.descrizione_avvenimento),
        ("Altre cause", r.altre_cause),
        ("Misure da adottare", r.quali_misure),
        ("Note del preposto", r.note_preposto),
        ("Note RSPP / ASPP", r.note_rspp),
    ]
    perche = [(f"{i}° perché", getattr(r, f"why_{i}")) for i in range(1, 6)]
    sezioni += perche + [("Partecipanti all'analisi", r.partecipanti)]
    return [(t, v) for t, v in sezioni if (v or "").strip()]


def componi(r: RilevazioneIncidente, *, con_nominativo: bool = True) -> dict:
    """Oggetto, testo semplice e frammento HTML della mail. Non invia niente."""
    etichetta_stato, tono = stato(r)
    reparto = r.reparto or NON_INDICATO
    oggetto = f"[Sicurezza] Segnalazione di sicurezza #{r.pk} ({r.tipologia_scheda}) - {reparto}"

    fatti = [("Riferimento", f"#{r.pk}"), ("Tipologia", r.tipologia_scheda or NON_INDICATO)]
    if con_nominativo:
        fatti.append(("Nominativo", r.nominativo or NON_INDICATO))
    fatti += [
        ("Reparto", reparto),
        ("Data evento", _data(r.data_segnalazione)),
        ("Stato", etichetta_stato),
        ("Approvazione RLS", r.approvazione_rls or NON_INDICATO),
        ("Data approvazione RLS", _data(r.data_approvazione_rls)),
        ("Chiusura RSPP", _si_no(r.chiusura_rspp)),
        ("Data chiusura RSPP", _data(r.data_chiusura_rspp)),
    ]
    if r.planimetria_area_id:
        fatti.append(("Area", r.planimetria_area.name))
    if r.asset_id:
        fatti.append(("Asset", str(r.asset)))
    fatti += [
        ("Uso di una macchina", _si_no(r.usa_macchina)),
    ]
    if r.usa_macchina:
        fatti += [
            ("Macchina / attrezzatura", r.nome_macchina or NON_INDICATO),
            ("Macchina in buono stato", _si_no(r.buono_stato_macchina)),
        ]
    fatti += [
        ("DPI previsti utilizzati", _si_no(r.utilizzo_dpi)),
        ("Prima volta", _si_no(r.prima_volta)),
        ("Persone coinvolte", r.persone_coinvolte or NON_INDICATO),
        ("Causa dell'evento", r.causa_evento or NON_INDICATO),
        ("Misure tecniche / organizzative", _si_no(r.misure_tecniche)),
    ]
    sezioni = _sezioni_testo(r) if con_nominativo else [
        (t, v) for t, v in _sezioni_testo(r) if t != "Descrizione dell'avvenimento"
    ]

    from core.accounts.portal_links import portal_link

    link = portal_link(reverse("rilevazione_incidenti:dettaglio", args=[r.pk]))

    frammento = (
        '<p style="margin:0 0 14px;color:#475569;font-size:15px;line-height:1.65;">'
        "Buongiorno,<br>di seguito la scheda della segnalazione di sicurezza.</p>"
        f'<p style="margin:0 0 12px;">{email_badge(etichetta_stato, tono)}</p>'
        + email_facts_table(fatti)
        + "".join(_blocco_testo(t, v) for t, v in sezioni)
    )
    if link:
        frammento += '<div style="margin:22px 0 0;">' + email_cta("Apri la segnalazione", link) + "</div>"

    righe = ["Buongiorno,", "di seguito la scheda della segnalazione di sicurezza.", ""]
    righe += [f"{etichetta}: {valore}" for etichetta, valore in fatti]
    for titolo, testo in sezioni:
        righe += ["", f"{titolo}:", testo.strip()]
    if link:
        righe += ["", f"Apri la segnalazione: {link}"]
    righe += ["", "Questo messaggio è generato da NOVICROM HUB."]

    return {
        "oggetto": oggetto,
        "testo": "\n".join(righe),
        "frammento": frammento,
        "titolo": f"Segnalazione di sicurezza #{r.pk}",
    }


def invia(r: RilevazioneIncidente, destinatari: list[str], *, cc: list[str] | None = None,
          con_nominativo: bool = True) -> int:
    """Manda la scheda; la riga finisce in Automazioni → «Mail inviate»."""
    mail = componi(r, con_nominativo=con_nominativo)
    return send_hub_mail(
        mail["oggetto"],
        mail["testo"],
        destinatari,
        cc=cc,
        title=mail["titolo"],
        email_type="Sicurezza",
        section_label="Segnalazione di sicurezza",
        body_html_fragment=mail["frammento"],
    )
