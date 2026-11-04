"""Ingressi delle ditte esterne (GuestPortal) collegati a ticket e ordini di lavoro.

Flusso: la ditta delegata (``Ticket.delegato_fornitore`` / ``WorkOrder.supplier``)
entra dal chiosco → l'HUB propone gli ingressi della ditta nel periodo
dell'intervento → un utente conferma con «Collega». Al collegamento si salva la
fotografia dell'ingresso (giorno, entrata, uscita, tecnico): resta anche quando il
GuestPortal cancella le visite vecchie.

La ditta di un ingresso si riconosce dall'abbinamento ``DittaGuestPortal``
(fornitore del GuestPortal → fornitore HUB) oppure dall'azienda scritta dal
visitatore uguale alla ragione sociale del fornitore HUB.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import guestportal as gp
from .models import DittaGuestPortal, IngressoIntervento

TIPO_TICKET = "ticket"
TIPO_ODL = "odl"
TIPI = (TIPO_TICKET, TIPO_ODL)
FINESTRA_MAX_GIORNI = 90
TOLLERANZA_MINUTI = 15


@dataclass
class Intervento:
    """Ticket o OdL visto in modo uniforme dal collegamento."""

    tipo: str
    oggetto: object

    @property
    def pk(self) -> int:
        return self.oggetto.pk

    @property
    def fornitore(self):
        if self.tipo == TIPO_TICKET:
            return self.oggetto.delegato_fornitore
        return self.oggetto.supplier

    @property
    def etichetta(self) -> str:
        if self.tipo == TIPO_TICKET:
            return self.oggetto.numero_ticket or f"Ticket #{self.oggetto.pk}"
        return f"OdL #{self.oggetto.display_number}"

    @property
    def chiuso(self) -> bool:
        if self.tipo == TIPO_TICKET:
            return bool(self.oggetto.is_chiuso)
        return self.oggetto.status != self.oggetto.STATUS_OPEN

    def finestra(self) -> tuple[date, date]:
        """Periodo in cui cercare gli ingressi: dall'apertura (un giorno prima) alla
        chiusura o a oggi, al massimo 90 giorni."""
        o = self.oggetto
        inizio = o.created_at if self.tipo == TIPO_TICKET else o.opened_at
        fine = o.closed_at
        oggi = timezone.localdate()
        al = timezone.localtime(fine).date() if fine else oggi
        al = min(al, oggi)
        dal = (timezone.localtime(inizio).date() if inizio else al) - timedelta(days=1)
        if (al - dal).days > FINESTRA_MAX_GIORNI:
            dal = al - timedelta(days=FINESTRA_MAX_GIORNI)
        return dal, al

    def collegamenti(self):
        filtro = {"ticket": self.oggetto} if self.tipo == TIPO_TICKET else {"work_order": self.oggetto}
        return IngressoIntervento.objects.filter(**filtro).select_related("collegato_da")


def intervento(tipo: str, pk: int) -> Intervento | None:
    if tipo == TIPO_TICKET:
        from tickets.models import Ticket

        oggetto = Ticket.objects.select_related("delegato_fornitore").filter(pk=pk).first()
    elif tipo == TIPO_ODL:
        from assets.models import WorkOrder

        oggetto = WorkOrder.objects.select_related("supplier").filter(pk=pk).first()
    else:
        return None
    return Intervento(tipo, oggetto) if oggetto else None


def ditte_gp_del_fornitore(fornitore) -> list[int]:
    if fornitore is None:
        return []
    return list(DittaGuestPortal.objects.filter(fornitore=fornitore).values_list("ditta_gp_id", flat=True))


def proposte(iv: Intervento) -> list[gp.Accesso]:
    """Ingressi della ditta delegata nel periodo dell'intervento, non ancora collegati."""
    fornitore = iv.fornitore
    if fornitore is None:
        return []
    dal, al = iv.finestra()
    righe = gp.ingressi_ditta(
        ditte_gp=ditte_gp_del_fornitore(fornitore), nomi=[fornitore.ragione_sociale], dal=dal, al=al,
    )
    gia = set(iv.collegamenti().values_list("visita_gp_id", flat=True))
    return [a for a in righe if a.visita_id not in gia]


def ingressi_del_giorno(iv: Intervento, giorno: date) -> list[gp.Accesso]:
    """Tutti gli ingressi esterni di un giorno (collegamento a mano), esclusi i già collegati."""
    righe, _ = gp.storico(dal=giorno, al=giorno)
    gia = set(iv.collegamenti().values_list("visita_gp_id", flat=True))
    return [a for a in righe if a.visita_id not in gia]


def _aware(valore: datetime | None) -> datetime | None:
    if valore is None:
        return None
    if timezone.is_naive(valore):
        return timezone.make_aware(valore, timezone.get_current_timezone())
    return valore


class CollegamentoNonValido(Exception):
    pass


def collega(iv: Intervento, visita_id: int, *, utente, modo: str) -> IngressoIntervento:
    """Collega una visita all'intervento salvando la fotografia dell'ingresso.

    La visita si rilegge dal GuestPortal: non ci si fida dei dati del form.
    """
    if iv.chiuso:
        raise CollegamentoNonValido("L'intervento è chiuso: non si possono più collegare ingressi.")
    accesso = gp.visita(visita_id)
    if accesso is None:
        raise CollegamentoNonValido("Ingresso non trovato nel GuestPortal (forse già cancellato).")
    if accesso.nome == "Ospite anonimizzato":
        raise CollegamentoNonValido("Ingresso già anonimizzato nel GuestPortal: non si può collegare.")
    fornitore = None
    if accesso.ditta_gp_id:
        abbinata = DittaGuestPortal.objects.filter(ditta_gp_id=accesso.ditta_gp_id).select_related("fornitore").first()
        fornitore = abbinata.fornitore if abbinata else None
    if fornitore is None and iv.fornitore is not None and \
            accesso.azienda.strip().lower() == (iv.fornitore.ragione_sociale or "").strip().lower():
        fornitore = iv.fornitore
    dati = {
        "visita_gp_id": accesso.visita_id,
        "fornitore": fornitore,
        "ingresso": _aware(accesso.ingresso),
        "uscita": _aware(accesso.uscita),
        "tecnico_nome": accesso.nome[:200],
        "azienda": accesso.azienda[:200],
        "badge": accesso.badge[:20],
        "modo": modo if modo in dict(IngressoIntervento.MODO_CHOICES) else IngressoIntervento.MODO_MANUALE,
        "collegato_da": utente if getattr(utente, "is_authenticated", False) else None,
    }
    if iv.tipo == TIPO_TICKET:
        dati["ticket"] = iv.oggetto
    else:
        dati["work_order"] = iv.oggetto
    try:
        with transaction.atomic():
            return IngressoIntervento.objects.create(**dati)
    except IntegrityError as exc:
        raise CollegamentoNonValido("Ingresso già collegato a questo intervento.") from exc


def aggiorna_uscite(iv: Intervento) -> int:
    """Completa l'uscita dei collegamenti fatti mentre il tecnico era ancora dentro.
    Silenzioso se il GuestPortal non risponde."""
    aggiornati = 0
    for link in iv.collegamenti().filter(uscita__isnull=True):
        try:
            accesso = gp.visita(link.visita_gp_id)
        except (gp.GuestPortalNonConfigurato, gp.GuestPortalNonRaggiungibile):
            return aggiornati
        if accesso and accesso.uscita:
            link.uscita = _aware(accesso.uscita)
            link.save(update_fields=["uscita", "aggiornato_il"])
            aggiornati += 1
    return aggiornati


@dataclass
class ConfrontoOre:
    presenza_minuti: int
    dichiarate_minuti: int | None
    ingressi_aperti: int

    @property
    def scarto_minuti(self) -> int | None:
        if self.dichiarate_minuti is None:
            return None
        return self.dichiarate_minuti - self.presenza_minuti

    @property
    def da_controllare(self) -> bool:
        """Ore dichiarate oltre la presenza in azienda (tolleranza 15 minuti)."""
        scarto = self.scarto_minuti
        return scarto is not None and self.ingressi_aperti == 0 and scarto > TOLLERANZA_MINUTI


def _ore_label(minuti: int | None) -> str:
    if minuti is None:
        return "—"
    return f"{minuti // 60} h {minuti % 60:02d} min"


def confronto_ore(iv: Intervento, collegamenti: list[IngressoIntervento]) -> ConfrontoOre:
    presenza = sum(c.durata_minuti or 0 for c in collegamenti)
    aperti = sum(1 for c in collegamenti if c.ingresso and not c.uscita)
    dichiarate = None
    if iv.tipo == TIPO_TICKET:
        ore = [i.durata_ore for i in iv.oggetto.interventi.all()]
        ore = [o for o in ore if o is not None]
        if ore:
            dichiarate = int(round(sum(ore) * 60))
    return ConfrontoOre(presenza_minuti=presenza, dichiarate_minuti=dichiarate, ingressi_aperti=aperti)


def interventi_per_visite(visita_ids: list[int]) -> dict[int, list[tuple[str, str]]]:
    """Per la pagina Accessi esterni: visita → [(etichetta, url)] degli interventi collegati."""
    from django.urls import reverse

    esito: dict[int, list[tuple[str, str]]] = {}
    if not visita_ids:
        return esito
    righe = IngressoIntervento.objects.filter(visita_gp_id__in=visita_ids).select_related("ticket", "work_order")
    for link in righe:
        if link.ticket_id:
            voce = (link.ticket.numero_ticket or f"Ticket #{link.ticket_id}",
                    reverse("tickets:gestione_detail", args=[link.ticket_id]))
        else:
            voce = (f"OdL #{link.work_order.display_number}", reverse("assets:wo_view", args=[link.work_order_id]))
        esito.setdefault(link.visita_gp_id, []).append(voce)
    return esito


ore_label = _ore_label
