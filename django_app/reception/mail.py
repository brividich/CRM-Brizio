"""Invito all'ospite pre-registrato (codice, QR, calendario) e avviso al referente."""
from __future__ import annotations

import io
from datetime import datetime

from django.utils import timezone

ORGANIZZAZIONE = "Costruzioni Novicrom Srl"


def _qr_png(codice: str) -> bytes:
    import qrcode

    buffer = io.BytesIO()
    qrcode.make(codice, box_size=8, border=2).save(buffer, format="PNG")
    return buffer.getvalue()


def _ics(pre, metodo: str) -> str | None:
    if not pre.data_visita:
        return None
    inizio = datetime.combine(pre.data_visita, pre.ora_inizio or datetime.min.time().replace(hour=9))
    fine = datetime.combine(pre.data_visita, pre.ora_fine or inizio.time().replace(hour=min(inizio.hour + 1, 23)))
    testo = lambda s: (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")  # noqa: E731
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NOVICROM HUB//Reception//IT", f"METHOD:{metodo}", "BEGIN:VEVENT",
        f"UID:prereg-{pre.codice}@novicrom-hub", f"DTSTAMP:{timezone.now():%Y%m%dT%H%M%SZ}",
        f"DTSTART;TZID=Europe/Rome:{inizio:%Y%m%dT%H%M%S}", f"DTEND;TZID=Europe/Rome:{fine:%Y%m%dT%H%M%S}",
        f"SUMMARY:{testo('Visita ' + ORGANIZZAZIONE if metodo == 'PUBLISH' else 'Visita di ' + pre.ospite_nome)}",
        f"DESCRIPTION:{testo('Codice di accesso: ' + pre.codice)}", f"LOCATION:{testo(ORGANIZZAZIONE)}",
        "END:VEVENT", "END:VCALENDAR", "",
    ])


def invia_invito(pre) -> None:
    from core.email_utils import send_hub_mail

    quando = ""
    if pre.data_visita:
        quando = f"Visita prevista: {pre.data_visita:%d/%m/%Y}"
        if pre.ora_inizio:
            quando += f" alle {pre.ora_inizio:%H:%M}"
        quando += "\n"
    testo = (f"Gentile {pre.ospite_nome},\n{pre.referente_nome} la aspetta da {ORGANIZZAZIONE}.\n{quando}\n"
             f"Il suo codice di accesso è: {pre.codice}\nValido fino al {timezone.localtime(pre.scade_il):%d/%m/%Y}.\n\n"
             "All'arrivo, al chiosco della reception scelga «Ho un codice» e inserisca il codice o mostri il QR allegato, "
             "poi ritiri il cartellino.")
    allegati = [("codice-accesso.png", _qr_png(pre.codice), "image/png")]
    invito = _ics(pre, "PUBLISH")
    if invito:
        allegati.append(("invito.ics", invito, "text/calendar"))
    send_hub_mail(f"Il suo accesso a {ORGANIZZAZIONE}", testo, [pre.ospite_email], title="Invito in azienda",
                  email_type="Reception", attachments=allegati)
    avviso = _ics(pre, "REQUEST")
    if avviso and "@" in pre.referente_email:
        send_hub_mail(f"Visita ospite: {pre.ospite_nome}", f"{pre.ospite_nome} è atteso il {pre.data_visita:%d/%m/%Y}. Codice: {pre.codice}.",
                      [pre.referente_email], title="Visita in programma", email_type="Reception",
                      attachments=[("visita.ics", avviso, "text/calendar")])
