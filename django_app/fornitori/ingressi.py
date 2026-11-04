"""Ingressi delle ditte esterne (GuestPortal) collegati a ticket e ordini di lavoro.

Flusso: la ditta delegata (``Ticket.delegato_fornitore`` / ``WorkOrder.supplier``)
entra dal chiosco → l'HUB propone gli ingressi della ditta nel periodo
dell'intervento → un utente conferma con «Collega». Al collegamento si salva la
fotografia dell'ingresso (giorno, entrata, uscita, tecnico): resta anche quando il
GuestPortal cancella le visite vecchie.

La ditta di un ingresso si riconosce dall'abbinamento ``DittaGuestPortal``
(fornitore del GuestPortal → fornitore HUB) oppure dall'azienda scritta dal
visitatore uguale alla ragione sociale del fornitore HUB a meno di maiuscole,
punteggiatura e forma giuridica (``fornitori/nomi.py``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import guestportal as gp
from .models import DittaGuestPortal, IngressoIntervento
from .nomi import chiave_ditta, unico

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
    ditte = set(ditte_gp_del_fornitore(fornitore))
    nomi = {fornitore.ragione_sociale}
    # Ditte del GuestPortal con lo stesso nome a meno di forma giuridica e
    # punteggiatura («Rossi Impianti» = «ROSSI IMPIANTI S.R.L.»), se non abbinate
    # a un altro fornitore.
    chiave = chiave_ditta(fornitore.ragione_sociale)
    abbinate_altrove = set(DittaGuestPortal.objects.exclude(fornitore=fornitore).values_list("ditta_gp_id", flat=True))
    for ditta_id, nome in gp.ditte_guestportal():
        if ditta_id not in abbinate_altrove and chiave and chiave_ditta(nome) == chiave:
            ditte.add(ditta_id)
            nomi.add(nome)
    righe = gp.ingressi_ditta(ditte_gp=sorted(ditte), nomi=sorted(nomi), dal=dal, al=al)
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


def fornitore_da_accesso(accesso: gp.Accesso, preferito=None):
    """Fornitore HUB di un ingresso: abbinamento della ditta GuestPortal, altrimenti
    azienda dell'ingresso con lo stesso nome della ragione sociale a meno di
    maiuscole, punteggiatura e forma giuridica (prima ``preferito``, poi l'unico
    fornitore attivo con quel nome). None se non si riconosce o è ambiguo."""
    from anagrafica.models import Fornitore

    if accesso.ditta_gp_id:
        abbinata = DittaGuestPortal.objects.filter(ditta_gp_id=accesso.ditta_gp_id).select_related("fornitore").first()
        if abbinata:
            return abbinata.fornitore
    chiave = chiave_ditta(accesso.azienda)
    if not chiave:
        return None
    if preferito is not None and chiave_ditta(preferito.ragione_sociale) == chiave:
        return preferito
    pk = unico(chiave, Fornitore.objects.filter(is_active=True).values_list("pk", "ragione_sociale"))
    return Fornitore.objects.filter(pk=pk).first() if pk else None


def _imposta_ditta(iv: Intervento, fornitore, *, utente, autore: tuple[str, str] | None) -> str:
    """Se l'intervento non ha ancora una ditta, imposta quella dell'ingresso e lo
    scrive nello storico del ticket/OdL. Ritorna una frase per l'utente ("" se niente)."""
    if fornitore is None or iv.fornitore is not None:
        return ""
    o = iv.oggetto
    nota = (f"Ditta impostata a «{fornitore.ragione_sociale}» collegando l'ingresso "
            "dal GuestPortal (Presenze in azienda).")
    if iv.tipo == TIPO_TICKET:
        from tickets.models import TicketCommento

        o.delegato_fornitore = fornitore
        o.save(update_fields=["delegato_fornitore", "updated_at"])
        nome, email = autore or ("", "")
        TicketCommento.objects.create(
            ticket=o, autore_nome=(nome or getattr(utente, "get_username", lambda: "")() or "HUB")[:200],
            autore_email=(email or "")[:200], testo=nota, is_interno=True,
        )
        return f"Il ticket ora è delegato a «{fornitore.ragione_sociale}»."
    from assets.models import WorkOrderLog

    campi = ["supplier"]
    o.supplier = fornitore
    if o.execution_mode != o.EXECUTION_EXTERNAL:
        o.execution_mode = o.EXECUTION_EXTERNAL
        campi.append("execution_mode")
        nota += " Esecuzione passata a Esterna."
    o.save(update_fields=campi)
    WorkOrderLog.objects.create(
        work_order=o, note=nota, author=utente if getattr(utente, "is_authenticated", False) else None,
    )
    return f"L'OdL ora è eseguito da «{fornitore.ragione_sociale}» (Esterna)."


def collega(
    iv: Intervento,
    visita_id: int,
    *,
    utente,
    modo: str,
    imposta_ditta: bool = True,
    autore: tuple[str, str] | None = None,
) -> IngressoIntervento:
    """Collega una visita all'intervento salvando la fotografia dell'ingresso.

    La visita si rilegge dal GuestPortal: non ci si fida dei dati del form. Se
    l'intervento non ha ancora una ditta e quella dell'ingresso si riconosce, la
    imposta (``link.nota_ditta`` dice cosa è cambiato).
    """
    if iv.chiuso:
        raise CollegamentoNonValido("L'intervento è chiuso: non si possono più collegare ingressi.")
    accesso = gp.visita(visita_id)
    if accesso is None:
        raise CollegamentoNonValido("Ingresso non trovato nel GuestPortal (forse già cancellato).")
    if accesso.nome == "Ospite anonimizzato":
        raise CollegamentoNonValido("Ingresso già anonimizzato nel GuestPortal: non si può collegare.")
    fornitore = fornitore_da_accesso(accesso, preferito=iv.fornitore)
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
            link = IngressoIntervento.objects.create(**dati)
            link.nota_ditta = _imposta_ditta(iv, fornitore, utente=utente, autore=autore) if imposta_ditta else ""
            return link
    except IntegrityError as exc:
        raise CollegamentoNonValido("Ingresso già collegato a questo intervento.") from exc


def fornitore_del_collegamento(link: IngressoIntervento, preferito=None):
    """Fornitore HUB riconosciuto oggi per un ingresso già collegato: rilegge la
    visita (abbinamento della ditta GuestPortal fatto dopo il collegamento), se il
    GuestPortal non la ha più o non risponde usa l'azienda fotografata."""
    if link.fornitore_id:
        return link.fornitore
    accesso = None
    try:
        accesso = gp.visita(link.visita_gp_id)
    except (gp.GuestPortalNonConfigurato, gp.GuestPortalNonRaggiungibile):
        accesso = None
    if accesso is None or accesso.nome == "Ospite anonimizzato":
        accesso = gp.Accesso(
            visita_id=link.visita_gp_id, stato="", tipo="", nome=link.tecnico_nome, azienda=link.azienda,
            referente="", motivo="", badge=link.badge, ingresso=None, uscita=None,
        )
    return fornitore_da_accesso(accesso, preferito=preferito)


def ditta_dai_collegamenti(iv: Intervento, collegamenti: list[IngressoIntervento]):
    """Per un intervento senza ditta: ``(fornitore, link)`` del primo ingresso
    collegato la cui ditta oggi si riconosce, altrimenti None."""
    if iv.fornitore is not None:
        return None
    for link in collegamenti:
        fornitore = fornitore_del_collegamento(link)
        if fornitore is not None:
            return fornitore, link
    return None


def imposta_ditta_da_collegamento(iv: Intervento, link: IngressoIntervento, *, utente, autore=None) -> str:
    """Imposta sull'intervento la ditta di un ingresso già collegato (abbinamento o
    fornitore creati dopo il collegamento). Ritorna la frase per l'utente."""
    if iv.chiuso:
        raise CollegamentoNonValido("L'intervento è chiuso.")
    if iv.fornitore is not None:
        raise CollegamentoNonValido("L'intervento ha già una ditta.")
    fornitore = fornitore_del_collegamento(link)
    if fornitore is None:
        raise CollegamentoNonValido("La ditta dell'ingresso non corrisponde a nessun fornitore dell'HUB.")
    with transaction.atomic():
        if not link.fornitore_id:
            link.fornitore = fornitore
            link.save(update_fields=["fornitore", "aggiornato_il"])
        return _imposta_ditta(iv, fornitore, utente=utente, autore=autore)


ODL_MAX_ELENCO = 300


def interventi_aperti(request, *, testo: str = "", fornitore=None) -> list[Intervento]:
    """Ticket MAN e OdL aperti a cui l'utente può collegare un ingresso, per il
    collegamento partendo dall'ingresso. Prima quelli della stessa ditta."""
    from django.db.models import Q

    from assets.models import WorkOrder
    from tickets.models import StatoTicket, Ticket, TipoTicket

    testo = (testo or "").strip()
    esito: list[Intervento] = []

    tickets = Ticket.objects.filter(tipo=TipoTicket.MAN).exclude(
        stato__in=[StatoTicket.CHIUSO, StatoTicket.ANNULLATO]
    ).select_related("delegato_fornitore")
    if testo:
        tickets = tickets.filter(Q(numero_ticket__icontains=testo) | Q(titolo__icontains=testo))
    from tickets.services.accesso import utente_puo_gestire_ticket

    for t in tickets.order_by("-created_at")[:200]:
        if utente_puo_gestire_ticket(request, t):
            esito.append(Intervento(TIPO_TICKET, t))

    if puo_collegare_odl(request):
        odl = WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN).select_related("asset", "supplier")
        if testo:
            filtro = Q(title__icontains=testo) | Q(asset__name__icontains=testo) | Q(asset__asset_tag__icontains=testo)
            if testo.isdigit():
                filtro |= Q(pk=int(testo))
            odl = odl.filter(filtro)
        esito.extend(Intervento(TIPO_ODL, w) for w in odl.order_by("-opened_at")[:ODL_MAX_ELENCO])

    if fornitore is not None:
        esito.sort(key=lambda iv: 0 if (iv.fornitore and iv.fornitore.pk == fornitore.pk) else 1)
    return esito


def puo_collegare_odl(request) -> bool:
    """Stessa regola del riquadro nell'OdL: apre le schede OdL ed esegue le manutenzioni."""
    from django.urls import reverse

    from assets.views_maintenance import can_execute_maintenance
    from core.middleware import acl_allows_path

    try:
        percorso = reverse("assets:wo_view", args=[0])
    except Exception:
        return False
    vede = acl_allows_path(percorso, django_user=request.user,
                           legacy_user=getattr(request, "legacy_user", None), request=request)
    return bool(vede and can_execute_maintenance(request))


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
