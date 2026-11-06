"""Requisiti di sicurezza dei fornitori che lavorano nei nostri locali.

Art. 26 D.Lgs. 81/2008 (appalti e contratti d'opera): prima di far entrare una ditta
il committente verifica l'idoneità tecnico-professionale (visura camerale +
autocertificazione), la regolarità contributiva (DURC) e coordina i rischi da
interferenza (DUVRI). La polizza RCT/RCO è consigliata.

Qui si decide, per ogni fornitore con ``accede_in_sede``, se i documenti caricati nella
scheda sono **in regola**, **in scadenza** (entro ``GIORNI_PREAVVISO``) o **non in
regola** (mancanti o scaduti). Vale il documento di quel tipo con la scadenza più
lontana; un documento senza scadenza vale finché non viene sostituito.

Lo stato si vede nella scheda e nell'elenco fornitori, negli Accessi esterni e nella
lista Presenti in azienda accanto alla ditta entrata dal GuestPortal; ``tasks`` avvisa
RSPP/ASPP con una notifica (mai mail) quando entra una ditta non in regola.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone

GIORNI_PREAVVISO = 30
GIORNI_DITTE_ATTESE = 30

# (tipo documento, etichetta breve, obbligatorio)
REQUISITI: list[tuple[str, str, bool]] = [
    ("VISURA", "Visura camerale", True),
    ("IDONEITA", "Idoneità tecnico-professionale", True),
    ("DURC", "DURC", True),
    ("DUVRI", "DUVRI", True),
    ("RCT", "Polizza RCT/RCO", False),
]

ESITO_OK = "ok"
ESITO_IN_SCADENZA = "in_scadenza"
ESITO_NON_IN_REGOLA = "non_in_regola"
ESITO_NON_RICHIESTO = "non_richiesto"

ETICHETTE_ESITO = {
    ESITO_OK: "Documenti in regola",
    ESITO_IN_SCADENZA: "Documenti in scadenza",
    ESITO_NON_IN_REGOLA: "Documenti non in regola",
    ESITO_NON_RICHIESTO: "Non lavora in sede",
}


@dataclass
class VoceRequisito:
    tipo: str
    etichetta: str
    obbligatorio: bool
    stato: str  # ok | in_scadenza | scaduto | mancante
    scadenza: date | None = None
    documento_id: int | None = None

    @property
    def descrizione(self) -> str:
        if self.stato == "mancante":
            return f"{self.etichetta} mancante"
        if self.stato == "scaduto":
            return f"{self.etichetta} scaduto il {self.scadenza:%d/%m/%Y}"
        if self.stato == "in_scadenza":
            return f"{self.etichetta} scade il {self.scadenza:%d/%m/%Y}"
        return f"{self.etichetta} valido" + (f" fino al {self.scadenza:%d/%m/%Y}" if self.scadenza else "")


@dataclass
class StatoRequisiti:
    esito: str
    voci: list[VoceRequisito] = field(default_factory=list)

    @property
    def etichetta(self) -> str:
        return ETICHETTE_ESITO[self.esito]

    @property
    def problemi(self) -> list[VoceRequisito]:
        """Voci obbligatorie mancanti o scadute, poi quelle in scadenza."""
        gravi = [v for v in self.voci if v.obbligatorio and v.stato in ("mancante", "scaduto")]
        return gravi + [v for v in self.voci if v.stato == "in_scadenza"]

    @property
    def riassunto(self) -> str:
        return "; ".join(v.descrizione for v in self.problemi)


def _stato_da_documenti(accede_in_sede: bool, documenti: list[tuple[str, date | None, int]], oggi: date) -> StatoRequisiti:
    if not accede_in_sede:
        return StatoRequisiti(ESITO_NON_RICHIESTO)
    migliore: dict[str, tuple[date | None, int]] = {}
    for tipo, scadenza, doc_id in documenti:
        attuale = migliore.get(tipo)
        # Senza scadenza = vale sempre (batte qualunque data); altrimenti la data più lontana.
        if attuale is None or (attuale[0] is not None and (scadenza is None or scadenza > attuale[0])):
            migliore[tipo] = (scadenza, doc_id)
    voci = []
    limite = oggi + timedelta(days=GIORNI_PREAVVISO)
    for tipo, etichetta, obbligatorio in REQUISITI:
        if tipo not in migliore:
            voci.append(VoceRequisito(tipo, etichetta, obbligatorio, "mancante"))
            continue
        scadenza, doc_id = migliore[tipo]
        if scadenza is not None and scadenza < oggi:
            stato = "scaduto"
        elif scadenza is not None and scadenza <= limite:
            stato = "in_scadenza"
        else:
            stato = "ok"
        voci.append(VoceRequisito(tipo, etichetta, obbligatorio, stato, scadenza, doc_id))
    if any(v.obbligatorio and v.stato in ("mancante", "scaduto") for v in voci):
        esito = ESITO_NON_IN_REGOLA
    elif any(v.stato == "in_scadenza" for v in voci if v.obbligatorio):
        esito = ESITO_IN_SCADENZA
    else:
        esito = ESITO_OK
    return StatoRequisiti(esito, voci)


def stati_per_fornitori(ids, oggi: date | None = None, al: dict[int, date] | None = None) -> dict[int, StatoRequisiti]:
    """Stato dei requisiti per molti fornitori con due sole query. ``al``: la data a cui
    valutare ogni fornitore, se diversa da ``oggi``."""
    from anagrafica.models import Fornitore, FornitoreDocumento

    ids = {int(i) for i in ids if i}
    if not ids:
        return {}
    oggi = oggi or timezone.localdate()
    tipi = [t for t, _e, _o in REQUISITI]
    docs: dict[int, list] = {}
    for fid, tipo, scadenza, pk in FornitoreDocumento.objects.filter(fornitore_id__in=ids, tipo__in=tipi).values_list(
            "fornitore_id", "tipo", "data_scadenza", "pk"):
        docs.setdefault(fid, []).append((tipo, scadenza, pk))
    return {
        fid: _stato_da_documenti(sede, docs.get(fid, []), (al or {}).get(fid, oggi))
        for fid, sede in Fornitore.objects.filter(pk__in=ids).values_list("pk", "accede_in_sede")
    }


def stato_fornitore(fornitore, oggi: date | None = None) -> StatoRequisiti:
    return stati_per_fornitori([fornitore.pk], oggi).get(fornitore.pk) or StatoRequisiti(ESITO_NON_RICHIESTO)


@dataclass
class DittaAttesa:
    fornitore_id: int
    ragione_sociale: str
    n_interventi: int
    entro_il: date
    problemi: str


def ditte_attese_non_in_regola(oggi: date | None = None) -> list[DittaAttesa]:
    """Ditte «Lavora nei nostri locali» che devono ancora venire e con i documenti che non
    saranno in regola: manutenzioni aperte entro ``GIORNI_DITTE_ATTESE`` (anche in ritardo), OdL
    aperti e ticket delegati aperti. Lo stato si guarda al giorno dell'ultimo intervento atteso:
    un DURC che scade prima conta già adesso. Una manutenzione raccolta in un OdL aperto della
    stessa ditta conta una volta sola."""
    from anagrafica.models import Fornitore
    from assets.models import MaintenanceOccurrence, WorkOrder
    from tickets.models import StatoTicket, Ticket

    oggi = oggi or timezone.localdate()
    limite = oggi + timedelta(days=GIORNI_DITTE_ATTESE)
    date_per_ditta: dict[int, list[date]] = {}

    occorrenze = MaintenanceOccurrence.objects.filter(
        status=MaintenanceOccurrence.STATUS_OPEN, due_date__lte=limite,
        supplier__accede_in_sede=True, supplier__is_active=True,
    ).values_list("supplier_id", "due_date", "work_order__supplier_id", "work_order__status")
    for fid, scadenza, ditta_odl, stato_odl in occorrenze:
        if ditta_odl == fid and stato_odl == WorkOrder.STATUS_OPEN:
            continue
        date_per_ditta.setdefault(fid, []).append(max(scadenza, oggi))
    odl = WorkOrder.objects.filter(
        status=WorkOrder.STATUS_OPEN, supplier__accede_in_sede=True, supplier__is_active=True,
    ).values_list("supplier_id", "due_at")
    for fid, entro in odl:
        giorno = timezone.localtime(entro).date() if entro else oggi
        if giorno <= limite:
            date_per_ditta.setdefault(fid, []).append(max(giorno, oggi))
    ticket = Ticket.objects.filter(
        delegato_fornitore__accede_in_sede=True, delegato_fornitore__is_active=True,
    ).exclude(stato__in=[StatoTicket.CHIUSO, StatoTicket.ANNULLATO]).values_list("delegato_fornitore_id", flat=True)
    for fid in ticket:
        date_per_ditta.setdefault(fid, []).append(oggi)
    if not date_per_ditta:
        return []

    stati = stati_per_fornitori(date_per_ditta, oggi, al={fid: max(d) for fid, d in date_per_ditta.items()})
    nomi = dict(Fornitore.objects.filter(pk__in=date_per_ditta).values_list("pk", "ragione_sociale"))
    esito = []
    for fid, giorni in date_per_ditta.items():
        stato = stati.get(fid)
        if stato is None or stato.esito != ESITO_NON_IN_REGOLA:
            continue
        problemi = []
        for voce in stato.voci:
            if not voce.obbligatorio or voce.stato not in ("mancante", "scaduto"):
                continue
            # «Scaduto» è calcolato alla data dell'intervento: oggi può essere ancora valido.
            if voce.scadenza is not None and voce.scadenza >= oggi:
                problemi.append(f"{voce.etichetta} scade il {voce.scadenza:%d/%m/%Y}")
            else:
                problemi.append(voce.descrizione)
        esito.append(DittaAttesa(fid, nomi.get(fid, ""), len(giorni), max(giorni), "; ".join(problemi)))
    return sorted(esito, key=lambda d: (d.entro_il, d.ragione_sociale))


def documenti_con_scadenza(documenti) -> list:
    """Per fornitore e tipo il documento con la scadenza più lontana: un documento rinnovato
    fa sparire il vecchio dalle scadenze. Stessa regola in Scadenzario e nella scheda."""
    migliori: dict[tuple[int, str], object] = {}
    for d in documenti:
        chiave = (d.fornitore_id, d.tipo)
        if chiave not in migliori or d.data_scadenza > migliori[chiave].data_scadenza:
            migliori[chiave] = d
    return list(migliori.values())


def abbina_fornitori(accessi) -> None:
    """Imposta ``accesso.fornitore_id`` sugli accessi del GuestPortal.

    Prima l'abbinamento ditta GuestPortal → fornitore HUB, poi la stessa ragione sociale
    a meno di maiuscole, punteggiatura e forma giuridica; un nome che corrisponde a più
    fornitori non collega nessuno (``fornitori.nomi.chiave_ditta``).
    """
    from anagrafica.models import Fornitore

    from .models import DittaGuestPortal
    from .nomi import chiave_ditta

    accessi = list(accessi)
    if not accessi:
        return
    per_ditta = dict(DittaGuestPortal.objects.values_list("ditta_gp_id", "fornitore_id"))
    per_chiave: dict[str, int | None] = {}
    if any(getattr(a, "azienda", "") for a in accessi):
        for pk, rs in Fornitore.objects.filter(is_active=True).values_list("pk", "ragione_sociale"):
            chiave = chiave_ditta(rs)
            if chiave:
                per_chiave[chiave] = None if chiave in per_chiave else pk
    for a in accessi:
        a.fornitore_id = per_ditta.get(getattr(a, "ditta_gp_id", None)) or per_chiave.get(chiave_ditta(a.azienda))
