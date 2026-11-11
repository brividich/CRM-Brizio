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


def _luogo(pre) -> str:
    sala = getattr(pre, "sala", None)
    return f"{ORGANIZZAZIONE} - {sala.nome}" if sala else ORGANIZZAZIONE


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
        f"DESCRIPTION:{testo('Codice di accesso: ' + pre.codice)}", f"LOCATION:{testo(_luogo(pre))}",
        "END:VEVENT", "END:VCALENDAR", "",
    ])


def valori_invito(pre) -> dict[str, str]:
    """Segnaposti della mail d'invito (personalizza.TESTI["invito_testo"])."""
    sala = pre.sala.nome if getattr(pre, "sala", None) else ""
    quando = ""
    if pre.data_visita:
        quando = f"Visita prevista: {pre.data_visita:%d/%m/%Y}"
        if pre.ora_inizio:
            quando += f" alle {pre.ora_inizio:%H:%M}"
        if sala:
            quando += f", sala {sala}"
    return {
        "nome": pre.ospite_nome, "referente": pre.referente_nome, "quando": quando, "sala": sala,
        "data": f"{pre.data_visita:%d/%m/%Y}" if pre.data_visita else "",
        "ora": f"{pre.ora_inizio:%H:%M}" if pre.ora_inizio else "", "codice": pre.codice,
        "scadenza": f"{timezone.localtime(pre.scade_il):%d/%m/%Y}", "azienda": pre.ospite_azienda or "",
    }


def invia_invito(pre, *, solo_a: str = "") -> None:
    """``solo_a``: prova da Impostazioni, la mail all'ospite va a questo indirizzo e il referente non riceve niente."""
    from core.email_utils import send_hub_mail

    from . import personalizza

    valori = valori_invito(pre)
    testo = personalizza.componi(personalizza.leggi("invito_testo"), valori)
    oggetto = personalizza.componi(personalizza.leggi("invito_oggetto"), valori)[:200]
    allegati = [("codice-accesso.png", _qr_png(pre.codice), "image/png")]
    invito = _ics(pre, "PUBLISH")
    if invito:
        allegati.append(("invito.ics", invito, "text/calendar"))
    send_hub_mail(oggetto, testo, [solo_a or pre.ospite_email], title="Invito in azienda",
                  email_type="Reception", attachments=allegati)
    if solo_a:
        return
    avviso = _ics(pre, "REQUEST")
    if avviso and "@" in pre.referente_email:
        sala = f" Sala {pre.sala.nome}." if pre.sala_id else ""
        # Sala prenotata in Outlook: l'evento è già nel calendario del referente, niente secondo invito.
        gia_in_calendario = bool(pre.outlook_event_id)
        send_hub_mail(f"Visita ospite: {pre.ospite_nome}",
                      f"{pre.ospite_nome} è atteso il {pre.data_visita:%d/%m/%Y}. Codice: {pre.codice}.{sala}"
                      + (" L'appuntamento con la sala è già nel tuo calendario." if gia_in_calendario else ""),
                      [pre.referente_email], title="Visita in programma", email_type="Reception",
                      attachments=[] if gia_in_calendario else [("visita.ics", avviso, "text/calendar")])


# --- Richieste di appuntamento dal modulo pubblico ---------------------------------------------


def invia_conferma_richiesta(richiesta, link: str) -> None:
    """All'esterno: link per confermare l'email. Senza conferma la richiesta non arriva a nessuno."""
    from core.email_utils import send_hub_mail

    from . import personalizza
    from .servizi import ORE_CONFERMA_RICHIESTA

    valori = {"nome": richiesta.nome_completo, "data": f"{richiesta.data_visita:%d/%m/%Y}",
              "ore": str(ORE_CONFERMA_RICHIESTA), "link": link}
    send_hub_mail(personalizza.componi(personalizza.leggi("conferma_oggetto"), valori)[:200],
                  personalizza.componi(personalizza.leggi("conferma_testo"), valori), [richiesta.email],
                  title="Conferma la richiesta", email_type="Reception")


def avvisa_nuova_richiesta(richiesta, link_referente: str, link_pannello: str) -> None:
    """Richiesta confermata: mail al referente riconosciuto, notifica nell'HUB a chi gestisce la reception."""
    from core.email_utils import send_hub_mail
    from core.notifiche import invia_notifica
    from fornitori.tasks import _destinatari

    from .servizi import CHIAVE_RUOLI_RICHIESTE, RUOLI_RICHIESTE_PREDEFINITI

    quando = f"{richiesta.data_visita:%d/%m/%Y}" + (f" alle {richiesta.ora_inizio:%H:%M}" if richiesta.ora_inizio else "")
    riepilogo = (f"{richiesta.nome_completo}{f' ({richiesta.azienda})' if richiesta.azienda else ''} chiede di venire "
                 f"il {quando}. Motivo: {richiesta.motivo or 'non indicato'}.")
    if richiesta.referente and "@" in richiesta.referente.email:
        send_hub_mail(f"Richiesta di visita: {richiesta.nome_completo}",
                      f"{riepilogo}\n{('Messaggio: ' + richiesta.messaggio) if richiesta.messaggio else ''}\n\n"
                      f"Approva o rifiuta da qui: {link_referente}",
                      [richiesta.referente.email], title="Una richiesta di visita per te", email_type="Reception")
    testo = riepilogo + (f" Per {richiesta.referente.nome_elenco}." if richiesta.referente
                         else f" Persona indicata: «{richiesta.referente_indicato}», da assegnare.")
    for uid in _destinatari(CHIAVE_RUOLI_RICHIESTE, RUOLI_RICHIESTE_PREDEFINITI):
        invia_notifica(legacy_user_id=uid, tipo="generico", messaggio=testo[:480], url_azione=link_pannello)


def invia_rifiuto(richiesta) -> None:
    from core.email_utils import send_hub_mail

    from . import personalizza

    valori = {"nome": richiesta.nome_completo, "data": f"{richiesta.data_visita:%d/%m/%Y}",
              "nota": f"Nota: {richiesta.nota_decisione}" if richiesta.nota_decisione else ""}
    send_hub_mail(personalizza.componi(personalizza.leggi("rifiuto_oggetto"), valori)[:200],
                  personalizza.componi(personalizza.leggi("rifiuto_testo"), valori), [richiesta.email],
                  title="Richiesta non accolta", email_type="Reception")
