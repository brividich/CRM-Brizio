"""Scheda fornitore: quello che gli altri moduli sanno di questa ditta.

Niente qui è obbligatorio e niente blocca: si legge ciò che esiste già (OdL, contratti,
ticket, ricambi, fatture delle multifunzioni, ingressi dal GuestPortal) e una sezione
vuota lo dice senza errori. Le sezioni si caricano all'apertura della scheda relativa,
così un GuestPortal che non risponde non rallenta la pagina del fornitore.

Ogni sezione segue il permesso del modulo da cui vengono i dati (``sezioni_visibili``):
la scheda fornitore non deve diventare una scorciatoia per vederli.

Tecnici: il registro (``TecnicoFornitore``, vedi ``fornitori.tecnici``) sta nell'HUB e si
vede con la scheda del fornitore. Ingressi, ore e presenze si leggono dal GuestPortal a ogni
apertura, senza copie, e solo con il permesso di «Accessi esterni».
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from . import guestportal as gp
from . import ingressi as ing
from .models import FornitoreContatori, IngressoIntervento
from .nomi import chiave_ditta, chiave_tecnico
from .requisiti import GIORNI_PREAVVISO, documenti_con_scadenza
from .tecnici import nome_registrabile

SEZIONE_MANUTENZIONE = "manutenzione"
SEZIONE_COPIE = "copie"
SEZIONE_SCADENZE = "scadenze"
SEZIONE_TECNICI = "tecnici"

CHIUSI_MOSTRATI = 10
RICAMBI_MOSTRATI = 20
TICKET_CHIUSI_MOSTRATI = 10
SESSIONI_MOSTRATE = 10
RINNOVI_MOSTRATI = 10
TRIMESTRI_CON_ESITO = 8
GIORNI_INGRESSI = 90
INGRESSI_MOSTRATI = 50
INTERVENTI_MOSTRATI = 20


def apre(request, route: str, *args) -> bool:
    """La persona può aprire questa pagina? (stessa decisione del middleware ACL)"""
    from core.middleware import acl_allows_path

    return bool(acl_allows_path(
        reverse(route, args=args), django_user=request.user,
        legacy_user=getattr(request, "legacy_user", None), request=request,
    ))


def vede_ingressi(request) -> bool:
    """Ingressi e presenze dei tecnici: dati personali, stesso permesso di «Accessi esterni»."""
    return apre(request, "fornitori:accessi_esterni")


def sezioni_visibili(request) -> dict[str, bool]:
    return {
        SEZIONE_MANUTENZIONE: apre(request, "assets:maintenance_suppliers"),
        SEZIONE_COPIE: apre(request, "contatori:fatture"),
        SEZIONE_SCADENZE: True,  # ogni voce controlla il proprio modulo in dati_scadenze
        SEZIONE_TECNICI: True,  # il registro segue la scheda; gli ingressi vedi vede_ingressi
    }


# ---------------------------------------------------------------------------
# Manutenzione
# ---------------------------------------------------------------------------

def dati_manutenzione(request, fornitore, oggi=None) -> dict:
    from assets.models import PeriodicCheckSession, SoftwareLicenseRenewal, SparePart
    from assets.services.fornitore_manutenzione import rapporto_ditta
    from tickets.models import StatoTicket
    from tickets.services.accesso import utente_puo_gestire_ticket

    oggi = oggi or timezone.localdate()
    r = rapporto_ditta(fornitore, oggi)

    # Ticket delegati alla ditta: si vedono solo quelli che la persona può gestire.
    chiusi_stati = (StatoTicket.CHIUSO, StatoTicket.ANNULLATO)
    delegati = fornitore.tickets_delegati.order_by("-created_at", "-pk")
    ticket_aperti = [t for t in delegati.exclude(stato__in=chiusi_stati) if utente_puo_gestire_ticket(request, t)]
    ticket_chiusi = [t for t in delegati.filter(stato__in=chiusi_stati) if utente_puo_gestire_ticket(request, t)]

    ricambi = SparePart.objects.filter(supplier=fornitore, is_active=True).order_by("code")
    sessioni, n_sessioni = [], 0
    if apre(request, "assets:periodic_check_list"):
        qs = PeriodicCheckSession.objects.filter(supplier=fornitore).select_related("check_type")
        n_sessioni = qs.count()
        sessioni = list(qs.order_by("-performed_on", "-pk")[:SESSIONI_MOSTRATE])
    rinnovi, n_rinnovi = [], 0
    if apre(request, "assets:software_license_list"):
        qs = SoftwareLicenseRenewal.objects.filter(supplier=fornitore).select_related("license")
        n_rinnovi = qs.count()
        rinnovi = list(qs.order_by("-renewed_on", "-pk")[:RINNOVI_MOSTRATI])

    vuota = not any((
        r.contracts, r.rules, r.verifications, r.workorders, ticket_aperti, ticket_chiusi,
        ricambi.exists(), sessioni, rinnovi,
    ))
    return {
        "r": r,
        "contratti_attivi": sum(1 for c in r.contracts if c.is_active),
        "piani_attivi": sum(1 for x in r.rules if x.is_active),
        "verifiche_attive": sum(1 for v in r.verifications if v.is_active),
        "chiusi_recenti": r.closed_wos[:CHIUSI_MOSTRATI],
        "ticket_aperti": ticket_aperti,
        "ticket_chiusi": ticket_chiusi[:TICKET_CHIUSI_MOSTRATI],
        "n_ticket_chiusi": len(ticket_chiusi),
        "ricambi": list(ricambi[:RICAMBI_MOSTRATI]),
        "n_ricambi": ricambi.count(),
        "sessioni": sessioni,
        "n_sessioni": n_sessioni,
        "rinnovi": rinnovi,
        "n_rinnovi": n_rinnovi,
        "vuota": vuota,
        "oggi": oggi,
    }


# ---------------------------------------------------------------------------
# Multifunzioni e fatture copie (modulo Contatori)
# ---------------------------------------------------------------------------

def catalogo_codici() -> dict[str, str]:
    """Codici fornitore usati da Contatori: ``{codice: etichetta}``."""
    from contatori.models import Fattura, Macchina

    catalogo = dict(Macchina.Fornitore.choices)
    for codice in Fattura.objects.order_by().values_list("fornitore", flat=True).distinct():
        if codice:
            catalogo.setdefault(codice, codice)
    return catalogo


def mappa_codici() -> dict[str, int | None]:
    """``{codice: id fornitore HUB}``: prima la scelta fatta a mano, poi la stessa ragione
    sociale tra i fornitori attivi (un nome che corrisponde a più fornitori non collega)."""
    from anagrafica.models import Fornitore

    espliciti = dict(FornitoreContatori.objects.values_list("codice", "fornitore_id"))
    per_chiave: dict[str, int | None] = {}
    for pk, rs in Fornitore.objects.filter(is_active=True).values_list("pk", "ragione_sociale"):
        chiave = chiave_ditta(rs)
        if chiave:
            per_chiave[chiave] = None if chiave in per_chiave else pk
    return {
        codice: espliciti.get(codice) or per_chiave.get(chiave_ditta(etichetta))
        for codice, etichetta in catalogo_codici().items()
    }


def codici_del_fornitore(fornitore) -> list[dict]:
    catalogo = catalogo_codici()
    espliciti = set(FornitoreContatori.objects.filter(fornitore=fornitore).values_list("codice", flat=True))
    return [
        {"codice": codice, "etichetta": catalogo.get(codice, codice), "esplicito": codice in espliciti}
        for codice, fornitore_id in mappa_codici().items() if fornitore_id == fornitore.pk
    ]


def codici_da_scegliere(fornitore) -> list[dict]:
    """Codici che si possono collegare a questo fornitore, con l'eventuale fornitore attuale."""
    from anagrafica.models import Fornitore

    catalogo = catalogo_codici()
    mappa = mappa_codici()
    nomi = dict(Fornitore.objects.filter(pk__in=[v for v in mappa.values() if v]).values_list("pk", "ragione_sociale"))
    return [
        {"codice": codice, "etichetta": catalogo[codice], "attuale": nomi.get(fornitore_id, "")}
        for codice, fornitore_id in mappa.items() if fornitore_id != fornitore.pk
    ]


_GRAVITA = {"ok": 0, "warn": 1, "danger": 2}
_ESITI = {"ok": "OK", "warn": "Dati incompleti", "danger": "Da controllare"}


def dati_copie(fornitore) -> dict:
    from contatori import services as cs
    from contatori.models import Fattura, LetturaContatori, Macchina

    codici = codici_del_fornitore(fornitore)
    if not codici:
        return {"codici": [], "macchine": [], "fatture": [], "scoperti": [], "trimestri_con_esito": TRIMESTRI_CON_ESITO}
    valori = [c["codice"] for c in codici]
    macchine = list(Macchina.objects.filter(fornitore__in=valori).select_related("asset").order_by("reparto", "matricola"))
    fatture = list(Fattura.objects.filter(fornitore__in=valori).prefetch_related("righe").order_by("-periodo_al", "-pk"))

    fatturati = {f.trimestre for f in fatture}
    # Esito della riconciliazione fattura per fattura: la stessa funzione della pagina Riconciliazione.
    esiti: dict[int, dict] = {}
    for trimestre in sorted(fatturati, reverse=True)[:TRIMESTRI_CON_ESITO]:
        for gruppo in cs.riconcilia(trimestre)[1]["gruppi"]:
            esito = esiti.setdefault(gruppo["fattura"].pk, {"livello": "ok", "copie_in_eccesso": 0})
            if _GRAVITA.get(gruppo["livello"], 0) > _GRAVITA[esito["livello"]]:
                esito["livello"] = gruppo["livello"]
            esito["copie_in_eccesso"] += gruppo["copie_in_eccesso"]
    for f in fatture:
        esito = esiti.get(f.pk)
        f.esito_livello = esito["livello"] if esito else ""
        f.esito_label = _ESITI.get(esito["livello"], "") if esito else ""
        f.copie_in_eccesso = esito["copie_in_eccesso"] if esito else 0

    # Trimestri con letture delle macchine di questa ditta ma senza una sua fattura.
    scoperti: list[str] = []
    if fatturati:
        primo, corrente = min(fatturati), cs.trimestre_corrente()
        letti = (LetturaContatori.objects.filter(macchina__fornitore__in=valori).order_by()
                 .values_list("trimestre", flat=True).distinct())
        scoperti = sorted((t for t in set(letti) if primo <= t < corrente and t not in fatturati), reverse=True)
    return {
        "codici": codici,
        "macchine": macchine,
        "macchine_attive": sum(1 for m in macchine if m.attiva),
        "fatture": fatture,
        "da_controllare": sum(1 for f in fatture if f.esito_livello == "danger"),
        "scoperti": scoperti,
        "trimestri_con_esito": TRIMESTRI_CON_ESITO,
    }


# ---------------------------------------------------------------------------
# Scadenze della ditta
# ---------------------------------------------------------------------------

def _stato_data(data, oggi) -> tuple[str, str]:
    if data < oggi:
        return "scaduta", "Scaduta"
    if data <= oggi + timedelta(days=GIORNI_PREAVVISO):
        return "in_scadenza", "In scadenza"
    return "ok", "Valida"


def dati_scadenze(request, fornitore, oggi=None) -> dict:
    oggi = oggi or timezone.localdate()
    dettaglio = reverse("fornitori:fornitore_detail", args=[fornitore.pk])
    voci: list[dict] = []

    def aggiungi(data, tipo, cosa, url):
        stato, stato_label = _stato_data(data, oggi)
        voci.append({"data": data, "tipo": tipo, "cosa": cosa, "url": url, "stato": stato, "stato_label": stato_label})

    for d in documenti_con_scadenza(fornitore.documenti.filter(data_scadenza__isnull=False)):
        aggiungi(d.data_scadenza, "Documento", f"{d.get_tipo_display()} — {d.nome}", f"{dettaglio}#tab-docs")

    if apre(request, "assets:maintenance_suppliers"):
        from assets.models import AssistanceContract, PeriodicVerification

        url = reverse("assets:maintenance_supplier_detail", args=[fornitore.pk])
        for c in AssistanceContract.objects.filter(supplier=fornitore, is_active=True, end_date__isnull=False):
            aggiungi(c.end_date, "Contratto", c.title, url)
        for v in PeriodicVerification.objects.filter(supplier=fornitore, is_active=True,
                                                     next_verification_date__isnull=False):
            aggiungi(v.next_verification_date, "Verifica periodica", v.name, url)

    from scadenzario.permessi import puo_vedere_scadenza

    for t in fornitore.tecnici.filter(attivo=True, attestati_fino_al__isnull=False):
        aggiungi(t.attestati_fino_al, "Attestati tecnico", t.nome, f"{dettaglio}#tab-tecnici")

    for s in fornitore.scadenze_generiche.filter(is_active=True).select_related("categoria"):
        if puo_vedere_scadenza(request, s):
            aggiungi(s.data_scadenza, "Scadenzario", s.titolo, reverse("scadenzario:scadenza_dettaglio", args=[s.pk]))

    voci.sort(key=lambda v: v["data"])
    return {
        "voci": voci,
        "n_scadute": sum(1 for v in voci if v["stato"] == "scaduta"),
        "n_in_scadenza": sum(1 for v in voci if v["stato"] == "in_scadenza"),
        "giorni_preavviso": GIORNI_PREAVVISO,
    }


# ---------------------------------------------------------------------------
# Tecnici
# ---------------------------------------------------------------------------

@dataclass
class Tecnico:
    nome: str
    ingressi: int = 0
    minuti: int = 0
    ultimo: datetime | None = None
    dentro: bool = False
    interventi: list = field(default_factory=list)
    registro: object = None
    attestati_stato: str = ""
    attestati_label: str = ""

    @property
    def ore_label(self) -> str:
        return ing.ore_label(self.minuti) if self.minuti else "—"


def _locale(valore: datetime | None) -> datetime | None:
    """Gli orari del GuestPortal sono locali senza fuso: si confrontano così."""
    if valore is None or timezone.is_naive(valore):
        return valore
    return timezone.localtime(valore).replace(tzinfo=None)


def collegamenti_del_fornitore(fornitore):
    """Ingressi collegati a ticket e OdL della ditta: restano dopo la pulizia del GuestPortal."""
    return (
        IngressoIntervento.objects
        .filter(Q(fornitore=fornitore) | Q(ticket__delegato_fornitore=fornitore) | Q(work_order__supplier=fornitore))
        .select_related("ticket", "work_order", "sessione_formazione")
        .order_by("-ingresso", "-pk")
    )


def dati_tecnici(fornitore, oggi=None, *, vede_ingressi: bool = True) -> dict:
    """Registro del fornitore e, con ``vede_ingressi``, ingressi e ore di ciascuno."""
    oggi = oggi or timezone.localdate()
    configurato = gp.db_configurato()
    errore = ""
    righe_gp: list[gp.TecnicoDitta] = []
    troncato = False
    ingressi: list = []
    ingressi_troncati = False
    ditte: list[int] = []
    if configurato and vede_ingressi:
        try:
            ditte, nomi = ing.ditte_e_nomi(fornitore)
            righe_gp, troncato = gp.tecnici_ditta(ditte_gp=ditte, nomi=nomi)
            ingressi = gp.ingressi_ditta(
                ditte_gp=ditte, nomi=nomi, dal=oggi - timedelta(days=GIORNI_INGRESSI - 1), al=oggi,
                limite=INGRESSI_MOSTRATI + 1,
            )
            ingressi_troncati = len(ingressi) > INGRESSI_MOSTRATI
            ingressi = ingressi[:INGRESSI_MOSTRATI]
        except gp.GuestPortalNonConfigurato:
            configurato = False
        except gp.GuestPortalNonRaggiungibile:
            errore = "Il GuestPortal non risponde: si vedono solo gli ingressi già collegati agli interventi."

    per_chiave: dict[str, Tecnico] = {}
    for r in righe_gp:  # il GuestPortal può avere la stessa persona registrata più volte
        t = per_chiave.setdefault(chiave_tecnico(r.nome), Tecnico(nome=r.nome))
        t.ingressi += r.ingressi
        t.minuti += r.minuti
        t.dentro = t.dentro or r.dentro
        if r.ultimo and (t.ultimo is None or r.ultimo > t.ultimo):
            t.ultimo = r.ultimo

    collegati = list(collegamenti_del_fornitore(fornitore)) if vede_ingressi else []
    interventi = []
    for link in collegati:
        iv = ing.intervento_del_link(link)
        voce = {"link": link, "etichetta": iv.etichetta, "url": iv.url}
        interventi.append(voce)
        if not link.tecnico_nome:
            continue
        t = per_chiave.setdefault(chiave_tecnico(link.tecnico_nome), Tecnico(nome=link.tecnico_nome))
        t.interventi.append(voce)
        ingresso = _locale(link.ingresso)
        if ingresso and (t.ultimo is None or ingresso > t.ultimo):
            t.ultimo = ingresso

    # Il registro comanda: nome e dati sono i suoi, ingressi e ore si aggiungono se ci sono.
    tecnici = []
    for reg in fornitore.tecnici.all():
        t = per_chiave.pop(reg.chiave, None) or Tecnico(nome=reg.nome)
        t.nome, t.registro = reg.nome, reg
        if reg.attestati_fino_al and reg.attivo:  # chi non è attivo non ha più scadenze
            t.attestati_stato, t.attestati_label = _stato_data(reg.attestati_fino_al, oggi)
        tecnici.append(t)
    tecnici.sort(key=lambda t: (t.registro.attivo, t.dentro, t.ultimo or datetime.min), reverse=True)
    da_registrare = sorted(
        (t for t in per_chiave.values() if nome_registrabile(t.nome)),
        key=lambda t: (t.dentro, t.ultimo or datetime.min), reverse=True,
    )
    return {
        "vede_ingressi": vede_ingressi,
        "da_registrare": da_registrare,
        "n_attivi": sum(1 for t in tecnici if t.registro.attivo),
        "configurato": configurato,
        "errore": errore,
        "tecnici": tecnici,
        "troncato": troncato,
        "limite": gp.TECNICI_MAX_RIGHE,
        "n_dentro": sum(1 for t in [*tecnici, *da_registrare] if t.dentro),
        "ingressi": ingressi,
        "ingressi_troncati": ingressi_troncati,
        "ingressi_mostrati": INGRESSI_MOSTRATI,
        "giorni_ingressi": GIORNI_INGRESSI,
        "interventi": interventi[:INTERVENTI_MOSTRATI],
        "n_interventi": len(interventi),
        "abbinata": bool(ditte),
    }


# ---------------------------------------------------------------------------
# Cruscotto: cosa guardare oggi
# ---------------------------------------------------------------------------

def da_guardare(request, oggi=None) -> list[dict]:
    """Voci con qualcosa da fare, per la pagina iniziale: solo quelle con almeno un elemento."""
    from anagrafica.models import Fornitore

    from .requisiti import ESITO_IN_SCADENZA, ESITO_NON_IN_REGOLA, stati_per_fornitori

    oggi = oggi or timezone.localdate()
    base = reverse("fornitori:fornitori_list")
    stati = stati_per_fornitori(
        Fornitore.objects.filter(is_active=True, accede_in_sede=True).values_list("pk", flat=True)
    ).values()
    voci = [
        {"n": sum(1 for s in stati if s.esito == ESITO_NON_IN_REGOLA), "livello": "danger",
         "testo": "ditte in sede con documenti non in regola", "url": f"{base}?requisiti={ESITO_NON_IN_REGOLA}"},
        {"n": sum(1 for s in stati if s.esito == ESITO_IN_SCADENZA), "livello": "warn",
         "testo": f"ditte in sede con documenti in scadenza entro {GIORNI_PREAVVISO} giorni",
         "url": f"{base}?requisiti={ESITO_IN_SCADENZA}"},
    ]
    if apre(request, "assets:maintenance_suppliers"):
        from assets.models import AssistanceContract, WorkOrder

        voci.append({
            "n": WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN, supplier__isnull=False).count(),
            "livello": "info", "testo": "ordini di lavoro aperti affidati a una ditta",
            "url": reverse("assets:maintenance_suppliers"),
        })
        voci.append({
            "n": AssistanceContract.objects.filter(
                is_active=True, end_date__isnull=False, end_date__lte=oggi + timedelta(days=GIORNI_PREAVVISO),
            ).count(),
            "livello": "warn", "testo": f"contratti di assistenza scaduti o in scadenza entro {GIORNI_PREAVVISO} giorni",
            "url": reverse("assets:assistance_contract_list"),
        })
    return [v for v in voci if v["n"]]
