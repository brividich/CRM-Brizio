"""Regole della reception, le stesse del GuestPortal. Unico punto che scrive visite e cartellini."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Cartellino, EventoVisita, Ospite, Preregistrazione, Referente, RichiestaAppuntamento, Visita

GIORNI_RIAPERTURA = 7
CARATTERI_CODICE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # niente O, 0, 1, I: si confondono
GIORNI_VALIDITA_CODICE = 7
# Richieste di appuntamento dal modulo pubblico (gli stessi numeri sono scritti nel modulo e nell'informativa).
ORE_CONFERMA_RICHIESTA = 48
GIORNI_CONSERVAZIONE_RICHIESTE = 30
GIORNI_MAX_ANTICIPO_RICHIESTA = 90
MAX_RICHIESTE_APERTE_PER_EMAIL = 3
# Chi riceve nell'HUB la notifica delle richieste confermate (nomi di ruolo, come reception_usciti_ruoli).
CHIAVE_RUOLI_RICHIESTE = "reception_richieste_ruoli"
RUOLI_RICHIESTE_PREDEFINITI = "Information Technology Manager"


class GiaDentro(Exception):
    pass


class CartelliniFiniti(Exception):
    pass


class EmailDiAltri(Exception):
    pass


class OperazioneNonValida(Exception):
    """Il messaggio si mostra all'operatore."""


def _evento(visita_id: int, azione: str, autore: str = "", ip: str = "", **dettaglio) -> None:
    EventoVisita.objects.create(
        visita_id_rif=visita_id, azione=azione, autore=(autore or "")[:255], ip=(ip or "")[:45],
        dettaglio=json.dumps(dettaglio, default=str, ensure_ascii=False), quando=timezone.now(),
    )


def trova_ospite_per_email(email: str) -> Ospite | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    return Ospite.objects.filter(email__iexact=email, anonimizzato=False).order_by("pk").first()


def ospite_da_dati(*, nome: str, cognome: str, email: str = "", telefono: str = "", azienda: str = "",
                   ip: str = "") -> Ospite:
    """Trova o crea l'ospite. Stessa email con un altro nome: errore, non si sovrascrive."""
    email = (email or "").strip().lower()
    esistente = trova_ospite_per_email(email)
    if esistente is not None:
        if (esistente.nome.strip().lower(), esistente.cognome.strip().lower()) != (nome.strip().lower(), cognome.strip().lower()):
            raise EmailDiAltri
        esistente.nome, esistente.cognome = nome.strip(), cognome.strip()
        esistente.telefono, esistente.azienda = (telefono or "").strip(), (azienda or "").strip()
        esistente.informativa_letta_il, esistente.informativa_ip = timezone.now(), (ip or "")[:45]
        esistente.save()
        return esistente
    return Ospite.objects.create(
        nome=nome.strip(), cognome=cognome.strip(), email=email, telefono=(telefono or "").strip(),
        azienda=(azienda or "").strip(), informativa_letta_il=timezone.now(), informativa_ip=(ip or "")[:45],
    )


def ospite_fornitore(*, nome: str, cognome: str, azienda: str, ip: str = "") -> Ospite:
    ospite = Ospite.objects.filter(
        nome__iexact=nome, cognome__iexact=cognome, azienda__iexact=azienda, anonimizzato=False,
    ).order_by("pk").first()
    if ospite is None:
        return Ospite.objects.create(nome=nome.strip(), cognome=cognome.strip(), azienda=azienda.strip(),
                                     informativa_letta_il=timezone.now(), informativa_ip=(ip or "")[:45])
    ospite.informativa_letta_il, ospite.informativa_ip = timezone.now(), (ip or "")[:45]
    ospite.save(update_fields=["informativa_letta_il", "informativa_ip", "aggiornato_il"])
    return ospite


def registra_ingresso(ospite: Ospite, *, referente_nome: str, referente_email: str = "", motivo: str = "",
                      tipo: str = Visita.NORMALE, ditta=None, contatto=None, creata_da: str = "CHIOSCO",
                      cartellino: str | None = None, quando: datetime | None = None,
                      invia_mail: bool = True) -> Visita:
    """Una visita aperta per persona e un cartellino libero, nella stessa transazione: due ingressi
    insieme non prendono lo stesso cartellino. ``cartellino=""``: visita senza (solo pannello)."""
    with transaction.atomic():
        aperte = Visita.objects.filter(stato=Visita.DENTRO)
        aperta = aperte.filter(contatto=contatto).exists() if contatto is not None else aperte.filter(ospite=ospite).exists()
        if aperta:
            raise GiaDentro
        adesso = timezone.now()
        if cartellino == "":
            numero = Visita.SENZA_CARTELLINO
        else:
            scelti = Cartellino.objects.select_for_update().filter(disponibile=True)
            if cartellino:
                scelti = scelti.filter(numero=cartellino)
            scelto = scelti.order_by("numero").first()
            if scelto is None:
                raise CartelliniFiniti
            scelto.disponibile, scelto.ultima_assegnazione = False, adesso
            scelto.save(update_fields=["disponibile", "ultima_assegnazione"])
            numero = scelto.numero
        return Visita.objects.create(
            ospite=ospite, cartellino=numero, referente_nome=referente_nome.strip(),
            referente_email=(referente_email or "").strip(), motivo=(motivo or "").strip()[:500],
            ingresso=quando or adesso, stato=Visita.DENTRO, tipo=tipo, ditta=ditta, contatto=contatto,
            creata_da=creata_da[:50], mail_stato=Visita.MAIL_DA_INVIARE if invia_mail else Visita.MAIL_INVIATA,
        )


def _libera_cartellino(numero: str, *, escludi: int, quando) -> bool:
    if not numero or numero == Visita.SENZA_CARTELLINO:
        return False
    if Visita.objects.filter(cartellino=numero, stato=Visita.DENTRO).exclude(pk=escludi).exists():
        return False
    return bool(Cartellino.objects.filter(numero=numero).update(disponibile=True, ultima_restituzione=quando))


def registra_uscita(visita_id: int, *, cartellino: str | None = None, quando: datetime | None = None,
                    autore: str = "", ip: str = "", origine: str = "CHIOSCO") -> Visita:
    """Chiude la visita aperta e libera il cartellino, se nessun'altra visita aperta lo usa."""
    with transaction.atomic():
        visita = Visita.objects.select_for_update().filter(pk=visita_id).first()
        if visita is None or visita.stato != Visita.DENTRO:
            raise OperazioneNonValida("Visita non trovata o già conclusa.")
        if cartellino is not None and visita.cartellino.lstrip("0") != str(cartellino).lstrip("0"):
            raise OperazioneNonValida("Il cartellino non corrisponde alla visita.")
        adesso = quando or timezone.now()
        visita.uscita, visita.stato = adesso, Visita.USCITO
        visita.save(update_fields=["uscita", "stato"])
        liberato = _libera_cartellino(visita.cartellino, escludi=visita.pk, quando=adesso)
        if origine != "CHIOSCO":
            _evento(visita.pk, "USCITA_FORZATA", autore, ip, cartellino=visita.cartellino, uscita=adesso,
                    cartellino_liberato=liberato)
    return visita


def correggi_uscita(visita_id: int, quando: datetime, *, autore: str = "", ip: str = "") -> Visita:
    with transaction.atomic():
        visita = Visita.objects.select_for_update().filter(pk=visita_id).first()
        if visita is None:
            raise OperazioneNonValida("Visita non trovata.")
        if not visita.ingresso:
            raise OperazioneNonValida("La visita non ha un orario di ingresso.")
        if visita.stato not in (Visita.DENTRO, Visita.USCITO):
            raise OperazioneNonValida("Questa visita non consente l'uscita.")
        if quando < visita.ingresso:
            raise OperazioneNonValida("L'uscita non può precedere l'ingresso.")
        if quando > timezone.now():
            raise OperazioneNonValida("L'uscita non può essere nel futuro.")
        prima, stato_prima = visita.uscita, visita.stato
        visita.uscita, visita.stato = quando, Visita.USCITO
        visita.save(update_fields=["uscita", "stato"])
        liberato = stato_prima == Visita.DENTRO and _libera_cartellino(visita.cartellino, escludi=visita.pk, quando=quando)
        _evento(visita.pk, "USCITA_CORRETTA", autore, ip, prima=prima, dopo=quando, stato_prima=stato_prima,
                cartellino_liberato=liberato)
    return visita


def riapri_visita(visita_id: int, cartellino: str, *, autore: str = "", ip: str = "") -> Visita:
    """Riapre una visita chiusa per errore, entro ``GIORNI_RIAPERTURA``, con un cartellino libero."""
    with transaction.atomic():
        visita = Visita.objects.select_for_update().filter(pk=visita_id).first()
        if visita is None:
            raise OperazioneNonValida("Visita non trovata.")
        if visita.stato != Visita.USCITO:
            raise OperazioneNonValida("Solo una visita chiusa può essere riaperta.")
        if not visita.ingresso or visita.ingresso < timezone.now() - timedelta(days=GIORNI_RIAPERTURA):
            raise OperazioneNonValida(f"Si riaprono solo le visite degli ultimi {GIORNI_RIAPERTURA} giorni.")
        if Visita.objects.filter(ospite=visita.ospite, stato=Visita.DENTRO).exists():
            raise OperazioneNonValida("L'ospite ha già una visita aperta: chiudila prima.")
        scelto = Cartellino.objects.select_for_update().filter(numero=cartellino).first()
        if scelto is None:
            raise OperazioneNonValida("Cartellino inesistente.")
        if not scelto.disponibile or Visita.objects.filter(cartellino=cartellino, stato=Visita.DENTRO).exists():
            raise OperazioneNonValida("Cartellino non disponibile: aggiorna l'elenco e riprova.")
        prima = visita.uscita
        visita.uscita, visita.stato, visita.cartellino = None, Visita.DENTRO, cartellino
        visita.save(update_fields=["uscita", "stato", "cartellino"])
        scelto.disponibile, scelto.ultima_assegnazione = False, timezone.now()
        scelto.save(update_fields=["disponibile", "ultima_assegnazione"])
        _evento(visita.pk, "RIAPERTA", autore, ip, uscita_prima=prima, cartellino=cartellino)
    return visita


def cartellini_liberi() -> list[str]:
    occupati = Visita.objects.filter(stato=Visita.DENTRO).values("cartellino")
    return list(Cartellino.objects.filter(disponibile=True).exclude(numero__in=occupati)
                .order_by("numero").values_list("numero", flat=True))


def nuovo_codice() -> str:
    while True:
        codice = "".join(secrets.choice(CARATTERI_CODICE) for _ in range(8))
        if not Preregistrazione.objects.filter(codice=codice).exists():
            return codice


def preregistrazione_valida(codice: str) -> Preregistrazione | None:
    return Preregistrazione.objects.filter(codice=(codice or "").strip().upper(), usata_il__isnull=True,
                                           scade_il__gte=timezone.now()).first()


def ingresso_da_codice(codice: str, *, ip: str = "") -> Visita | None:
    """``None`` se il codice non vale. Il codice si usa una volta sola anche con due richieste insieme."""
    with transaction.atomic():
        pre = Preregistrazione.objects.select_for_update().filter(
            codice=(codice or "").strip().upper(), usata_il__isnull=True, scade_il__gte=timezone.now(),
        ).first()
        if pre is None:
            return None
        nome, _, cognome = pre.ospite_nome.strip().partition(" ")
        ospite = ospite_da_dati(nome=nome, cognome=cognome, email=pre.ospite_email, azienda=pre.ospite_azienda, ip=ip)
        visita = registra_ingresso(ospite, referente_nome=pre.referente_nome, referente_email=pre.referente_email,
                                   motivo=pre.motivo, tipo=Visita.PREREG, creata_da="PREREG")
        pre.usata_il, pre.visita = timezone.now(), visita
        pre.save(update_fields=["usata_il", "visita"])
    return visita


def visite_oltre_conservazione(mesi: int, oggi=None):
    """Visite concluse più vecchie di ``mesi``: sono quelle da cancellare."""
    limite = (oggi or timezone.now()) - timedelta(days=round(mesi * 365 / 12))
    return Visita.objects.filter(~Q(stato=Visita.DENTRO), Q(ingresso__lt=limite) | Q(ingresso__isnull=True, creata_il__lt=limite))


@transaction.atomic
def pulizia_conservazione(mesi: int, oggi=None) -> dict:
    """Cancella visite, correzioni e pre-registrazioni oltre il termine, e gli ospiti rimasti senza visite."""
    limite = (oggi or timezone.now()) - timedelta(days=round(mesi * 365 / 12))
    visite = visite_oltre_conservazione(mesi, oggi)
    ids = list(visite.values_list("pk", flat=True))
    n_eventi = 0
    # A blocchi: SQL Server accetta al massimo 2100 parametri per istruzione.
    for i in range(0, len(ids), 1000):
        blocco = ids[i:i + 1000]
        n_eventi += EventoVisita.objects.filter(visita_id_rif__in=blocco).delete()[0]
        Preregistrazione.objects.filter(visita_id__in=blocco).delete()
        Visita.objects.filter(pk__in=blocco).delete()
    n_pre = Preregistrazione.objects.filter(scade_il__lt=limite).delete()[0]
    n_ospiti = Ospite.objects.filter(visite__isnull=True, creato_il__lt=limite).delete()[0]
    return {"visite": len(ids), "correzioni": n_eventi, "preregistrazioni": n_pre, "ospiti": n_ospiti}


def pulizia_preregistrazioni(oggi=None) -> int:
    """Pre-registrazioni mai usate con la visita ormai passata."""
    oggi = oggi or timezone.localdate()
    return Preregistrazione.objects.filter(usata_il__isnull=True, data_visita__lt=oggi).delete()[0]


# --- Pre-registrazioni e richieste di appuntamento ---------------------------------------------


def crea_preregistrazione(*, ospite_nome: str, ospite_email: str, referente: Referente, creata_da: str,
                          ospite_azienda: str = "", motivo: str = "", data_visita=None, ora_inizio=None,
                          ora_fine=None, scade_il=None) -> Preregistrazione:
    """Unico punto che crea le pre-registrazioni: pannello, «Annuncia una visita», richieste approvate.

    Senza scadenza vale fino a fine giornata della visita, o ``GIORNI_VALIDITA_CODICE`` giorni.
    """
    if scade_il is None:
        if data_visita:
            scade_il = timezone.make_aware(datetime.combine(data_visita, datetime.max.time().replace(microsecond=0)))
        else:
            scade_il = timezone.now() + timedelta(days=GIORNI_VALIDITA_CODICE)
    return Preregistrazione.objects.create(
        codice=nuovo_codice(), ospite_nome=ospite_nome.strip()[:200], ospite_email=ospite_email.strip().lower()[:255],
        ospite_azienda=(ospite_azienda or "").strip()[:200], referente_nome=referente.nome_elenco,
        referente_email=referente.email, motivo=(motivo or "")[:500], creata_da=(creata_da or "")[:100],
        scade_il=scade_il, data_visita=data_visita, ora_inizio=ora_inizio, ora_fine=ora_fine,
    )


def referente_per_utente(user, *, crea: bool = False) -> Referente | None:
    """Il referente che corrisponde all'utente collegato, per email. ``crea``: lo aggiunge all'elenco."""
    email = (getattr(user, "email", "") or "").strip().lower()
    if "@" not in email:
        return None
    referente = Referente.objects.filter(email__iexact=email).first()
    if referente is None and crea:
        nome = (getattr(user, "first_name", "") or "").strip() or user.get_username()
        referente = Referente.objects.create(nome=nome[:100], cognome=(getattr(user, "last_name", "") or "").strip()[:100],
                                             email=email[:255])
    return referente


def trova_referente(testo: str) -> Referente | None:
    """Il referente scritto dall'esterno, solo se non ci sono dubbi: email esatta, o nome e cognome di uno solo."""
    testo = " ".join((testo or "").split()).lower()
    if not testo:
        return None
    attivi = Referente.objects.filter(attivo=True)
    if "@" in testo:
        return attivi.filter(email__iexact=testo).first()
    parole = set(testo.split())
    if len(parole) < 2:
        return None
    filtro = Q()
    for parola in parole:
        filtro |= Q(cognome__iexact=parola) | Q(nome__iexact=parola)
    candidati = [r for r in attivi.filter(filtro)
                 if set(f"{r.nome} {r.cognome}".lower().split()) == parole]
    return candidati[0] if len(candidati) == 1 else None


def nuova_richiesta(*, nome: str, cognome: str, email: str, data_visita, referente_indicato: str, azienda: str = "",
                    telefono: str = "", ora_inizio=None, motivo: str = "", messaggio: str = "", ip: str = "") -> RichiestaAppuntamento:
    email = email.strip().lower()
    aperte = RichiestaAppuntamento.objects.filter(
        email__iexact=email, stato__in=[RichiestaAppuntamento.DA_CONFERMARE, RichiestaAppuntamento.IN_ATTESA]).count()
    if aperte >= MAX_RICHIESTE_APERTE_PER_EMAIL:
        raise OperazioneNonValida("Ci sono già richieste in attesa con questa email: aspetti la risposta prima di farne altre.")
    return RichiestaAppuntamento.objects.create(
        nome=nome.strip()[:100], cognome=cognome.strip()[:100], email=email[:255], azienda=azienda.strip()[:200],
        telefono=telefono.strip()[:50], data_visita=data_visita, ora_inizio=ora_inizio, motivo=motivo[:200],
        messaggio=messaggio.strip()[:1000], referente_indicato=referente_indicato.strip()[:200],
        token=secrets.token_urlsafe(32), ip=ip[:45], informativa_letta_il=timezone.now(),
    )


def richiesta_da_confermare(token: str) -> RichiestaAppuntamento | None:
    limite = timezone.now() - timedelta(hours=ORE_CONFERMA_RICHIESTA)
    return RichiestaAppuntamento.objects.filter(token=token or "-", stato=RichiestaAppuntamento.DA_CONFERMARE,
                                                creata_il__gte=limite).first()


def conferma_richiesta(token: str) -> RichiestaAppuntamento | None:
    """L'esterno ha confermato l'email: passa a «Da decidere» e cerca il referente. ``None`` se non vale più."""
    with transaction.atomic():
        trovata = richiesta_da_confermare(token)
        if trovata is None:
            return None
        richiesta = RichiestaAppuntamento.objects.select_for_update().get(pk=trovata.pk)
        if richiesta.stato != RichiestaAppuntamento.DA_CONFERMARE:
            return None
        richiesta.stato, richiesta.confermata_il = RichiestaAppuntamento.IN_ATTESA, timezone.now()
        richiesta.referente = trova_referente(richiesta.referente_indicato)
        richiesta.save(update_fields=["stato", "confermata_il", "referente"])
    return richiesta


def approva_richiesta(richiesta_id: int, *, autore: str, referente: Referente | None = None,
                      ora_inizio=None, nota: str = "") -> RichiestaAppuntamento:
    with transaction.atomic():
        richiesta = RichiestaAppuntamento.objects.select_for_update().get(pk=richiesta_id)
        if richiesta.stato != RichiestaAppuntamento.IN_ATTESA:
            raise OperazioneNonValida("La richiesta è già stata decisa.")
        referente = referente or richiesta.referente
        if referente is None:
            raise OperazioneNonValida("Scegli il referente prima di approvare.")
        richiesta.preregistrazione = crea_preregistrazione(
            ospite_nome=richiesta.nome_completo, ospite_email=richiesta.email, ospite_azienda=richiesta.azienda,
            referente=referente, creata_da=autore, motivo=richiesta.motivo, data_visita=richiesta.data_visita,
            ora_inizio=ora_inizio or richiesta.ora_inizio,
        )
        richiesta.referente, richiesta.stato = referente, RichiestaAppuntamento.APPROVATA
        richiesta.decisa_il, richiesta.decisa_da, richiesta.nota_decisione = timezone.now(), autore[:150], nota.strip()[:500]
        richiesta.save()
    return richiesta


def rifiuta_richiesta(richiesta_id: int, *, autore: str, nota: str = "") -> RichiestaAppuntamento:
    with transaction.atomic():
        richiesta = RichiestaAppuntamento.objects.select_for_update().get(pk=richiesta_id)
        if richiesta.stato != RichiestaAppuntamento.IN_ATTESA:
            raise OperazioneNonValida("La richiesta è già stata decisa.")
        richiesta.stato = RichiestaAppuntamento.RIFIUTATA
        richiesta.decisa_il, richiesta.decisa_da, richiesta.nota_decisione = timezone.now(), autore[:150], nota.strip()[:500]
        richiesta.save(update_fields=["stato", "decisa_il", "decisa_da", "nota_decisione"])
    return richiesta


def pulizia_richieste(adesso=None) -> int:
    """Non confermate dopo 48 ore, decise dopo 30 giorni, in attesa a 7 giorni dal giorno chiesto."""
    adesso = adesso or timezone.now()
    oggi = timezone.localdate(adesso)
    return RichiestaAppuntamento.objects.filter(
        Q(stato=RichiestaAppuntamento.DA_CONFERMARE, creata_il__lt=adesso - timedelta(hours=ORE_CONFERMA_RICHIESTA))
        | Q(decisa_il__lt=adesso - timedelta(days=GIORNI_CONSERVAZIONE_RICHIESTE))
        | Q(stato=RichiestaAppuntamento.IN_ATTESA, data_visita__lt=oggi - timedelta(days=7))
    ).delete()[0]
