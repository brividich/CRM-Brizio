"""Gruppi di ospiti: i partecipanti entrano ed escono con il capogruppo.

Agganci (in ``servizi``): ``ingresso_da_codice`` → l'invito usato porta dentro i suoi partecipanti;
``registra_ingresso`` dal chiosco o dal pannello → se oggi c'è un invito con partecipanti per la stessa
persona (email o nome e cognome), lo usa; ``registra_uscita`` del capogruppo → escono anche i partecipanti
ancora dentro. Un problema con un partecipante non blocca mai l'ingresso o l'uscita del capogruppo.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Ospite, PartecipanteGruppo, Preregistrazione, Visita

log = logging.getLogger(__name__)


def _ospite(p: PartecipanteGruppo) -> Ospite:
    from . import servizi

    try:
        return servizi.ospite_da_dati(nome=p.nome, cognome=p.cognome, email=p.email, telefono=p.telefono, azienda=p.azienda)
    except servizi.EmailDiAltri:
        # L'email nel frattempo è di un'altra persona: entra lo stesso, senza email.
        return servizi.ospite_da_dati(nome=p.nome, cognome=p.cognome, telefono=p.telefono, azienda=p.azienda)


def entra_gruppo(capo: Visita, partecipanti) -> dict:
    """Registra l'ingresso dei partecipanti non ancora entrati con referente e motivo del capogruppo."""
    from . import servizi

    esito = {"entrati": 0, "gia_dentro": 0}
    for p in partecipanti.filter(visita__isnull=True):
        with transaction.atomic():
            ospite = _ospite(p)
            try:
                visita = servizi.registra_ingresso(
                    ospite, referente_nome=capo.referente_nome, referente_email=capo.referente_email, motivo=capo.motivo,
                    creata_da="GRUPPO", cartellino=None if p.con_cartellino else "", invia_mail=False,
                )
                esito["entrati"] += 1
            except servizi.CartelliniFiniti:
                visita = servizi.registra_ingresso(
                    ospite, referente_nome=capo.referente_nome, referente_email=capo.referente_email, motivo=capo.motivo,
                    creata_da="GRUPPO", cartellino="", invia_mail=False,
                )
                esito["entrati"] += 1
            except servizi.GiaDentro:
                visita = Visita.objects.filter(ospite=ospite, stato=Visita.DENTRO).order_by("-ingresso").first()
                esito["gia_dentro"] += 1
            p.visita, p.visita_capo = visita, capo
            p.save(update_fields=["visita", "visita_capo"])
    return esito


def esci_gruppo(capo: Visita, *, autore: str = "", ip: str = "") -> int:
    """Uscita dei partecipanti ancora dentro, alla stessa ora del capogruppo."""
    from . import servizi

    n = 0
    ids = PartecipanteGruppo.objects.filter(visita_capo=capo, visita__stato=Visita.DENTRO).values_list("visita_id", flat=True)
    for visita_id in list(ids):
        try:
            servizi.registra_uscita(visita_id, quando=capo.uscita, autore=autore, ip=ip, origine="GRUPPO")
            n += 1
        except servizi.OperazioneNonValida:
            continue
    return n


def invito_del_giorno(ospite: Ospite) -> Preregistrazione | None:
    """L'invito di oggi, non ancora usato e con partecipanti, che corrisponde a questa persona."""
    nome, cognome = ospite.nome.strip(), ospite.cognome.strip()
    chi = Q(ospite_nome__iexact=f"{nome} {cognome}") | Q(ospite_nome__iexact=f"{cognome} {nome}")
    if ospite.email:
        chi |= Q(ospite_email__iexact=ospite.email)
    return (Preregistrazione.objects.filter(chi, usata_il__isnull=True, scade_il__gte=timezone.now(),
                                            data_visita=timezone.localdate(), partecipanti__isnull=False)
            .distinct().order_by("ora_inizio", "pk").first())


def dopo_ingresso(visita: Visita) -> None:
    """Gancio di ``registra_ingresso``: chi entra senza codice ma ha un invito di gruppo per oggi."""
    if visita.creata_da in ("PREREG", "GRUPPO", "IMPORT"):
        return
    try:
        with transaction.atomic():
            pre = invito_del_giorno(visita.ospite)
            if pre is None:
                return
            pre = Preregistrazione.objects.select_for_update().get(pk=pre.pk)
            if pre.usata_il:
                return
            pre.usata_il, pre.visita = timezone.now(), visita
            pre.save(update_fields=["usata_il", "visita"])
            entra_gruppo(visita, pre.partecipanti.all())
    except Exception:  # noqa: BLE001 - l'ingresso del capogruppo resta comunque valido
        log.exception("Reception: ingresso del gruppo non riuscito per la visita %s", visita.pk)


def dopo_codice(pre: Preregistrazione, visita: Visita) -> None:
    try:
        if pre.partecipanti.exists():
            entra_gruppo(visita, pre.partecipanti.all())
    except Exception:  # noqa: BLE001
        log.exception("Reception: ingresso del gruppo non riuscito per l'invito %s", pre.pk)


def dopo_uscita(visita: Visita, *, autore: str = "", ip: str = "") -> None:
    try:
        esci_gruppo(visita, autore=autore, ip=ip)
    except Exception:  # noqa: BLE001
        log.exception("Reception: uscita del gruppo non riuscita per la visita %s", visita.pk)


def partecipanti_di(*, preregistrazione: Preregistrazione | None = None, visita_capo: Visita | None = None):
    """Il gruppo di un invito o di una visita (anche quelli dell'invito che l'ha aperta)."""
    if preregistrazione is not None:
        return PartecipanteGruppo.objects.filter(preregistrazione=preregistrazione).select_related("visita")
    q = Q(visita_capo=visita_capo)
    pre_ids = list(Preregistrazione.objects.filter(visita=visita_capo).values_list("pk", flat=True))
    if pre_ids:
        q |= Q(preregistrazione_id__in=pre_ids)
    return PartecipanteGruppo.objects.filter(q).select_related("visita")
