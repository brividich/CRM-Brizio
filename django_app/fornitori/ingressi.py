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

Le sessioni formative (``anagrafica.TrainingSession``) usano lo stesso
collegamento per l'ingresso del docente esterno: le proposte sono gli ingressi
nel periodo della sessione con il nome del docente o l'azienda dell'ente di
formazione; non c'è nessuna ditta da impostare.
"""
from __future__ import annotations

import logging

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import guestportal as gp
from .models import DittaGuestPortal, IngressoIntervento, TecnicoFornitore
from .nomi import chiave_ditta, chiave_persona, unico

logger = logging.getLogger(__name__)

TIPO_TICKET = "ticket"
TIPO_ODL = "odl"
TIPO_FORMAZIONE = "formazione"
TIPO_ORDINARIA = "ordinaria"
TIPO_AMMINISTRATIVA = "amministrativa"
TIPO_SCADENZA = "scadenza"
TIPI = (TIPO_TICKET, TIPO_ODL, TIPO_ORDINARIA, TIPO_AMMINISTRATIVA, TIPO_SCADENZA)  # interventi con una ditta
TIPI_TUTTI = (*TIPI, TIPO_FORMAZIONE)
FINESTRA_MAX_GIORNI = 90
TOLLERANZA_MINUTI = 15
GIORNI_PROPOSTE_SCADENZE = 30
ELENCO_MAX_SCADENZE = 200
GIORNI_PRIMA_ELENCO = 60
GIORNI_DOPO_ELENCO = 60
_CAMPI_DESTINAZIONE = {
    TIPO_TICKET: "ticket", TIPO_ODL: "work_order", TIPO_FORMAZIONE: "sessione_formazione",
    TIPO_ORDINARIA: "occorrenza", TIPO_AMMINISTRATIVA: "scadenza_asset", TIPO_SCADENZA: "scadenza",
}
_NON_LETTA = object()


@dataclass
class Intervento:
    """Ticket o OdL visto in modo uniforme dal collegamento."""

    tipo: str
    oggetto: object
    ditta_letta: object = field(default=_NON_LETTA, repr=False)

    @property
    def pk(self) -> int:
        return self.oggetto.pk

    @property
    def formazione(self) -> bool:
        return self.tipo == TIPO_FORMAZIONE

    @property
    def fornitore(self):
        if self.tipo == TIPO_TICKET:
            return self.oggetto.delegato_fornitore
        if self.tipo in (TIPO_ODL, TIPO_ORDINARIA):
            return self.oggetto.supplier
        if self.tipo == TIPO_SCADENZA:
            return self.oggetto.fornitore
        if self.tipo == TIPO_AMMINISTRATIVA:
            # L'ente è un testo: vale la stessa ragione sociale, se è di un solo fornitore.
            if self.ditta_letta is _NON_LETTA:
                self.ditta_letta = _fornitore_con_nome(self.oggetto.issuer)
            return self.ditta_letta
        return None

    @property
    def puo_prendere_ditta(self) -> bool:
        """Senza ditta e con un posto libero: un ente già scritto a mano non si sovrascrive."""
        if self.tipo not in TIPI or self.fornitore is not None:
            return False
        return not (self.tipo == TIPO_AMMINISTRATIVA and self.oggetto.issuer.strip())

    @property
    def dove_la_ditta(self) -> str:
        return {TIPO_TICKET: "delegata", TIPO_ODL: "dell'OdL", TIPO_ORDINARIA: "della manutenzione"}.get(
            self.tipo, "della scadenza",
        )

    @property
    def etichetta(self) -> str:
        if self.tipo == TIPO_TICKET:
            return self.oggetto.numero_ticket or f"Ticket #{self.oggetto.pk}"
        if self.tipo == TIPO_ODL:
            return f"OdL #{self.oggetto.display_number}"
        if self.tipo == TIPO_ORDINARIA:
            return self.oggetto.plan.label
        if self.tipo == TIPO_AMMINISTRATIVA:
            return self.oggetto.title
        if self.tipo == TIPO_SCADENZA:
            return self.oggetto.titolo
        return f"Sessione {self.oggetto.codice_sessione}"

    @property
    def tipo_label(self) -> str:
        return {
            TIPO_TICKET: "Ticket", TIPO_ODL: "OdL", TIPO_FORMAZIONE: "Formazione", TIPO_ORDINARIA: "Manutenzione",
            TIPO_AMMINISTRATIVA: "Scadenza asset", TIPO_SCADENZA: "Scadenzario",
        }[self.tipo]

    @property
    def titolo(self) -> str:
        o = self.oggetto
        if self.tipo == TIPO_TICKET:
            return o.titolo
        if self.tipo == TIPO_ODL:
            return f"{o.title} · {o.asset.name}" if o.asset_id else o.title
        if self.tipo in (TIPO_ORDINARIA, TIPO_AMMINISTRATIVA):
            return o.asset.name
        if self.tipo == TIPO_SCADENZA:
            return o.categoria.nome
        return o.corso.titolo

    @property
    def aperto_il(self):
        o = self.oggetto
        if self.tipo == TIPO_TICKET:
            return o.created_at
        if self.tipo == TIPO_ODL:
            return o.opened_at
        if self.tipo in (TIPO_ORDINARIA, TIPO_AMMINISTRATIVA):
            return o.due_date
        if self.tipo == TIPO_SCADENZA:
            return o.data_scadenza
        return o.data_inizio

    @property
    def url(self) -> str:
        from django.urls import reverse

        if self.tipo == TIPO_TICKET:
            return reverse("tickets:gestione_detail", args=[self.pk])
        if self.tipo == TIPO_ODL:
            return reverse("assets:wo_view", args=[self.pk])
        if self.tipo == TIPO_ORDINARIA:
            # Da eseguita la pagina di registrazione non si apre più: resta la scheda dell'asset.
            if self.oggetto.status == self.oggetto.STATUS_OPEN:
                return reverse("assets:occurrence_complete", args=[self.pk])
            return reverse("assets:asset_view", args=[self.oggetto.asset_id])
        if self.tipo == TIPO_AMMINISTRATIVA:
            return reverse("assets:asset_administrative_deadline_edit", args=[self.pk])
        if self.tipo == TIPO_SCADENZA:
            return reverse("scadenzario:scadenza_dettaglio", args=[self.pk])
        return reverse("anagrafica:formazione_sessione_detail", args=[self.pk])

    @property
    def chi(self) -> str:
        """Ditta (ticket/OdL) o docente/ente (sessione) per gli elenchi."""
        if self.formazione:
            return self.oggetto.erogatore_display or ""
        if self.fornitore:
            return self.fornitore.ragione_sociale
        return self.oggetto.issuer if self.tipo == TIPO_AMMINISTRATIVA else ""

    @property
    def chiuso(self) -> bool:
        if self.tipo == TIPO_TICKET:
            return bool(self.oggetto.is_chiuso)
        if self.tipo == TIPO_ODL:
            return self.oggetto.status != self.oggetto.STATUS_OPEN
        if self.tipo == TIPO_ORDINARIA:
            # Eseguita resta collegabile: spesso l'ingresso si collega dopo aver registrato il lavoro.
            return self.oggetto.status == self.oggetto.STATUS_CANCELED
        if self.tipo in (TIPO_AMMINISTRATIVA, TIPO_SCADENZA):
            return not self.oggetto.is_active
        # Sessione: l'ingresso del docente si collega anche a edizione chiusa o
        # approvata (è una prova di presenza, non tocca il registro); non se annullata.
        return self.oggetto.stato == "ANNULLATA"

    def finestra(self) -> tuple[date, date]:
        """Periodo in cui cercare gli ingressi: dall'apertura (un giorno prima) alla
        chiusura o a oggi, al massimo 90 giorni. Sessione: dal giorno prima
        dell'inizio alla fine (o a oggi)."""
        o = self.oggetto
        oggi = timezone.localdate()
        if self.formazione:
            al = min(o.data_fine, oggi)
            dal = min(o.data_inizio - timedelta(days=1), al)
            if (al - dal).days > FINESTRA_MAX_GIORNI:
                dal = al - timedelta(days=FINESTRA_MAX_GIORNI)
            return dal, al
        if self.tipo in (TIPO_ORDINARIA, TIPO_AMMINISTRATIVA, TIPO_SCADENZA):
            # Queste non hanno una data di apertura: gli ultimi giorni, fino all'esecuzione se c'è.
            al = min(getattr(o, "completed_on", None) or oggi, oggi)
            return al - timedelta(days=GIORNI_PROPOSTE_SCADENZE), al
        inizio = o.created_at if self.tipo == TIPO_TICKET else o.opened_at
        fine = o.closed_at
        al = timezone.localtime(fine).date() if fine else oggi
        al = min(al, oggi)
        dal = (timezone.localtime(inizio).date() if inizio else al) - timedelta(days=1)
        if (al - dal).days > FINESTRA_MAX_GIORNI:
            dal = al - timedelta(days=FINESTRA_MAX_GIORNI)
        return dal, al

    def collegamenti(self):
        filtro = {_CAMPI_DESTINAZIONE[self.tipo]: self.oggetto}
        return IngressoIntervento.objects.filter(**filtro).select_related("collegato_da")


def intervento(tipo: str, pk: int) -> Intervento | None:
    if tipo == TIPO_TICKET:
        from tickets.models import Ticket

        oggetto = Ticket.objects.select_related("delegato_fornitore").filter(pk=pk).first()
    elif tipo == TIPO_ODL:
        from assets.models import WorkOrder

        oggetto = WorkOrder.objects.select_related("supplier").filter(pk=pk).first()
    elif tipo == TIPO_FORMAZIONE:
        from anagrafica.models import TrainingSession

        oggetto = TrainingSession.objects.select_related(
            "corso", "corso__ente_formativo", "docente", "docente__azienda", "docente_ente",
        ).filter(pk=pk).first()
    elif tipo == TIPO_ORDINARIA:
        from assets.models import MaintenanceOccurrence

        oggetto = MaintenanceOccurrence.objects.select_related("plan", "asset", "supplier").filter(pk=pk).first()
    elif tipo == TIPO_AMMINISTRATIVA:
        from assets.models import AssetAdministrativeDeadline

        oggetto = AssetAdministrativeDeadline.objects.select_related("asset").filter(pk=pk).first()
    elif tipo == TIPO_SCADENZA:
        from scadenzario.models import ScadenzaGenerica

        oggetto = ScadenzaGenerica.objects.select_related("categoria", "fornitore").filter(pk=pk).first()
    else:
        return None
    return Intervento(tipo, oggetto) if oggetto else None


def intervento_del_link(link: IngressoIntervento) -> Intervento:
    if link.ticket_id:
        return Intervento(TIPO_TICKET, link.ticket)
    if link.work_order_id:
        return Intervento(TIPO_ODL, link.work_order)
    if link.occorrenza_id:
        return Intervento(TIPO_ORDINARIA, link.occorrenza)
    if link.scadenza_asset_id:
        return Intervento(TIPO_AMMINISTRATIVA, link.scadenza_asset)
    if link.scadenza_id:
        return Intervento(TIPO_SCADENZA, link.scadenza)
    return Intervento(TIPO_FORMAZIONE, link.sessione_formazione)


def chiavi_docente(sessione) -> tuple[set[str], set[str]]:
    """Nominativi dei docenti (sessione e lezioni) e nomi degli enti di formazione
    di una sessione, come chiavi di confronto con gli ingressi."""
    persone: set[str] = set()
    enti: set[str] = set()

    def _docente(docente, nome_snapshot, ente_docente):
        for nome in (nome_snapshot, getattr(docente, "nome", "")):
            if chiave_persona(nome):
                persone.add(chiave_persona(nome))
        if docente is not None and docente.ente:
            enti.add(chiave_ditta(docente.ente))
        if ente_docente is not None:
            enti.add(chiave_ditta(ente_docente.nome))

    _docente(sessione.docente, sessione.docente_nome, sessione.docente_ente)
    for lz in sessione.lezioni.select_related("docente", "docente__azienda", "docente_ente"):
        _docente(lz.docente, lz.docente_nome, lz.docente_ente)
    if sessione.corso_id and sessione.corso.ente_formativo_id:
        enti.add(chiave_ditta(sessione.corso.ente_formativo.nome))
    enti.discard("")
    return persone, enti


def accesso_del_docente(accesso: gp.Accesso, persone: set[str], enti: set[str]) -> bool:
    if accesso.nome == "Ospite anonimizzato":
        return False
    if chiave_persona(accesso.nome) in persone:
        return True
    return bool(accesso.azienda) and chiave_ditta(accesso.azienda) in enti


def proposte_formazione(iv: Intervento) -> list[gp.Accesso]:
    """Ingressi del docente (stesso nominativo) o dell'ente di formazione (stessa
    azienda) nel periodo della sessione, non ancora collegati."""
    persone, enti = chiavi_docente(iv.oggetto)
    if not persone and not enti:
        return []
    dal, al = iv.finestra()
    righe, _ = gp.storico(dal=dal, al=al)
    gia = set(iv.collegamenti().values_list("visita_gp_id", flat=True))
    return [a for a in righe if a.visita_id not in gia and accesso_del_docente(a, persone, enti)]


def ditte_gp_del_fornitore(fornitore) -> list[int]:
    if fornitore is None:
        return []
    return list(DittaGuestPortal.objects.filter(fornitore=fornitore).values_list("ditta_gp_id", flat=True))


def ditte_e_nomi(fornitore) -> tuple[list[int], list[str]]:
    """Come riconoscere la ditta nel GuestPortal: i suoi ``SupplierID`` e i nomi da cercare."""
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
    return sorted(ditte), sorted(nomi)


def proposte(iv: Intervento) -> list[gp.Accesso]:
    """Ingressi della ditta delegata nel periodo dell'intervento, non ancora collegati."""
    if iv.formazione:
        return proposte_formazione(iv)
    fornitore = iv.fornitore
    if fornitore is None:
        return []
    dal, al = iv.finestra()
    ditte, nomi = ditte_e_nomi(fornitore)
    righe = gp.ingressi_ditta(ditte_gp=ditte, nomi=nomi, dal=dal, al=al)
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


def _fornitore_con_nome(nome: str):
    """L'unico fornitore attivo con quel nome, a meno di forma giuridica e punteggiatura."""
    from anagrafica.models import Fornitore

    pk = unico(chiave_ditta(nome), Fornitore.objects.filter(is_active=True).values_list("pk", "ragione_sociale"))
    return Fornitore.objects.filter(pk=pk).first() if pk else None


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


def crea_fornitore_da_accesso(accesso: gp.Accesso, *, utente) -> tuple[object | None, bool, bool]:
    """Fornitore e tecnico dall'ingresso di una ditta nuova: nome dell'azienda e nominativo del
    GuestPortal. Una ditta già presente, anche non attiva, non si duplica: il tecnico va su quella.

    Ritorna ``(fornitore, fornitore_creato, tecnico_registrato)``; fornitore None se il nome è
    vuoto o corrisponde a più fornitori.
    """
    from anagrafica.models import Fornitore

    from . import tecnici

    chiave = chiave_ditta(accesso.azienda)
    if not chiave:
        return None, False, False
    fornitore = fornitore_da_accesso(accesso)
    if fornitore is None:
        pk = {p for p, nome in Fornitore.objects.values_list("pk", "ragione_sociale") if chiave_ditta(nome) == chiave}
        if len(pk) > 1:
            return None, False, False
        fornitore = Fornitore.objects.filter(pk__in=pk).first()
    with transaction.atomic():
        creato = fornitore is None
        if creato:
            fornitore = Fornitore.objects.create(ragione_sociale=accesso.azienda.strip()[:200])
        if accesso.ditta_gp_id:
            DittaGuestPortal.objects.get_or_create(
                ditta_gp_id=accesso.ditta_gp_id,
                defaults={"fornitore": fornitore, "ditta_gp_nome": accesso.azienda.strip()[:200], "creato_da": utente},
            )
        _tecnico, registrato = tecnici.registra(
            fornitore.pk, accesso.nome, origine=TecnicoFornitore.ORIGINE_GUESTPORTAL, utente=utente,
        )
    return fornitore, creato, registrato


def _imposta_ditta(iv: Intervento, fornitore, *, utente, autore: tuple[str, str] | None) -> str:
    """Se l'intervento non ha ancora una ditta, imposta quella dell'ingresso e lo
    scrive nello storico del ticket/OdL. Ritorna una frase per l'utente ("" se niente)."""
    if fornitore is None or not iv.puo_prendere_ditta:
        return ""
    o = iv.oggetto
    if iv.tipo == TIPO_ORDINARIA:
        o.supplier = fornitore
        o.save(update_fields=["supplier", "updated_at"])
        return f"La manutenzione ora è affidata a «{fornitore.ragione_sociale}»."
    if iv.tipo == TIPO_AMMINISTRATIVA:
        o.issuer = fornitore.ragione_sociale[:200]
        o.save(update_fields=["issuer", "updated_at"])
        iv.ditta_letta = fornitore
        return f"La scadenza ora riporta come ente «{fornitore.ragione_sociale}»."
    if iv.tipo == TIPO_SCADENZA:
        o.fornitore = fornitore
        o.save(update_fields=["fornitore", "aggiornato_il"])
        return f"L'attività ora è collegata a «{fornitore.ragione_sociale}»."
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
    fornitore = None if iv.formazione else fornitore_da_accesso(accesso, preferito=iv.fornitore)
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
    dati[_CAMPI_DESTINAZIONE[iv.tipo]] = iv.oggetto
    if iv.formazione:
        imposta_ditta = False
    try:
        with transaction.atomic():
            link = IngressoIntervento.objects.create(**dati)
            link.nota_ditta = _imposta_ditta(iv, fornitore, utente=utente, autore=autore) if imposta_ditta else ""
    except IntegrityError as exc:
        raise CollegamentoNonValido("Ingresso già collegato a questo intervento.") from exc
    if fornitore is not None:
        from . import tecnici

        try:
            tecnici.registra(fornitore.pk, link.tecnico_nome, origine=TecnicoFornitore.ORIGINE_INTERVENTO, utente=utente)
        except Exception:  # noqa: BLE001 - il collegamento è già fatto: il registro non lo annulla
            logger.exception("Registrazione del tecnico dal collegamento fallita")
    return link


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
    if not iv.puo_prendere_ditta:
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
    if not iv.puo_prendere_ditta:
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


def interventi_aperti(
    request, *, testo: str = "", fornitore=None, accesso: gp.Accesso | None = None,
) -> list[Intervento]:
    """Ticket MAN e OdL aperti a cui l'utente può collegare un ingresso, per il
    collegamento partendo dall'ingresso, più le sessioni formative in corso il
    giorno dell'ingresso. Prima quelli della stessa ditta o con quel docente."""
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

    docente_di: set[int] = set()
    if accesso is not None and accesso.ingresso and puo_collegare_formazione(request):
        giorno = timezone.localtime(_aware(accesso.ingresso)).date()
        sessioni = sessioni_del_giorno(giorno, testo=testo)
        for iv in sessioni:
            if accesso_del_docente(accesso, *chiavi_docente(iv.oggetto)):
                docente_di.add(iv.pk)
        esito.extend(sessioni)

    def _ordine(iv: Intervento) -> int:
        if iv.formazione:
            return 0 if iv.pk in docente_di else 1
        stessa_ditta = fornitore is not None and iv.fornitore and iv.fornitore.pk == fornitore.pk
        return 0 if stessa_ditta else 1

    esito.sort(key=_ordine)
    return esito


def _apre_percorso(request, nome: str) -> bool:
    from django.urls import NoReverseMatch, reverse

    from core.middleware import acl_allows_path

    try:
        percorso = reverse(nome, args=[0])
    except NoReverseMatch:
        return False
    return bool(acl_allows_path(percorso, django_user=request.user,
                                legacy_user=getattr(request, "legacy_user", None), request=request))


def puo_collegare_ordinaria(request) -> bool:
    from assets.views_maintenance import can_execute_maintenance

    return _apre_percorso(request, "assets:occurrence_complete") and bool(can_execute_maintenance(request))


def puo_collegare_scadenza_asset(request) -> bool:
    return _apre_percorso(request, "assets:asset_administrative_deadline_edit")


def scadenze_da_collegare(request, *, testo: str = "", fornitore=None, accesso: gp.Accesso | None = None,
                          ) -> tuple[list[Intervento], bool]:
    """Manutenzioni aperte, scadenze degli asset e attività dello Scadenzario a cui l'utente può
    collegare un ingresso: quelle della ditta e quelle intorno al giorno dell'ingresso; con una
    ricerca, tutte quelle che corrispondono. Ritorna anche se l'elenco è stato tagliato."""
    from django.db.models import Q

    from assets.models import AssetAdministrativeDeadline, MaintenanceOccurrence
    from assets.registro_permessi import MODULO_MANUTENZIONE, MODULO_VERIFICHE
    from assets.services.visibilita import filtra_per_asset
    from scadenzario.models import ScadenzaGenerica
    from scadenzario.permessi import categorie_gestibili

    testo = (testo or "").strip()
    ingresso = _aware(accesso.ingresso) if accesso is not None else None
    giorno = timezone.localtime(ingresso).date() if ingresso else timezone.localdate()
    vicino = (giorno - timedelta(days=GIORNI_PRIMA_ELENCO), giorno + timedelta(days=GIORNI_DOPO_ELENCO))
    esito: list[Intervento] = []
    tagliato = False

    def aggiungi(tipo, qs):
        nonlocal tagliato
        righe = list(qs[:ELENCO_MAX_SCADENZE + 1])
        tagliato = tagliato or len(righe) > ELENCO_MAX_SCADENZE
        esito.extend(Intervento(tipo, o) for o in righe[:ELENCO_MAX_SCADENZE])

    if puo_collegare_ordinaria(request):
        qs = filtra_per_asset(request, MaintenanceOccurrence.objects.all(), MODULO_MANUTENZIONE).select_related(
            "plan", "asset", "supplier",
        ).filter(Q(status=MaintenanceOccurrence.STATUS_OPEN) | Q(status=MaintenanceOccurrence.STATUS_DONE, completed_on=giorno))
        if testo:
            qs = qs.filter(Q(plan__label__icontains=testo) | Q(asset__name__icontains=testo) | Q(asset__asset_tag__icontains=testo))
        else:
            filtro = Q(due_date__range=vicino) | Q(completed_on=giorno)
            if fornitore is not None:
                filtro |= Q(supplier=fornitore)
            qs = qs.filter(filtro)
        aggiungi(TIPO_ORDINARIA, qs.order_by("due_date", "pk"))

    if puo_collegare_scadenza_asset(request):
        qs = filtra_per_asset(request, AssetAdministrativeDeadline.objects.filter(is_active=True), MODULO_VERIFICHE).select_related("asset")
        if testo:
            qs = qs.filter(Q(title__icontains=testo) | Q(issuer__icontains=testo) | Q(asset__name__icontains=testo)
                           | Q(asset__asset_tag__icontains=testo))
        else:
            filtro = Q(due_date__range=vicino)
            if fornitore is not None:
                # Solo per restringere la lettura: il confronto vero è sulla chiave del nome.
                chiavi = chiave_ditta(fornitore.ragione_sociale).split()
                if chiavi:
                    filtro |= Q(issuer__icontains=chiavi[0])
            qs = qs.filter(filtro)
        aggiungi(TIPO_AMMINISTRATIVA, qs.order_by("due_date", "pk"))

    gestibili = categorie_gestibili(request)
    if gestibili is None or gestibili:
        qs = ScadenzaGenerica.objects.filter(is_active=True).select_related("categoria", "fornitore")
        if gestibili is not None:
            qs = qs.filter(categoria_id__in=gestibili)
        if testo:
            qs = qs.filter(Q(titolo__icontains=testo) | Q(categoria__nome__icontains=testo))
        else:
            filtro = Q(data_scadenza__range=vicino)
            if fornitore is not None:
                filtro |= Q(fornitore=fornitore)
            qs = qs.filter(filtro)
        aggiungi(TIPO_SCADENZA, qs.order_by("data_scadenza", "pk"))

    # L'ente è un testo: si risolve una volta sola per tutto l'elenco.
    from anagrafica.models import Fornitore

    enti = [iv for iv in esito if iv.tipo == TIPO_AMMINISTRATIVA]
    if enti:
        attivi = list(Fornitore.objects.filter(is_active=True))
        per_chiave: dict[str, list] = {}
        for f in attivi:
            per_chiave.setdefault(chiave_ditta(f.ragione_sociale), []).append(f)
        for iv in enti:
            trovati = per_chiave.get(chiave_ditta(iv.oggetto.issuer), [])
            iv.ditta_letta = trovati[0] if len(trovati) == 1 else None
    return esito, tagliato


def stessa_ditta_prima(fornitore):
    """Chiave di ordinamento: prima gli interventi della ditta dell'ingresso."""
    def chiave(iv: Intervento) -> int:
        return 0 if fornitore is not None and iv.fornitore and iv.fornitore.pk == fornitore.pk else 1
    return chiave


def sessioni_del_giorno(giorno: date, *, testo: str = "") -> list[Intervento]:
    """Sessioni formative non annullate in corso in quel giorno."""
    from django.db.models import Q

    from anagrafica.models import TrainingSession

    qs = TrainingSession.objects.filter(data_inizio__lte=giorno, data_fine__gte=giorno).exclude(
        stato="ANNULLATA"
    ).select_related("corso", "corso__ente_formativo", "docente", "docente__azienda", "docente_ente")
    if testo:
        qs = qs.filter(Q(codice_sessione__icontains=testo) | Q(corso__titolo__icontains=testo)
                       | Q(docente_nome__icontains=testo))
    return [Intervento(TIPO_FORMAZIONE, s) for s in qs.order_by("data_inizio", "pk")[:100]]


def puo_collegare_formazione(request) -> bool:
    """Chi modifica la formazione (stessa regola delle sessioni)."""
    from anagrafica.views import _helpers

    return bool(_helpers._can_edit_formazione(request))


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
    if iv.formazione:
        # Ore in aula a registro (pausa compresa: il docente resta in azienda).
        ore = [lz.durata_ore_lorde for lz in iv.oggetto.lezioni.all()]
        if ore:
            dichiarate = int(round(sum(ore) * 60))
    elif iv.tipo == TIPO_TICKET:
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
    righe = IngressoIntervento.objects.filter(visita_gp_id__in=visita_ids).select_related(
        "ticket", "work_order", "sessione_formazione", "occorrenza", "occorrenza__plan", "occorrenza__asset",
        "scadenza_asset", "scadenza_asset__asset", "scadenza",
    )
    for link in righe:
        if link.ticket_id:
            voce = (link.ticket.numero_ticket or f"Ticket #{link.ticket_id}",
                    reverse("tickets:gestione_detail", args=[link.ticket_id]))
        elif link.work_order_id:
            voce = (f"OdL #{link.work_order.display_number}", reverse("assets:wo_view", args=[link.work_order_id]))
        elif link.occorrenza_id or link.scadenza_asset_id or link.scadenza_id:
            iv = intervento_del_link(link)
            voce = (f"{iv.tipo_label}: {iv.etichetta}", iv.url)
        else:
            voce = (f"Formazione {link.sessione_formazione.codice_sessione}",
                    reverse("anagrafica:formazione_sessione_detail", args=[link.sessione_formazione_id]))
        esito.setdefault(link.visita_gp_id, []).append(voce)
    return esito


ore_label = _ore_label
