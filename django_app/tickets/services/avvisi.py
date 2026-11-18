"""Avvisi dei ticket a chi chiede e a chi gestisce: campanella dell'HUB e mail, a transazione confermata.

Un solo punto per tutti i percorsi (scheda, elenco, API, azioni di massa, OdL):

- ticket nuovo → team gestori del tipo (campanella + mail) e conferma al richiedente;
- assegnato / preso in carico → al tecnico assegnato (se non è lui stesso) e al richiedente;
- risolto → al richiedente, che conferma o riapre; in attesa e annullato dal gestore → al richiedente;
- commento visibile → all'altra parte (richiedente ↔ tecnico o team);
- riaperto o annullato dal richiedente → al tecnico o, se nessuno lo segue, al team;
- allegato rifiutato → a chi l'ha caricato.

La chiusura (CHIUSO) manda solo la campanella: la mail la manda già la regola
``tickets-cambio-stato-email-richiedente``. Chi compie l'azione non riceve l'avviso.
Best effort: un errore di invio non blocca mai il ticket.
"""
from __future__ import annotations

import contextvars
import html
import logging
from contextlib import contextmanager

from django.db import transaction

from ..models import StatoTicket, Ticket, TicketImpostazioni

logger = logging.getLogger(__name__)

_silenzio: contextvars.ContextVar[bool] = contextvars.ContextVar("tickets_avvisi_silenzio", default=False)


@contextmanager
def silenzio():
    """Nessun avviso dentro il blocco (es. ticket registrato a intervento già concluso)."""
    token = _silenzio.set(True)
    try:
        yield
    finally:
        _silenzio.reset(token)


def _norm(email: str | None) -> str:
    return str(email or "").strip().lower()


def url_richiedente(ticket: Ticket) -> str:
    return f"/tickets/{ticket.pk}/"


def url_gestione(ticket: Ticket) -> str:
    return f"/tickets/gestione/{ticket.pk}/"


def email_team(ticket: Ticket) -> list[str]:
    imp = TicketImpostazioni.objects.filter(tipo=ticket.tipo).first()
    emails = []
    for g in (imp.team_gestori if imp else []) or []:
        email = _norm(g.get("email")) if isinstance(g, dict) else ""
        if email and email not in emails:
            emails.append(email)
    return emails


def _campanella(*, email: str = "", legacy_id=None, tipo: str, messaggio: str, url: str) -> None:
    from core.notifiche import invia_notifica, invia_notifica_email

    try:
        if legacy_id:
            invia_notifica(int(legacy_id), tipo, messaggio[:480], url)
        elif email:
            invia_notifica_email(email, tipo, messaggio[:480], url)
    except Exception:
        logger.warning("Avviso ticket in campanella non creato (%s)", tipo, exc_info=True)


def _mail(email: str, *, oggetto: str, testo: str, url: str, pulsante: str, titolo: str) -> None:
    if not email:
        return
    try:
        from core.accounts.portal_links import portal_link
        from core.email_utils import email_cta, send_hub_mail

        link = portal_link(url)
        corpo = "".join(
            f'<p style="color:#475569;font-size:15px;line-height:1.7;margin:0 0 12px;">{html.escape(riga)}</p>'
            for riga in testo.split("\n") if riga.strip()
        )
        if link:
            corpo += email_cta(pulsante, link)
        send_hub_mail(oggetto[:200], testo + (f"\n\n{pulsante}: {link}" if link else ""), [email],
                      title=titolo, email_type="Ticket", body_html_fragment=corpo, fail_silently=True)
    except Exception:
        logger.warning("Mail ticket non inviata a %s (%s)", email, oggetto[:80], exc_info=True)


def _al_richiedente(ticket: Ticket, *, autore_email: str, tipo: str, messaggio: str, oggetto: str,
                    testo: str, pulsante: str = "Apri il ticket", mail: bool = True) -> None:
    email = _norm(ticket.richiedente_email)
    if email and email == _norm(autore_email):
        return
    url = url_richiedente(ticket)
    _campanella(email=email, legacy_id=ticket.richiedente_legacy_user_id, tipo=tipo, messaggio=messaggio, url=url)
    if mail:
        _mail(email, oggetto=oggetto, testo=testo, url=url, pulsante=pulsante, titolo=messaggio)


def _a_chi_gestisce(ticket: Ticket, *, autore_email: str, tipo: str, messaggio: str, oggetto: str,
                    testo: str, solo_team: bool = False) -> None:
    """Al tecnico assegnato; se nessuno lo segue (o ``solo_team``), al team del tipo."""
    autore = _norm(autore_email)
    assegnato = _norm(ticket.assegnato_email)
    destinatari = email_team(ticket) if (solo_team or not assegnato) else [assegnato]
    url = url_gestione(ticket)
    for email in destinatari:
        if email == autore:
            continue
        _campanella(email=email, tipo=tipo, messaggio=messaggio, url=url)
        _mail(email, oggetto=oggetto, testo=testo, url=url, pulsante="Gestisci il ticket", titolo=messaggio)


def _dopo(fn, *args, **kwargs) -> None:
    if _silenzio.get():
        return
    transaction.on_commit(lambda: _esegui(fn, *args, **kwargs))


def _esegui(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.warning("Avviso ticket non riuscito (%s)", getattr(fn, "__name__", fn), exc_info=True)


def _ricarica(ticket_id: int) -> Ticket | None:
    return Ticket.objects.filter(pk=ticket_id).first()


# ── Eventi ────────────────────────────────────────────────────────────────

def nuovo(ticket: Ticket, *, autore_email: str = "") -> None:
    _dopo(_nuovo, ticket.pk, autore_email)


def _nuovo(ticket_id: int, autore_email: str) -> None:
    t = _ricarica(ticket_id)
    if t is None:
        return
    priorita = t.get_priorita_display() if hasattr(t, "get_priorita_display") else t.priorita
    _a_chi_gestisce(
        t, autore_email=autore_email, solo_team=True, tipo="ticket_nuovo",
        messaggio=f"{t.numero_ticket} · {t.titolo} — da {t.richiedente_nome} (priorità {priorita})",
        oggetto=f"Nuovo ticket {t.numero_ticket}: {t.titolo}",
        testo=(f"{t.richiedente_nome} ha aperto il ticket {t.numero_ticket} (priorità {priorita}).\n"
               f"{t.titolo}\n{(t.descrizione or '')[:600]}"),
    )
    _al_richiedente(
        t, autore_email="", tipo="ticket_aperto",
        messaggio=f"Ticket {t.numero_ticket} aperto: {t.titolo}",
        oggetto=f"Ticket {t.numero_ticket} ricevuto: {t.titolo}",
        testo=(f"Abbiamo ricevuto il tuo ticket {t.numero_ticket}: «{t.titolo}».\n"
               "Ti avvisiamo quando qualcuno lo prende in carico e quando è risolto."),
    )


def assegnato(ticket: Ticket, *, autore_email: str = "", autore_nome: str = "") -> None:
    _dopo(_assegnato, ticket.pk, autore_email, autore_nome)


def _assegnato(ticket_id: int, autore_email: str, autore_nome: str) -> None:
    t = _ricarica(ticket_id)
    if t is None:
        return
    chi = t.assegnato_a or (t.delegato_fornitore.ragione_sociale if t.delegato_fornitore_id else "")
    if not chi:
        return
    assegnato_email = _norm(t.assegnato_email)
    if assegnato_email and assegnato_email != _norm(autore_email):
        da = f" da {autore_nome}" if autore_nome else ""
        _campanella(email=assegnato_email, tipo="ticket_assegnato",
                    messaggio=f"{t.numero_ticket} · {t.titolo} — assegnato a te{da}", url=url_gestione(t))
        _mail(assegnato_email, oggetto=f"Ticket {t.numero_ticket} assegnato a te: {t.titolo}",
              testo=f"Il ticket {t.numero_ticket} ti è stato assegnato{da}.\n{t.titolo}\n"
                    f"Richiedente: {t.richiedente_nome}",
              url=url_gestione(t), pulsante="Gestisci il ticket", titolo="Ticket assegnato a te")
    _al_richiedente(
        t, autore_email="", tipo="ticket_preso",
        messaggio=f"Ticket {t.numero_ticket} preso in carico da {chi}",
        oggetto=f"Ticket {t.numero_ticket} preso in carico",
        testo=f"Il tuo ticket {t.numero_ticket} («{t.titolo}») è seguito da {chi}.",
    )


def stato(ticket: Ticket, *, vecchio: str, nuovo_stato: str, autore_email: str = "", nota: str = "") -> None:
    if vecchio == nuovo_stato or nuovo_stato in (StatoTicket.APERTA, StatoTicket.IN_CARICO):
        return
    _dopo(_stato, ticket.pk, vecchio, nuovo_stato, autore_email, nota)


def _stato(ticket_id: int, vecchio: str, nuovo_stato: str, autore_email: str, nota: str) -> None:
    t = _ricarica(ticket_id)
    if t is None:
        return
    extra = f"\nNota: {nota}" if nota else ""
    if nuovo_stato == StatoTicket.RISOLTO:
        _al_richiedente(
            t, autore_email=autore_email, tipo="ticket_risolto",
            messaggio=f"Ticket {t.numero_ticket} risolto: confermi o riapri?",
            oggetto=f"Ticket {t.numero_ticket} risolto: confermi?",
            testo=(f"Il tuo ticket {t.numero_ticket} («{t.titolo}») è stato risolto{f' da {t.risolto_da_nome}' if t.risolto_da_nome else ''}."
                   f"{extra}\nApri il ticket e premi «Confermo» se è tutto a posto, oppure riaprilo scrivendo cosa non va."),
            pulsante="Conferma o riapri",
        )
    elif nuovo_stato == StatoTicket.IN_ATTESA:
        prevista = f" Data prevista: {t.data_prevista_risoluzione:%d/%m/%Y}." if t.data_prevista_risoluzione else ""
        _al_richiedente(
            t, autore_email=autore_email, tipo="ticket_stato",
            messaggio=f"Ticket {t.numero_ticket} in attesa.{prevista}",
            oggetto=f"Ticket {t.numero_ticket} in attesa",
            testo=f"Il tuo ticket {t.numero_ticket} («{t.titolo}») è in attesa.{prevista}{extra}",
        )
    elif nuovo_stato == StatoTicket.CHIUSO:
        _al_richiedente(
            t, autore_email=autore_email, tipo="ticket_stato", mail=False,
            messaggio=f"Ticket {t.numero_ticket} chiuso: {t.titolo}", oggetto="", testo="",
        )
    elif nuovo_stato == StatoTicket.ANNULLATO:
        _al_richiedente(
            t, autore_email=autore_email, tipo="ticket_annullato",
            messaggio=f"Ticket {t.numero_ticket} annullato",
            oggetto=f"Ticket {t.numero_ticket} annullato",
            testo=f"Il tuo ticket {t.numero_ticket} («{t.titolo}») è stato annullato.{extra}",
        )


def commento(ticket: Ticket, *, autore_email: str, testo: str, da_richiedente: bool, interno: bool) -> None:
    if interno:
        return
    _dopo(_commento, ticket.pk, autore_email, testo, da_richiedente)


def _commento(ticket_id: int, autore_email: str, testo: str, da_richiedente: bool) -> None:
    t = _ricarica(ticket_id)
    if t is None:
        return
    breve = " ".join(testo.split())[:200]
    if da_richiedente:
        _a_chi_gestisce(
            t, autore_email=autore_email, tipo="ticket_commento",
            messaggio=f"{t.numero_ticket} · {t.richiedente_nome}: {breve}",
            oggetto=f"Ticket {t.numero_ticket}: nuovo commento del richiedente",
            testo=f"{t.richiedente_nome} ha scritto sul ticket {t.numero_ticket} («{t.titolo}»):\n{testo[:1500]}",
        )
    else:
        _al_richiedente(
            t, autore_email=autore_email, tipo="ticket_commento",
            messaggio=f"Risposta sul ticket {t.numero_ticket}: {breve}",
            oggetto=f"Ticket {t.numero_ticket}: nuova risposta",
            testo=f"C'è una risposta sul tuo ticket {t.numero_ticket} («{t.titolo}»):\n{testo[:1500]}",
            pulsante="Rispondi",
        )


def azione_richiedente(ticket: Ticket, *, azione: str, autore_email: str, nota: str = "") -> None:
    if azione not in ("riapri", "annulla"):
        return
    _dopo(_azione_richiedente, ticket.pk, azione, autore_email, nota)


def _azione_richiedente(ticket_id: int, azione: str, autore_email: str, nota: str) -> None:
    t = _ricarica(ticket_id)
    if t is None:
        return
    extra = f"\n{nota}" if nota else ""
    if azione == "riapri":
        _a_chi_gestisce(
            t, autore_email=autore_email, tipo="ticket_riaperto",
            messaggio=f"{t.numero_ticket} riaperto da {t.richiedente_nome}: {nota[:200]}",
            oggetto=f"Ticket {t.numero_ticket} riaperto: {t.titolo}",
            testo=f"{t.richiedente_nome} ha riaperto il ticket {t.numero_ticket} («{t.titolo}»): non è risolto.{extra}",
        )
    else:
        _a_chi_gestisce(
            t, autore_email=autore_email, tipo="ticket_annullato",
            messaggio=f"{t.numero_ticket} annullato da {t.richiedente_nome}",
            oggetto=f"Ticket {t.numero_ticket} annullato dal richiedente",
            testo=f"{t.richiedente_nome} ha annullato il ticket {t.numero_ticket} («{t.titolo}»).{extra}",
        )


def allegato_rifiutato(allegato, *, nota: str, autore_email: str = "") -> None:
    _dopo(_allegato_rifiutato, allegato.pk, nota, autore_email)


def _allegato_rifiutato(allegato_id: int, nota: str, autore_email: str) -> None:
    from ..models import TicketAllegato

    a = TicketAllegato.objects.select_related("ticket").filter(pk=allegato_id).first()
    email = _norm(getattr(a, "uploaded_by_email", "")) if a else ""
    if not a or not email or email == _norm(autore_email):
        return
    t = a.ticket
    nome = a.nome_originale or "allegato"
    url = url_richiedente(t) if email == _norm(t.richiedente_email) else url_gestione(t)
    _campanella(email=email, tipo="ticket_allegato_rifiutato",
                messaggio=f"{t.numero_ticket}: allegato «{nome}» rifiutato — {nota[:200]}", url=url)
    _mail(email, oggetto=f"Ticket {t.numero_ticket}: allegato rifiutato",
          testo=f"L'allegato «{nome}» caricato sul ticket {t.numero_ticket} è stato rifiutato.\nMotivo: {nota}",
          url=url, pulsante="Apri il ticket", titolo="Allegato rifiutato")
