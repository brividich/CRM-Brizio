"""Report area Salute e sicurezza sul lavoro."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from ..people import cessati_ids
from ..registry import (
    AREA_SICUREZZA,
    ISO_45001,
    ISO_9001,
    TONE_DANGER,
    TONE_OK,
    TONE_WARN,
    Kpi,
    ReportDef,
    ReportParams,
    ReportResult,
    c,
    register,
)
from ._common import d, days_between, link, links, pct, short, yes_no

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Eventi: infortuni, quasi infortuni, condizioni e atti insicuri
# ---------------------------------------------------------------------------


def _eventi_sicurezza(params: ReportParams) -> ReportResult:
    from rilevazione_incidenti.models import RilevazioneIncidente

    result = ReportResult()
    eventi = list(
        RilevazioneIncidente.objects.filter(
            data_segnalazione__date__range=(params.date_from, params.date_to)
        ).order_by("-data_segnalazione", "-id")
    )
    per_tipo = defaultdict(int)
    aperti = con_analisi = 0
    durate = []
    result.columns = ["Data", "Scheda", "Tipo evento", "Reparto", "Causa", "Analisi 5 perché",
                      "Misure tecniche", "Approvazione RLS", "Chiusura RSPP", "Giorni"]
    for e in eventi:
        tipo = e.get_tipo_evento_display() if e.tipo_evento else ""
        per_tipo[e.tipo_evento or "altro"] += 1
        analisi = bool((e.why_1 or "").strip())
        con_analisi += int(analisi)
        chiuso = bool(e.chiusura_rspp)
        giorni = days_between(e.data_segnalazione, e.data_chiusura_rspp) if chiuso else None
        if chiuso and giorni is not None:
            durate.append(giorni)
        if not chiuso:
            aperti += 1
        tone = TONE_OK if chiuso else (TONE_DANGER if e.tipo_evento == "incidente" else TONE_WARN)
        result.add_row(
            [d(e.data_segnalazione), e.tipologia_scheda, tipo, e.reparto, short(e.causa_evento, 80),
             yes_no(analisi), short(e.quali_misure, 80) if e.misure_tecniche else "No",
             e.approvazione_rls, d(e.data_chiusura_rspp) if chiuso else "Aperta",
             giorni if giorni is not None else ""],
            tone,
        )
    totale = len(eventi)
    result.kpis = [
        Kpi("Eventi nel periodo", totale),
        Kpi("Infortuni", per_tipo["incidente"], TONE_DANGER if per_tipo["incidente"] else TONE_OK),
        Kpi("Quasi infortuni", per_tipo["near_miss"]),
        Kpi("Condizioni/atti insicuri", per_tipo["unsafe_condition"]),
        Kpi("Non chiusi dall'RSPP", aperti, TONE_WARN if aperti else TONE_OK),
        Kpi("Con analisi delle cause", pct(con_analisi, totale)),
        Kpi("Giorni medi di chiusura", round(sum(durate) / len(durate)) if durate else "n/d"),
    ]
    result.notes = [
        "Il nominativo del segnalante non è riportato (minimizzazione): il dettaglio resta nel modulo Segnalazioni sicurezza.",
        "Gli indici di frequenza e gravità richiedono ore lavorate e giorni di prognosi, oggi non registrati: non calcolati.",
    ]
    result.links = links(("Segnalazioni sicurezza", "rilevazione_incidenti:lista"))
    return result


register(ReportDef(
    slug="eventi-sicurezza",
    title="Infortuni, quasi infortuni e situazioni pericolose",
    area=AREA_SICUREZZA,
    description="Eventi segnalati per tipo, analisi delle cause, tempi di chiusura RSPP.",
    clausole=(c(ISO_45001, "9.1.1"), c(ISO_45001, "10.2"), c(ISO_45001, "5.4")),
    builder=_eventi_sicurezza,
    fonte="Segnalazioni sicurezza",
))


# ---------------------------------------------------------------------------
# DPI: consegne, ricevute firmate, sostituzioni scadute
# ---------------------------------------------------------------------------


def _dpi(params: ReportParams) -> ReportResult:
    from dpi.models import ConsegnaDPI, RichiestaDPI

    result = ReportResult()
    consegne_periodo = ConsegnaDPI.objects.filter(data_consegna__range=(params.date_from, params.date_to))
    n_periodo = consegne_periodo.count()
    firmate = consegne_periodo.filter(firmato_ricevuta=True).count()

    esclusi = cessati_ids(params.today)
    attive = (
        ConsegnaDPI.objects.filter(sostituita_da__isnull=True, richiesta__stato="CONSEGNATA")
        .exclude(richiesta__richiedente_legacy_id__in=esclusi)
        .select_related("richiesta__categoria", "richiesta__tipo_dpi")
    )
    limite = params.today + timedelta(days=30)
    da_gestire = attive.filter(data_scadenza_stimata__isnull=False, data_scadenza_stimata__lte=limite) | attive.filter(
        firmato_ricevuta=False
    )
    scadute = 0
    senza_firma = 0
    result.columns = ["Richiesta", "Dipendente", "Reparto", "Categoria", "Tipo", "Consegnato il",
                      "Ricevuta firmata", "Sostituzione prevista", "Stato"]
    for cons in da_gestire.distinct().order_by("data_scadenza_stimata", "data_consegna"):
        r = cons.richiesta
        stato, tone = "Ricevuta non firmata", TONE_WARN
        if cons.data_scadenza_stimata and cons.data_scadenza_stimata < params.today:
            stato, tone = "Da sostituire (scaduto)", TONE_DANGER
            scadute += 1
        elif cons.data_scadenza_stimata and cons.data_scadenza_stimata <= limite:
            stato, tone = "Sostituzione entro 30 gg", TONE_WARN
        if not cons.firmato_ricevuta:
            senza_firma += 1
        result.add_row(
            [r.numero, r.richiedente_nome, r.richiedente_reparto, str(r.categoria or ""), str(r.tipo_dpi or ""),
             d(cons.data_consegna), yes_no(cons.firmato_ricevuta), d(cons.data_scadenza_stimata), stato],
            tone,
        )
    in_attesa = RichiestaDPI.objects.filter(stato__in=("INVIATA", "APPROVATA"))
    vecchie = in_attesa.filter(created_at__date__lt=params.today - timedelta(days=15)).count()
    result.kpis = [
        Kpi("Consegne nel periodo", n_periodo),
        Kpi("Con ricevuta firmata", pct(firmate, n_periodo),
            TONE_OK if n_periodo and firmate == n_periodo else TONE_WARN if n_periodo else ""),
        Kpi("DPI in uso da sostituire", scadute, TONE_DANGER if scadute else TONE_OK),
        Kpi("Ricevute non firmate (in uso)", senza_firma, TONE_WARN if senza_firma else TONE_OK),
        Kpi("Richieste in attesa", in_attesa.count()),
        Kpi("in attesa da oltre 15 gg", vecchie, TONE_WARN if vecchie else ""),
    ]
    result.notes = [
        "Righe: DPI in uso (non sostituiti) con sostituzione prevista entro 30 giorni o ricevuta non firmata. Cessati esclusi.",
        "La data di sostituzione è stimata dalla durata del tipo DPI alla consegna.",
    ]
    result.links = links(("DPI", "dpi:dashboard"))
    return result


register(ReportDef(
    slug="dpi",
    title="Dispositivi di protezione individuale",
    area=AREA_SICUREZZA,
    description="Consegne con ricevuta, DPI in uso da sostituire, richieste in attesa.",
    clausole=(c(ISO_45001, "8.1.2"), c(ISO_45001, "7.5")),
    builder=_dpi,
    fonte="DPI",
))


# ---------------------------------------------------------------------------
# Scadenziario degli obblighi di legge (valutazione della conformita')
# ---------------------------------------------------------------------------


def _conta(label, riferimento, scadute, in_scadenza, totale, route=None, query=""):
    return {
        "label": label, "rif": riferimento, "scadute": scadute, "in_scadenza": in_scadenza,
        "totale": totale, "link": link("Apri", route, query) if route else None,
    }


def _scadenziario_legale(params: ReportParams) -> ReportResult:
    result = ReportResult()
    oggi = params.today
    limite = oggi + timedelta(days=30)
    esclusi = cessati_ids(oggi)
    voci = []

    try:
        from anagrafica.models import TrainingDeadline

        qs = TrainingDeadline.objects.filter(is_required=True).exclude(legacy_anagrafica_id__in=esclusi)
        voci.append(_conta(
            "Formazione obbligatoria", "D.Lgs. 81/08 artt. 36-37, Accordo Stato-Regioni",
            qs.filter(stato_scadenza__in=("SCADUTO", "MAI_FREQUENTATO")).count(),
            qs.filter(stato_scadenza="IN_SCADENZA_30").count(), qs.count(),
            "anagrafica:formazione_scadenzario",
        ))
    except Exception:
        logger.warning("scadenziario legale: formazione non disponibile", exc_info=True)

    try:
        from anagrafica.models import VisitaMedica
        from anagrafica.services.visite import ultime_visite_correnti_ids

        correnti = VisitaMedica.objects.filter(id__in=ultime_visite_correnti_ids(), data_scadenza__isnull=False)
        voci.append(_conta(
            "Sorveglianza sanitaria (visite)", "D.Lgs. 81/08 art. 41",
            correnti.filter(data_scadenza__lt=oggi).count(),
            correnti.filter(data_scadenza__range=(oggi, limite)).count(), correnti.count(),
            "anagrafica:visite_mediche_dashboard",
        ))
    except Exception:
        logger.warning("scadenziario legale: visite non disponibili", exc_info=True)

    try:
        from assets.models import PeriodicVerification

        qs = PeriodicVerification.objects.filter(is_active=True)
        voci.append(_conta(
            "Verifiche periodiche attrezzature e impianti", "D.Lgs. 81/08 art. 71, DM 11/04/2011",
            qs.filter(next_verification_date__lt=oggi).count(),
            qs.filter(next_verification_date__range=(oggi, limite)).count(), qs.count(),
            "assets:periodic_verifications",
        ))
    except Exception:
        logger.warning("scadenziario legale: verifiche non disponibili", exc_info=True)

    try:
        from assets.models import AssetAdministrativeDeadline

        qs = AssetAdministrativeDeadline.objects.filter(is_active=True)
        voci.append(_conta(
            "Scadenze amministrative asset", "Libretti, revisioni, collaudi, certificazioni",
            qs.filter(due_date__lt=oggi).count(), qs.filter(due_date__range=(oggi, limite)).count(), qs.count(),
            "assets:maintenance_scadenze",
        ))
    except Exception:
        logger.warning("scadenziario legale: scadenze asset non disponibili", exc_info=True)

    try:
        from dpi.models import ConsegnaDPI

        qs = ConsegnaDPI.objects.filter(
            sostituita_da__isnull=True, richiesta__stato="CONSEGNATA", data_scadenza_stimata__isnull=False
        ).exclude(richiesta__richiedente_legacy_id__in=esclusi)
        voci.append(_conta(
            "Sostituzione DPI", "D.Lgs. 81/08 art. 77",
            qs.filter(data_scadenza_stimata__lt=oggi).count(),
            qs.filter(data_scadenza_stimata__range=(oggi, limite)).count(), qs.count(),
            "dpi:dashboard",
        ))
    except Exception:
        logger.warning("scadenziario legale: DPI non disponibili", exc_info=True)

    try:
        from schede_sicurezza.models import ProdottoChimico
        from schede_sicurezza.reports import prodotti_senza_scheda_corrente

        senza = len(list(prodotti_senza_scheda_corrente()))
        voci.append(_conta(
            "Schede di sicurezza prodotti chimici", "Reg. CE 1907/2006 (REACH) art. 31, D.Lgs. 81/08 Titolo IX",
            senza, 0, ProdottoChimico.objects.count(), "schede_sicurezza:report_compliance",
        ))
    except Exception:
        logger.warning("scadenziario legale: SDS non disponibili", exc_info=True)

    result.columns = ["Ambito", "Riferimento", "Scadute / mancanti", "In scadenza 30 gg", "Totale monitorato", "Conformità"]
    tot_scad = tot_in = tot = 0
    for v in voci:
        tot_scad += v["scadute"]
        tot_in += v["in_scadenza"]
        tot += v["totale"]
        tone = TONE_DANGER if v["scadute"] else (TONE_WARN if v["in_scadenza"] else TONE_OK)
        result.add_row(
            [v["label"], v["rif"], v["scadute"], v["in_scadenza"], v["totale"],
             pct(v["totale"] - v["scadute"], v["totale"])],
            tone,
        )
        if v["link"]:
            result.links.append((v["label"], v["link"][1]))
    result.kpis = [
        Kpi("Ambiti monitorati", len(voci)),
        Kpi("Scadute / mancanti", tot_scad, TONE_DANGER if tot_scad else TONE_OK),
        Kpi("In scadenza 30 gg", tot_in, TONE_WARN if tot_in else ""),
        Kpi("Conformità complessiva", pct(tot - tot_scad, tot)),
    ]
    result.notes = [
        "Solo conteggi, nessun dato nominativo (le visite mediche in particolare): il dettaglio si apre nel modulo, con i suoi permessi.",
        "Visite: solo la visita corrente per dipendente e famiglia (quelle superate non contano), dipendenti in forza.",
        "Fotografia alla data odierna: il periodo non si applica.",
    ]
    return result


register(ReportDef(
    slug="scadenziario-legale",
    title="Scadenziario degli obblighi di legge",
    area=AREA_SICUREZZA,
    description="Formazione, visite, verifiche attrezzature, DPI, schede di sicurezza: scadute e in arrivo.",
    clausole=(c(ISO_45001, "6.1.3"), c(ISO_45001, "9.1.2"), c(ISO_9001, "4.2")),
    builder=_scadenziario_legale,
    usa_periodo=False,
    fonte="Anagrafica, Asset, DPI, Schede di sicurezza",
))
