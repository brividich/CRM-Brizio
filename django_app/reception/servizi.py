"""Regole della reception, le stesse del GuestPortal. Unico punto che scrive visite e cartellini."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Cartellino, EventoVisita, Ospite, Preregistrazione, Visita

GIORNI_RIAPERTURA = 7
CARATTERI_CODICE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # niente O, 0, 1, I: si confondono
GIORNI_VALIDITA_CODICE = 7


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
