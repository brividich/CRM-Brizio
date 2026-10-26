"""Audit esterni (enti, clienti, autorità) e certificazioni del sistema di gestione.

I rilievi di un audit esterno diventano voci del Registro OFI (MOD.174) con origine
l'audit e fonte l'ente, così azioni, CAR, solleciti e cruscotto restano quelli del
registro unico.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from ..models import NORME_SGI, Audit, AuditEsito, AuditEsterno, Auditor, AuditVerificaEfficacia, Certificazione

CLASSIFICAZIONI = [
    ("NC_MAGGIORE", "Non conformità maggiore"),
    ("NC_MINORE", "Non conformità minore"),
    ("OSSERVAZIONE", "Osservazione"),
    ("OFI", "Opportunità di miglioramento"),
]
_ETICHETTE = dict(CLASSIFICAZIONI)
# Campo norma dell'audit esterno -> campo norma del registro OFI.
_NORME = {"en9100": "norma_en9100", "iso45001": "norma_iso45001", "iso14001": "norma_iso14001",
          "iso27001": "norma_iso27001", "pdr125": "norma_pdr125"}


def rilievi(audit: AuditEsterno):
    from gestione_specifiche.models import RegistroOFI
    ct = ContentType.objects.get_for_model(AuditEsterno)
    return (RegistroOFI.objects.filter(content_type=ct, object_id=audit.pk)
            .select_related("responsabile").order_by("numero"))


def crea_rilievo(audit: AuditEsterno, *, classificazione: str, descrizione: str, utente, rif_norma: str = "",
                 processo: str = "", data_richiesta=None, responsabile=None):
    """Registra un rilievo dell'audit esterno come voce del Registro OFI."""
    from gestione_specifiche import registro_ofi as reg
    from gestione_specifiche.models import RegistroOFI

    if classificazione not in _ETICHETTE:
        raise ValueError("Classificazione non valida.")
    nc = classificazione.startswith("NC_")
    testo = descrizione.strip()
    if classificazione != "OFI":
        testo = f"[{_ETICHETTE[classificazione]}] {testo}"
    dati = {
        "data_apertura": audit.data_fine or audit.data_inizio,
        "tipo": RegistroOFI.TIPO_NC if nc else RegistroOFI.TIPO_OFI,
        "fonte": audit.ente[:100],
        "ref": f"{audit.get_tipo_display()} {audit.data_inizio:%d/%m/%Y}"[:100],
        "rif_norma": rif_norma[:200],
        "processo": processo[:200],
        "opportunita": testo[:5000],
        "priorita": RegistroOFI.PRIORITA_ALTA if classificazione == "NC_MAGGIORE" else RegistroOFI.PRIORITA_MEDIA,
        "data_richiesta": data_richiesta or audit.risposta_entro,
        "responsabile": responsabile,
        "modulo_origine": "sistema_gestione",
        "content_type": ContentType.objects.get_for_model(AuditEsterno),
        "object_id": audit.pk,
        **{campo_ofi: getattr(audit, campo) for campo, campo_ofi in _NORME.items()},
    }
    voce = None
    for tentativo in range(2):
        try:
            with transaction.atomic():
                voce = RegistroOFI.objects.create(numero=reg.prossimo_numero(), **dati)
            break
        except IntegrityError:
            if tentativo:
                raise
    reg.registra_evento(voce, "CREATA", utente=utente, a=voce.get_fase_display(),
                        nota=f"Rilievo dell'audit esterno: {audit}")
    if audit.stato == AuditEsterno.STATO_PIANIFICATO:
        audit.stato = AuditEsterno.STATO_SVOLTO
        audit.save(update_fields=["stato", "aggiornato_il"])
    return voce


def nc_aperte(audit: AuditEsterno) -> int:
    from gestione_specifiche.models import RegistroOFI
    return sum(1 for v in rilievi(audit) if v.tipo == RegistroOFI.TIPO_NC and not v.is_chiuso)


def classificazione_di(voce) -> str:
    """Classificazione dell'ente ricavata dalla voce MOD.174 (il prefisso messo da ``crea_rilievo``)."""
    for _codice, etichetta in CLASSIFICAZIONI:
        if voce.opportunita.startswith(f"[{etichetta}]"):
            return etichetta
    return _ETICHETTE["OFI"] if voce.tipo == "OFI" else "Non conformità"


def _testo_rilievo(voce) -> str:
    testo = voce.opportunita
    for _codice, etichetta in CLASSIFICAZIONI:
        if testo.startswith(f"[{etichetta}] "):
            return testo[len(etichetta) + 3:]
    return testo


def piano_da_inviare(audit: AuditEsterno) -> bool:
    """L'ente aspetta un piano azioni (data fissata o NC registrate) e l'invio non è registrato."""
    if audit.piano_inviato_il:
        return False
    return bool(audit.risposta_entro) or any(v.tipo == "NC" for v in rilievi(audit))


def problemi_chiusura(audit: AuditEsterno) -> list[str]:
    """Cosa manca per chiudere l'audit esterno."""
    problemi = []
    if piano_da_inviare(audit) and rilievi(audit).exists():
        problemi.append("Registra l'invio del piano azioni all'ente.")
    if not audit.esito:
        problemi.append("Registra l'esito comunicato dall'ente.")
    if not audit.rapporto:
        problemi.append("Carica il rapporto dell'ente.")
    aperte = nc_aperte(audit)
    if aperte:
        problemi.append(f"Ci sono {aperte} non conformità ancora aperte nel Registro OFI.")
    return problemi


def scadenze(oggi=None, *, giorni_risposta: int = 7, giorni_sorveglianza: int = 30) -> dict:
    """Certificati scaduti o in scadenza, sorveglianze vicine, risposte all'ente da inviare."""
    oggi = oggi or timezone.localdate()
    certificati = [c for c in Certificazione.objects.filter(attiva=True) if c.stato in ("scaduta", "in_scadenza")]
    sorveglianze = list(Certificazione.objects.filter(
        attiva=True, prossima_sorveglianza__isnull=False,
        prossima_sorveglianza__lte=oggi + timedelta(days=giorni_sorveglianza)).order_by("prossima_sorveglianza"))
    risposte = list(AuditEsterno.objects.exclude(stato=AuditEsterno.STATO_CHIUSO).filter(
        piano_inviato_il__isnull=True, risposta_entro__isnull=False, risposta_entro__lte=oggi + timedelta(days=giorni_risposta))
        .order_by("risposta_entro"))
    return {"certificati": certificati, "sorveglianze": sorveglianze, "risposte": risposte}


COLONNE_PIANO = ["N. MOD.174", "Classificazione", "Requisito", "Processo / area", "Rilievo dell'ente",
                 "Analisi delle cause e azione pianificata (PLAN)", "Attuazione (DO)", "Verifica di efficacia (CHECK)",
                 "Responsabile", "Chiusura entro", "Stato"]


def righe_piano_azioni(audit: AuditEsterno) -> list[list]:
    """Piano azioni da inviare all'ente: una riga per rilievo, dai testi PDCA del Registro OFI."""
    righe = []
    for v in rilievi(audit):
        stato = "Chiuso" if v.is_chiuso else f"In corso: {v.get_fase_display()}"
        righe.append([
            v.numero, classificazione_di(v), v.rif_norma, v.processo, _testo_rilievo(v), v.plan, v.do, v.verifica,
            (v.responsabile.get_full_name() or v.responsabile.get_username()) if v.responsabile_id else v.proprietario,
            v.data_richiesta, stato,
        ])
    return righe


def audit_precedente(audit: AuditEsterno):
    """L'ultimo audit dello stesso certificato (o, senza certificato, dello stesso ente) prima di questo."""
    qs = AuditEsterno.objects.filter(data_inizio__lt=audit.data_inizio).exclude(pk=audit.pk)
    if audit.certificazione_id:
        qs = qs.filter(certificazione=audit.certificazione)
    else:
        qs = qs.filter(ente__iexact=audit.ente)
    return qs.order_by("-data_inizio", "-pk").first()


def _voce_breve(v) -> str:
    entro = f", entro il {v.data_richiesta:%d/%m/%Y}" if v.data_richiesta else ""
    return f"MOD.174 n. {v.numero} · {v.processo or v.rif_norma or v.fonte or '—'} · fase {v.get_fase_display()}{entro}"


def preparazione(audit: AuditEsterno, oggi=None) -> list[dict]:
    """Stato di preparazione all'audit dell'ente: cosa l'auditor dell'ente guarderà per primo.

    Ogni controllo ha ``stato`` "ok", "attenzione" o "critico", una sintesi, le voci da sistemare
    e un collegamento. Si basa sulle norme dell'audit e sul periodo che lo precede.
    """
    from gestione_specifiche.models import RegistroOFI

    from .cruscotto import avanzamento_programma, copertura_clausole

    oggi = oggi or timezone.localdate()
    riferimento = audit.data_inizio
    flags = {campo for campo, _etichetta in NORME_SGI if getattr(audit, campo)}
    controlli = []

    def aggiungi(titolo, stato, sintesi, voci=(), link=""):
        controlli.append({"titolo": titolo, "stato": stato, "sintesi": sintesi, "voci": list(voci), "link": link})

    cert = audit.certificazione
    if cert is not None:
        if cert.stato == "scaduta":
            aggiungi("Certificato", "critico", f"Il certificato {cert} è scaduto il {cert.scade_il:%d/%m/%Y}.")
        else:
            aggiungi("Certificato", "ok", f"{cert} valido fino al {cert.scade_il:%d/%m/%Y}.")

    if flags:
        copertura = copertura_clausole(dal=riferimento - timedelta(days=365), al=riferimento, solo_norme=flags)
        voci = [f"{n['norma']}: non verificate {', '.join(n['mancanti'])}" for n in copertura if n["mancanti"]]
        minima = min((n["percentuale"] for n in copertura), default=100)
        sintesi = "; ".join(f"{n['norma']} {n['verificate']}/{n['richieste']} ({n['percentuale']}%)" for n in copertura)
        aggiungi("Clausole verificate dagli audit interni negli ultimi 12 mesi",
                 "ok" if not voci else "critico" if minima < 50 else "attenzione",
                 sintesi or "Nessuna clausola delle norme dell'audit nel catalogo processi.", voci,
                 "sistema_gestione:audit_cruscotto")

    avanzamento = avanzamento_programma(riferimento.year, min(oggi, riferimento))
    titolo = f"Programma degli audit interni {riferimento.year}"
    if avanzamento["programma"] is None:
        aggiungi(titolo, "critico", "Nessun programma approvato per l'anno dell'audit.", link="sistema_gestione:audit_index")
    else:
        ritardi = avanzamento["ritardi"]
        aggiungi(titolo, "attenzione" if ritardi else "ok",
                 f"{avanzamento['eseguiti']} audit eseguiti su {avanzamento['pianificati']} pianificati"
                 + (f", {len(ritardi)} in ritardo." if ritardi else "."),
                 [f"{c.riga.area} · mese {c.mese}" for c in ritardi], "sistema_gestione:audit_cruscotto")

    nc_interne = list(AuditEsito.objects.filter(
        esito=AuditEsito.ESITO_NC, audit__rapporto_firmato_auditor_il__isnull=False,
        audit__data_inizio__gte=riferimento - timedelta(days=730)).exclude(audit__stato=Audit.STATO_ANNULLATO)
        .select_related("audit", "ofi").order_by("audit__data_inizio", "pk"))
    senza_azione = [e for e in nc_interne if not e.ofi_id or not e.ofi.is_chiuso]
    voci = [f"{e.audit.numero}{' § ' + e.clausola_effettiva if e.clausola_effettiva else ''} · "
            + (f"MOD.174 n. {e.ofi.numero}, fase {e.ofi.get_fase_display()}" if e.ofi_id else "nessuna voce MOD.174")
            for e in senza_azione]
    aggiungi("Non conformità degli audit interni (24 mesi)", "attenzione" if senza_azione else "ok",
             f"{len(nc_interne)} NC, {len(senza_azione)} con azione non ancora chiusa.", voci,
             "sistema_gestione:audit_cruscotto")

    chiuse = [e for e in nc_interne if e.ofi_id and e.ofi.is_chiuso]
    if chiuse:
        ultime: dict[int, str] = {}
        for v in (AuditVerificaEfficacia.objects.filter(esito__in=chiuse)
                  .order_by("esito_id", "-registrato_il").values("esito_id", "risultato")):
            ultime.setdefault(v["esito_id"], v["risultato"])
        da_verificare = [e for e in chiuse if ultime.get(e.pk) != "EFFICACE"]
        aggiungi("Efficacia delle azioni sulle NC interne", "attenzione" if da_verificare else "ok",
                 f"{len(chiuse) - len(da_verificare)} azioni chiuse su {len(chiuse)} verificate efficaci.",
                 [f"{e.audit.numero} · MOD.174 n. {e.ofi.numero}: efficacia "
                  + ("non dimostrata" if ultime.get(e.pk) else "da verificare") for e in da_verificare])

    aperte = RegistroOFI.objects.exclude(fase=RegistroOFI.FASE_CHIUSO).filter(data_chiusura__isnull=True)
    if flags:
        filtro = Q()
        for campo in flags:
            filtro |= Q(**{_NORME[campo]: True})
        aperte = aperte.filter(filtro)
    aperte = list(aperte.order_by("data_richiesta", "numero"))
    scadute = [v for v in aperte if v.is_scaduto]
    aggiungi("Registro OFI sulle norme dell'audit",
             "critico" if any(v.tipo == "NC" for v in scadute) else "attenzione" if scadute else "ok",
             f"{len(aperte)} voci aperte, {len(scadute)} oltre la data richiesta.",
             [_voce_breve(v) for v in scadute], "registro_ofi:cruscotto")

    precedente = audit_precedente(audit)
    if precedente is None:
        aggiungi("Rilievi dell'audit precedente dell'ente", "ok", "Nessun audit precedente registrato.")
    else:
        da_chiudere = [v for v in rilievi(precedente) if not v.is_chiuso]
        nc = [v for v in da_chiudere if v.tipo == "NC"]
        aggiungi("Rilievi dell'audit precedente dell'ente",
                 "critico" if nc else "attenzione" if da_chiudere else "ok",
                 f"{precedente}: {len(da_chiudere)} rilievi ancora aperti, di cui {len(nc)} NC." if da_chiudere
                 else f"{precedente}: tutti i rilievi sono chiusi.",
                 [_voce_breve(v) for v in da_chiudere], f"precedente:{precedente.pk}")

    auditor = list(Auditor.objects.filter(attivo=True, interno=True).select_related("user"))
    if not auditor:
        aggiungi("Auditor interni", "critico", "Nessun auditor interno attivo.", link="sistema_gestione:auditor_elenco")
    else:
        scaduti = [a for a in auditor if a.qualifica_scaduta]
        aggiungi("Auditor interni", "attenzione" if scaduti else "ok",
                 f"{len(auditor)} auditor interni attivi, {len(scaduti)} con qualifica scaduta.",
                 [f"{a.nome}: qualifica scaduta il {a.qualifica_scadenza:%d/%m/%Y}" for a in scaduti],
                 "sistema_gestione:auditor_elenco")
    return controlli


ETICHETTE_STATO = {"ok": "In ordine", "attenzione": "Da sistemare", "critico": "Critico"}
COLONNE_PREPARAZIONE = ["Controllo", "Stato", "Sintesi", "Da sistemare"]


def esito_preparazione(controlli: list[dict]) -> str:
    stati = {c["stato"] for c in controlli}
    return "critico" if "critico" in stati else "attenzione" if "attenzione" in stati else "ok"


def righe_preparazione(controlli: list[dict]) -> list[list]:
    righe = []
    for c in controlli:
        righe.append([c["titolo"], ETICHETTE_STATO[c["stato"]], c["sintesi"], ""])
        righe += [[c["titolo"], "", "", voce] for voce in c["voci"]]
    return righe


def rilievi_esterni_recenti(oggi=None, giorni: int = 730) -> list[dict]:
    """Rilievi degli enti degli ultimi ``giorni``: tipo e processo/area come scritti nel rilievo."""
    from gestione_specifiche.models import RegistroOFI
    oggi = oggi or timezone.localdate()
    return list(RegistroOFI.objects.filter(
        content_type__app_label=AuditEsterno._meta.app_label, content_type__model=AuditEsterno._meta.model_name,
        data_apertura__gte=oggi - timedelta(days=giorni),
                                           data_apertura__lte=oggi).values("tipo", "processo"))


def esterni_anno(anno: int) -> dict:
    """Per il cruscotto: audit esterni dell'anno e loro rilievi per classificazione."""
    from collections import Counter
    audit_list = list(AuditEsterno.objects.filter(data_inizio__year=anno).select_related("certificazione"))
    conteggi: Counter = Counter()
    nc_aperte = 0
    for a in audit_list:
        voci = list(rilievi(a))
        a.n_rilievi = len(voci)
        a.n_nc_aperte = sum(1 for v in voci if v.tipo == "NC" and not v.is_chiuso)
        a.piano_mancante = not a.piano_inviato_il and bool(a.risposta_entro or any(v.tipo == "NC" for v in voci))
        nc_aperte += a.n_nc_aperte
        for v in voci:
            conteggi[classificazione_di(v)] += 1
    return {"audit": audit_list, "per_classificazione": [(e, conteggi[e]) for _c, e in CLASSIFICAZIONI],
            "nc_aperte": nc_aperte}
