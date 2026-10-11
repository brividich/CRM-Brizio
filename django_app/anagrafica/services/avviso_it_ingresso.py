"""Avviso all'IT quando HR crea un nuovo dipendente.

Tre canali indipendenti, configurati da *Impostazioni anagrafica → Onboarding /
offboarding* (chiavi ``SiteConfig``, nessuna migrazione):

- email ai destinatari di ``anagrafica_avviso_it_emails``;
- notifica in-app agli utenti di ``anagrafica_avviso_it_utenti`` (id utente legacy);
- ticket IT nel modulo ``tickets`` se ``anagrafica_avviso_it_ticket`` = ``"1"``.

Un canale non configurato si salta in silenzio. L'invio parte dopo il commit
(``transaction.on_commit``) ed è fail-soft: un errore di un canale non tocca
gli altri né la creazione del dipendente. L'esito finisce nell'audit
``AVVISO_IT_NUOVO_DIPENDENTE``.

Il testo contiene solo dati organizzativi (nominativo, reparto, mansione, data
di ingresso, email di notifica, esito dell'account portale, link): mai codice
fiscale, dati sanitari o password.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.urls import reverse

from core import naming
from core.models import SiteConfig
from core.reminder_recipients import split_emails

logger = logging.getLogger(__name__)

CHIAVE_EMAILS = "anagrafica_avviso_it_emails"
CHIAVE_UTENTI = "anagrafica_avviso_it_utenti"
CHIAVE_TICKET = "anagrafica_avviso_it_ticket"

AUDIT_AZIONE = "AVVISO_IT_NUOVO_DIPENDENTE"
CODICE_VOCE_ONBOARDING = "it_account_ad"


# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

def _ids(raw: str) -> list[int]:
    valori = (raw or "").replace(";", ",").replace("\n", ",").split(",")
    return sorted({int(v.strip()) for v in valori if v.strip().isdigit() and int(v.strip()) > 0})


def configurazione() -> dict:
    """Configurazione corrente: ``{"emails": [...], "utenti_ids": [...], "ticket": bool}``."""
    raw = SiteConfig.get_many({CHIAVE_EMAILS: "", CHIAVE_UTENTI: "", CHIAVE_TICKET: "0"})
    return {
        "emails": split_emails(raw[CHIAVE_EMAILS]),
        "utenti_ids": _ids(raw[CHIAVE_UTENTI]),
        "ticket": (raw[CHIAVE_TICKET] or "").strip() == "1",
    }


def salva_configurazione(*, emails_raw: str, utenti_ids, ticket: bool) -> list[str]:
    """Valida e salva. Ritorna gli errori (nessun salvataggio se ce ne sono)."""
    emails = split_emails(emails_raw)
    errori = []
    for email in emails:
        try:
            validate_email(email)
        except ValidationError:
            errori.append(f"Indirizzo email non valido: «{email}».")
    if errori:
        return errori
    ids = _ids(",".join(str(v) for v in (utenti_ids or [])))
    SiteConfig.set(CHIAVE_EMAILS, ", ".join(dict.fromkeys(emails)),
                   "Anagrafica: email IT avvisate alla creazione di un nuovo dipendente")
    SiteConfig.set(CHIAVE_UTENTI, ",".join(str(i) for i in ids),
                   "Anagrafica: utenti (id legacy) avvisati in-app alla creazione di un nuovo dipendente")
    SiteConfig.set(CHIAVE_TICKET, "1" if ticket else "0",
                   "Anagrafica: apre un ticket IT alla creazione di un nuovo dipendente (1/0)")
    return []


# ---------------------------------------------------------------------------
# Contenuto
# ---------------------------------------------------------------------------

@dataclass
class DatiAvviso:
    legacy_id: int
    nominativo: str
    reparto: str = ""
    mansione: str = ""
    data_ingresso: date | None = None
    email_notifica: str = ""
    esito_account: str = ""
    account_da_creare: bool = True
    url_scheda: str = ""
    url_scheda_rel: str = ""
    url_onboarding: str = ""
    pratica_id: int | None = None
    righe: list[tuple[str, str]] = field(default_factory=list)


def _base_url(request) -> str:
    base = str(getattr(settings, "SITE_URL", "") or "").strip().rstrip("/")
    if base:
        return base
    try:
        return request.build_absolute_uri("/").rstrip("/")
    except Exception:
        return ""


def esito_account(scelta_tipo: str, utente_id: int | None) -> tuple[str, bool]:
    """(testo, account_da_creare) dall'esito di ``account_portale.applica_scelta``."""
    from core.legacy_models import UtenteLegacy

    from .account_portale import SCELTA_AD, SCELTA_COLLEGA, SCELTA_LOCALE, SCELTA_NESSUNO

    if utente_id:
        login = (UtenteLegacy.objects.filter(pk=utente_id).values_list("email", flat=True).first() or "").strip()
        suffisso = f" ({login})" if login else ""
        if scelta_tipo == SCELTA_AD:
            return f"Account AD collegato{suffisso}", False
        if scelta_tipo == SCELTA_LOCALE:
            return f"Utente locale del portale creato{suffisso}", False
        return f"Collegato a un utente portale esistente{suffisso}", False
    if scelta_tipo == SCELTA_NESSUNO:
        return "Nessun accesso al portale: account da creare", True
    return "Collegamento dell'account non riuscito: account da verificare o creare", True


def raccogli_dati(request, legacy_id: int, *, scelta_tipo: str) -> DatiAvviso | None:
    from core.legacy_models import AnagraficaDipendente

    from ..models import StoricoContratto
    from .onboarding import pratica_aperta

    row = AnagraficaDipendente.objects.filter(pk=legacy_id).first()
    if row is None:
        return None
    contratto = (
        StoricoContratto.objects.filter(legacy_anagrafica_id=legacy_id)
        .order_by("-data_inizio").values_list("data_inizio", flat=True).first()
    )
    testo_account, da_creare = esito_account(scelta_tipo, getattr(row, "utente_id", None))
    base = _base_url(request)
    scheda_rel = reverse("anagrafica:dipendente_detail", kwargs={"legacy_id": legacy_id})
    pratica = pratica_aperta(legacy_id)
    dati = DatiAvviso(
        legacy_id=legacy_id,
        nominativo=naming.nome_completo(row.nome, row.cognome) or f"Dipendente #{legacy_id}",
        reparto=(row.reparto or "").strip(),
        mansione=(row.mansione or "").strip(),
        data_ingresso=contratto,
        email_notifica=(getattr(row, "email_notifica", "") or "").strip(),
        esito_account=testo_account,
        account_da_creare=da_creare,
        url_scheda=f"{base}{scheda_rel}",
        url_scheda_rel=scheda_rel,
        pratica_id=pratica.pk if pratica else None,
    )
    if pratica:
        dati.url_onboarding = base + reverse("anagrafica:onboarding_detail", kwargs={"pratica_id": pratica.pk})
    dati.righe = [
        ("Nominativo", dati.nominativo),
        ("Reparto", dati.reparto or "—"),
        ("Mansione", dati.mansione or "—"),
        ("Data di ingresso", dati.data_ingresso.strftime("%d/%m/%Y") if dati.data_ingresso else "non indicata"),
        ("Email di notifica", dati.email_notifica or "—"),
        ("Account portale", dati.esito_account),
        ("Scheda dipendente", dati.url_scheda),
    ]
    if dati.url_onboarding:
        dati.righe.append(("Pratica onboarding", dati.url_onboarding))
    return dati


def testo_avviso(dati: DatiAvviso) -> str:
    intro = f"È stato inserito in anagrafica un nuovo dipendente: {dati.nominativo}."
    azione = ("Da predisporre: account AD, casella email, gruppi e accessi applicativi."
              if dati.account_da_creare else
              "Da verificare: casella email, gruppi e accessi applicativi.")
    righe = "\n".join(f"{etichetta}: {valore}" for etichetta, valore in dati.righe)
    return f"{intro}\n\n{righe}\n\n{azione}"


# ---------------------------------------------------------------------------
# Canali
# ---------------------------------------------------------------------------

def _invia_email(dati: DatiAvviso, destinatari: list[str]) -> None:
    from core.email_utils import email_cta, email_facts_table, send_hub_mail, text_to_html

    intro = f"È stato inserito in anagrafica un nuovo dipendente: {dati.nominativo}."
    frammento = text_to_html(intro) + email_facts_table(dati.righe) + email_cta("Apri la scheda", dati.url_scheda)
    send_hub_mail(
        subject=f"[IT] Nuovo ingresso — {dati.nominativo}",
        body_text=testo_avviso(dati),
        recipients=destinatari,
        title="Nuovo dipendente",
        email_type="Anagrafica HR",
        section_label="Avviso IT",
        body_html_fragment=frammento,
    )


def _invia_notifiche(dati: DatiAvviso, utenti_ids: list[int]) -> int:
    from core.notifiche import invia_notifica

    stato = "account da creare" if dati.account_da_creare else "account collegato"
    messaggio = f"Nuovo dipendente {dati.nominativo}"
    if dati.reparto:
        messaggio += f" ({dati.reparto})"
    messaggio = f"{messaggio}: {stato}. Predisporre gli accessi IT."
    for uid in utenti_ids:
        invia_notifica(uid, "generico", messaggio[:500], url_azione=dati.url_scheda_rel[:255])
    return len(utenti_ids)


def _categoria_ticket() -> str:
    from tickets.models import TipoTicket, get_categorie

    codici = [codice for codice, _ in get_categorie(TipoTicket.IT)]
    for codice in codici:
        if "ACCOUNT" in codice.upper():
            return codice
    if "ALTRO_IT" in codici or not codici:
        return "ALTRO_IT"
    return codici[0]


def _apri_ticket(request, dati: DatiAvviso):
    from tickets.models import PrioritaTicket, Ticket, TipoTicket

    user = getattr(request, "user", None)
    autenticato = bool(user and getattr(user, "is_authenticated", False))
    nome = ""
    if autenticato:
        nome = (user.get_full_name() or user.get_username() or "").strip()
    legacy_user_id = None
    try:
        from core.legacy_utils import get_legacy_user

        legacy = get_legacy_user(user) if autenticato else None
        legacy_user_id = getattr(legacy, "id", None)
    except Exception:
        legacy_user_id = None
    ticket = Ticket(
        tipo=TipoTicket.IT,
        titolo=f"Nuovo ingresso: accessi IT per {dati.nominativo}"[:300],
        descrizione=testo_avviso(dati),
        categoria=_categoria_ticket(),
        priorita=PrioritaTicket.MEDIA,
        asset_descrizione_libera="Account e accessi del nuovo dipendente",
        richiedente_nome=(nome or "Anagrafica HR")[:200],
        richiedente_email=((getattr(user, "email", "") if autenticato else "") or "")[:200],
        richiedente_legacy_user_id=legacy_user_id,
        richiedente_user=user if autenticato else None,
    )
    ticket.save()
    return ticket


def _collega_ticket_a_voce(dati: DatiAvviso, ticket, url_ticket: str) -> bool:
    """Annota il ticket nella voce ``it_account_ad`` della pratica onboarding, se c'è."""
    if not dati.pratica_id:
        return False
    from ..models import OnboardingTask

    voce = OnboardingTask.objects.filter(pratica_id=dati.pratica_id, codice=CODICE_VOCE_ONBOARDING).first()
    if voce is None:
        return False
    riga = f"Ticket IT {ticket.numero_ticket} aperto in automatico: {url_ticket}"
    voce.note = f"{voce.note.rstrip()}\n{riga}".strip() if voce.note else riga
    voce.save(update_fields=["note", "updated_at"])
    return True


# ---------------------------------------------------------------------------
# Orchestrazione
# ---------------------------------------------------------------------------

def invia_avviso(request, legacy_id: int, *, scelta_tipo: str) -> dict:
    """Esegue i canali configurati. Non solleva mai: ritorna l'esito per canale."""
    esito: dict = {"canali": [], "errori": [], "saltati": []}
    try:
        conf = configurazione()
    except Exception:
        logger.warning("Avviso IT: configurazione non leggibile", exc_info=True)
        return esito
    if not (conf["emails"] or conf["utenti_ids"] or conf["ticket"]):
        logger.debug("Avviso IT nuovo dipendente %s: nessun canale configurato", legacy_id)
        return esito
    try:
        dati = raccogli_dati(request, legacy_id, scelta_tipo=scelta_tipo)
    except Exception:
        logger.warning("Avviso IT: dati del dipendente %s non leggibili", legacy_id, exc_info=True)
        dati = None
    if dati is None:
        return esito

    if conf["emails"]:
        try:
            _invia_email(dati, conf["emails"])
            esito["canali"].append("email")
            esito["email_destinatari"] = len(conf["emails"])
        except Exception as exc:
            logger.warning("Avviso IT: email non inviata per dipendente %s", legacy_id, exc_info=True)
            esito["errori"].append(f"email: {exc.__class__.__name__}")
    else:
        esito["saltati"].append("email")

    if conf["utenti_ids"]:
        try:
            esito["notifiche"] = _invia_notifiche(dati, conf["utenti_ids"])
            esito["canali"].append("notifica")
        except Exception as exc:
            logger.warning("Avviso IT: notifiche in-app non create per dipendente %s", legacy_id, exc_info=True)
            esito["errori"].append(f"notifica: {exc.__class__.__name__}")
    else:
        esito["saltati"].append("notifica")

    if conf["ticket"]:
        try:
            ticket = _apri_ticket(request, dati)
            esito["canali"].append("ticket")
            esito["ticket"] = ticket.numero_ticket
            url_ticket = _base_url(request) + reverse("tickets:detail", kwargs={"pk": ticket.pk})
            try:
                esito["ticket_su_onboarding"] = _collega_ticket_a_voce(dati, ticket, url_ticket)
            except Exception:
                logger.warning("Avviso IT: ticket non annotato sulla pratica onboarding", exc_info=True)
        except Exception as exc:
            logger.warning("Avviso IT: ticket non aperto per dipendente %s", legacy_id, exc_info=True)
            esito["errori"].append(f"ticket: {exc.__class__.__name__}")
    else:
        esito["saltati"].append("ticket")

    try:
        from core.audit import log_action

        log_action(request, AUDIT_AZIONE, "anagrafica",
                   {**esito, "esito_account": dati.esito_account},
                   oggetto_tipo="dipendente", oggetto_id=str(legacy_id))
    except Exception:
        logger.warning("Audit %s fallito", AUDIT_AZIONE, exc_info=True)
    return esito


def programma_avviso(request, legacy_id: int, *, scelta_tipo: str) -> None:
    """Accoda l'avviso a dopo il commit della creazione. Non solleva mai."""
    def _esegui():
        try:
            invia_avviso(request, legacy_id, scelta_tipo=scelta_tipo)
        except Exception:
            logger.warning("Avviso IT nuovo dipendente %s fallito", legacy_id, exc_info=True)

    try:
        transaction.on_commit(_esegui)
    except Exception:
        logger.warning("Avviso IT nuovo dipendente %s non accodato", legacy_id, exc_info=True)
