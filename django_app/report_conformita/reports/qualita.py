"""Report area Qualita' e processi."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Q

from ..registry import (
    AREA_QUALITA,
    EN_9100,
    ISO_27001,
    ISO_45001,
    ISO_9001,
    TONE_DANGER,
    TONE_OK,
    TONE_WARN,
    Filtro,
    Kpi,
    ReportDef,
    ReportParams,
    ReportResult,
    c,
    register,
)
from ._common import d, days_between, links, pct, scadenza_stato, short

# ---------------------------------------------------------------------------
# Registro NC / OFI
# ---------------------------------------------------------------------------

_NORMA_FILTRO = Filtro(
    "norma",
    "Norma",
    (("", "Tutte"), ("9100", "EN 9100"), ("45001", "ISO 45001"), ("27001", "ISO 27001")),
)
_NORMA_FIELD = {"9100": "norma_en9100", "45001": "norma_iso45001", "27001": "norma_iso27001"}


def _registro_nc_ofi(params: ReportParams) -> ReportResult:
    from gestione_specifiche.models import RegistroOFI

    result = ReportResult()
    base = RegistroOFI.objects.all()
    norma = params.extra.get("norma", "")
    if norma in _NORMA_FIELD:
        base = base.filter(**{_NORMA_FIELD[norma]: True})

    aperte = base.exclude(fase=RegistroOFI.FASE_CHIUSO)
    nel_periodo = base.filter(data_apertura__range=(params.date_from, params.date_to))
    chiuse_periodo = base.filter(
        fase=RegistroOFI.FASE_CHIUSO, data_chiusura__range=(params.date_from, params.date_to)
    )
    in_ritardo = aperte.filter(data_richiesta__lt=params.today)

    durate = [
        days_between(a, b)
        for a, b in chiuse_periodo.values_list("data_apertura", "data_chiusura")
        if a and b
    ]
    media = round(sum(durate) / len(durate)) if durate else None

    n_aperte = aperte.count()
    n_ritardo = in_ritardo.count()
    result.kpis = [
        Kpi("Aperte", n_aperte),
        Kpi("di cui non conformità", aperte.filter(tipo=RegistroOFI.TIPO_NC).count(),
            TONE_WARN if aperte.filter(tipo=RegistroOFI.TIPO_NC).exists() else ""),
        Kpi("Oltre la data di chiusura", n_ritardo, TONE_DANGER if n_ritardo else TONE_OK),
        Kpi("Aperte nel periodo", nel_periodo.count()),
        Kpi("Chiuse nel periodo", chiuse_periodo.count()),
        Kpi("Giorni medi di chiusura", media if media is not None else "n/d"),
    ]

    result.columns = [
        "N.", "Tipo", "Norme", "Rif. norma", "Processo", "Descrizione", "Priorità",
        "Fase", "Apertura", "Chiusura richiesta", "Chiusura", "Giorni", "Proprietario",
    ]
    righe = (
        base.filter(Q(data_apertura__range=(params.date_from, params.date_to)) | ~Q(fase=RegistroOFI.FASE_CHIUSO))
        .order_by("-data_apertura", "-numero")
    )
    for r in righe:
        norme = ["ISO 9001"]
        if r.norma_en9100:
            norme.append("EN 9100")
        if r.norma_iso45001:
            norme.append("ISO 45001")
        if r.norma_iso27001:
            norme.append("ISO 27001")
        chiusa = r.fase == RegistroOFI.FASE_CHIUSO
        giorni = days_between(r.data_apertura, r.data_chiusura if chiusa else params.today)
        tone = ""
        if not chiusa and r.data_richiesta and r.data_richiesta < params.today:
            tone = TONE_DANGER
        elif not chiusa and r.tipo == RegistroOFI.TIPO_NC:
            tone = TONE_WARN
        result.add_row(
            [
                r.numero, r.get_tipo_display(), ", ".join(norme), r.rif_norma, r.processo,
                short(r.opportunita), r.get_priorita_display(), r.get_fase_display(),
                d(r.data_apertura), d(r.data_richiesta), d(r.data_chiusura),
                giorni if giorni is not None else "", r.owner_processo or r.proprietario,
            ],
            tone,
        )
    result.notes = [
        "Righe: tutte le voci aperte, più quelle aperte nel periodo e già chiuse.",
        "ISO 9001 è sempre inclusa: il registro è quello del sistema qualità; le altre norme seguono le spunte della voce.",
    ]
    result.links = links(("Registro OFI", "registro_ofi:lista"))
    return result


register(ReportDef(
    slug="registro-nc-ofi",
    title="Non conformità e azioni di miglioramento",
    area=AREA_QUALITA,
    description="Stato del registro NC/OFI: aperte, in ritardo, tempi di chiusura, ciclo PDCA.",
    clausole=(c(ISO_9001, "10.2"), c(ISO_9001, "10.3"), c(EN_9100, "10.2"),
              c(ISO_45001, "10.2"), c(ISO_27001, "10.2")),
    builder=_registro_nc_ofi,
    filtri=(_NORMA_FILTRO,),
    fonte="Registro OFI",
))


# ---------------------------------------------------------------------------
# Albo fornitori
# ---------------------------------------------------------------------------

def _albo_fornitori(params: ReportParams) -> ReportResult:
    from anagrafica.models import Fornitore, FornitoreDocumento, FornitoreValutazione

    result = ReportResult()
    fornitori = list(Fornitore.objects.filter(is_active=True).order_by("ragione_sociale"))
    ids = [f.id for f in fornitori]

    ultime: dict[int, FornitoreValutazione] = {}
    per_periodo: dict[int, int] = defaultdict(int)
    for v in FornitoreValutazione.objects.filter(fornitore_id__in=ids).order_by("fornitore_id", "-data", "-id"):
        ultime.setdefault(v.fornitore_id, v)
        if params.date_from <= v.data <= params.date_to:
            per_periodo[v.fornitore_id] += 1
    certificazioni = dict(
        FornitoreDocumento.objects.filter(fornitore_id__in=ids, tipo="CERTIFICAZIONE")
        .order_by()
        .values("fornitore_id")
        .annotate(n=Count("id"))
        .values_list("fornitore_id", "n")
    )

    soglia_rivalutazione = params.today - timedelta(days=365)
    counts = {"ok": 0, "rivalutare": 0, "insufficiente": 0, "mai": 0}
    result.columns = [
        "Fornitore", "Categoria", "Ultima valutazione", "Qualità", "Puntualità",
        "Comunicazione", "Media", "Valutazioni nel periodo", "Certificazioni caricate", "Esito",
    ]
    for f in fornitori:
        v = ultime.get(f.id)
        if v is None:
            esito, tone, key = "Mai valutato", TONE_WARN, "mai"
            media = ""
        else:
            media_val = round((v.qualita + v.puntualita + v.comunicazione) / 3, 1)
            media = media_val
            if media_val < 3:
                esito, tone, key = "Insufficiente", TONE_DANGER, "insufficiente"
            elif v.data < soglia_rivalutazione:
                esito, tone, key = "Da rivalutare (oltre 12 mesi)", TONE_WARN, "rivalutare"
            else:
                esito, tone, key = "Qualificato", TONE_OK, "ok"
        counts[key] += 1
        result.add_row(
            [
                f.ragione_sociale, f.get_categoria_display(), d(v.data) if v else "",
                v.qualita if v else "", v.puntualita if v else "", v.comunicazione if v else "",
                media, per_periodo.get(f.id, 0), certificazioni.get(f.id, 0), esito,
            ],
            tone,
        )

    totale = len(fornitori)
    result.kpis = [
        Kpi("Fornitori attivi", totale),
        Kpi("Qualificati", counts["ok"], TONE_OK, pct(counts["ok"], totale)),
        Kpi("Da rivalutare", counts["rivalutare"], TONE_WARN if counts["rivalutare"] else ""),
        Kpi("Insufficienti (media < 3)", counts["insufficiente"], TONE_DANGER if counts["insufficiente"] else ""),
        Kpi("Mai valutati", counts["mai"], TONE_WARN if counts["mai"] else ""),
        Kpi("Valutazioni nel periodo", sum(per_periodo.values())),
    ]
    result.notes = [
        "Scala di valutazione 1–5 su qualità, puntualità, comunicazione; esito sull'ultima valutazione.",
        "Criterio: media < 3 = insufficiente; ultima valutazione oltre 12 mesi = da rivalutare.",
        "EN 9100 §8.4.1 chiede l'albo con stato di approvazione e ambito: la puntualità è la base del KPI consegne.",
    ]
    result.links = links(("Anagrafica fornitori", "fornitori:fornitori_list"))
    return result


register(ReportDef(
    slug="albo-fornitori",
    title="Albo fornitori qualificati",
    area=AREA_QUALITA,
    description="Stato di qualifica dei fornitori attivi, ultima valutazione, rivalutazioni scadute.",
    clausole=(c(ISO_9001, "8.4.1"), c(EN_9100, "8.4.1"), c(ISO_27001, "A.5.19–5.22")),
    builder=_albo_fornitori,
    fonte="Fornitori",
))


# ---------------------------------------------------------------------------
# Strumenti e verifiche periodiche
# ---------------------------------------------------------------------------

def _verifiche_periodiche(params: ReportParams) -> ReportResult:
    from assets.models import PeriodicVerification

    result = ReportResult()
    verifiche = (
        PeriodicVerification.objects.filter(is_active=True)
        .select_related("supplier")
        .prefetch_related("assets")
        .order_by("next_verification_date", "name")
    )
    counts = {TONE_DANGER: 0, TONE_WARN: 0, TONE_OK: 0}
    eseguite_periodo = 0
    result.columns = ["Verifica", "Fornitore", "Frequenza (mesi)", "Ultima", "Prossima", "Asset", "Stato"]
    for v in verifiche:
        stato, tone = scadenza_stato(v.next_verification_date, params.today)
        counts[tone] += 1
        if v.last_verification_date and params.date_from <= v.last_verification_date <= params.date_to:
            eseguite_periodo += 1
        tags = [a.asset_tag or a.name for a in v.assets.all()]
        asset_label = ", ".join(tags[:6]) + (f" +{len(tags) - 6}" if len(tags) > 6 else "")
        result.add_row(
            [v.name, str(v.supplier) if v.supplier_id else "", v.frequency_months,
             d(v.last_verification_date), d(v.next_verification_date), asset_label, stato],
            tone,
        )
    totale = sum(counts.values())
    result.kpis = [
        Kpi("Verifiche attive", totale),
        Kpi("Scadute / senza data", counts[TONE_DANGER], TONE_DANGER if counts[TONE_DANGER] else TONE_OK),
        Kpi("In scadenza 30 gg", counts[TONE_WARN], TONE_WARN if counts[TONE_WARN] else ""),
        Kpi("In regola", counts[TONE_OK], TONE_OK, pct(counts[TONE_OK], totale)),
        Kpi("Eseguite nel periodo", eseguite_periodo),
    ]
    result.notes = [
        "Comprende tarature e verifiche periodiche registrate in Asset (strumenti di misura, apparecchi di sollevamento, impianti).",
        "EN 9100 §7.1.5.2: per uno strumento trovato fuori tolleranza va valutato l'effetto sui prodotti misurati (richiamo).",
    ]
    result.links = links(("Verifiche periodiche", "assets:periodic_verifications"))
    return result


register(ReportDef(
    slug="verifiche-periodiche",
    title="Strumenti di misura e verifiche periodiche",
    area=AREA_QUALITA,
    description="Registro tarature/verifiche con scadenze superate e in arrivo.",
    clausole=(c(ISO_9001, "7.1.5"), c(EN_9100, "7.1.5.2"), c(ISO_45001, "9.1.1")),
    builder=_verifiche_periodiche,
    fonte="Asset › Verifiche periodiche",
))


# ---------------------------------------------------------------------------
# Presa visione procedure
# ---------------------------------------------------------------------------

def _presa_visione(params: ReportParams) -> ReportResult:
    from procedure_refresh.models import ProcedureAssignment, ProcedureRevision

    result = ReportResult()
    revisioni = list(
        ProcedureRevision.objects.filter(is_current=True, document__is_active=True)
        .select_related("document")
        .order_by("document__code")
    )
    stats: dict[int, dict[str, int]] = defaultdict(lambda: {"tot": 0, "ok": 0, "late": 0})
    assignments = (
        ProcedureAssignment.objects.filter(revision__in=revisioni)
        .exclude(status="cancelled")
        .values_list("revision_id", "status", "read_confirmed_flag", "due_date")
    )
    for revision_id, status, confirmed, due in assignments:
        bucket = stats[revision_id]
        bucket["tot"] += 1
        if confirmed or status == "read_confirmed":
            bucket["ok"] += 1
        elif status == "overdue" or (due and due < params.today):
            bucket["late"] += 1

    result.columns = ["Codice", "Titolo", "Revisione", "In vigore dal", "Assegnati", "Confermati", "%", "In ritardo"]
    tot = ok = late = senza = 0
    for rev in revisioni:
        s = stats.get(rev.id, {"tot": 0, "ok": 0, "late": 0})
        tot += s["tot"]
        ok += s["ok"]
        late += s["late"]
        if not s["tot"] and rev.document.requires_acknowledgement:
            senza += 1
        tone = TONE_DANGER if s["late"] else (TONE_OK if s["tot"] and s["ok"] == s["tot"] else "")
        result.add_row(
            [rev.document.code, rev.document.title, rev.revision_code, d(rev.effective_date or rev.revision_date),
             s["tot"], s["ok"], pct(s["ok"], s["tot"]), s["late"]],
            tone,
        )
    result.kpis = [
        Kpi("Documenti in vigore", len(revisioni)),
        Kpi("Prese visione assegnate", tot),
        Kpi("Confermate", ok, TONE_OK, pct(ok, tot)),
        Kpi("In ritardo", late, TONE_DANGER if late else TONE_OK),
        Kpi("Da confermare ma mai assegnati", senza, TONE_WARN if senza else ""),
    ]
    result.notes = [
        "Revisione corrente di ogni documento attivo; le assegnazioni annullate non contano.",
        "Evidenza di consapevolezza (§7.3) e di distribuzione controllata della revisione applicabile (§7.5.3, EN 9100 §8.1.2).",
    ]
    result.links = links(("Campagne presa visione", "procedure_refresh:admin_dashboard"))
    return result


register(ReportDef(
    slug="presa-visione",
    title="Presa visione di procedure e istruzioni",
    area=AREA_QUALITA,
    description="Chi ha confermato la lettura della revisione in vigore, chi è in ritardo.",
    clausole=(c(ISO_9001, "7.3"), c(ISO_9001, "7.5.3"), c(EN_9100, "8.1.2"),
              c(ISO_45001, "7.4"), c(ISO_27001, "7.3")),
    builder=_presa_visione,
    usa_periodo=False,
    fonte="Presa visione procedure",
))


# ---------------------------------------------------------------------------
# Manutenzione infrastrutture
# ---------------------------------------------------------------------------

def _manutenzione(params: ReportParams) -> ReportResult:
    from assets.models import MaintenanceOccurrence

    result = ReportResult()
    occorrenze = (
        MaintenanceOccurrence.objects.filter(due_date__range=(params.date_from, params.date_to))
        .exclude(status=MaintenanceOccurrence.STATUS_CANCELED)
        .select_related("asset__asset_category")
    )
    gruppi: dict[str, dict[str, int]] = defaultdict(
        lambda: {"pianificate": 0, "eseguite": 0, "in_tempo": 0, "scadute": 0, "fermo": 0}
    )
    for occ in occorrenze:
        categoria = getattr(getattr(occ.asset, "asset_category", None), "label", "") or "Senza categoria"
        g = gruppi[categoria]
        g["pianificate"] += 1
        if occ.status == MaintenanceOccurrence.STATUS_DONE:
            g["eseguite"] += 1
            if occ.completed_on and occ.completed_on <= occ.due_date:
                g["in_tempo"] += 1
            g["fermo"] += int(occ.downtime_minutes or 0)
        elif occ.due_date < params.today:
            g["scadute"] += 1

    result.columns = ["Categoria", "Pianificate", "Eseguite", "di cui nei tempi", "Scadute non eseguite",
                      "Rispetto piano", "Fermo macchina (ore)"]
    tot = {"pianificate": 0, "eseguite": 0, "in_tempo": 0, "scadute": 0, "fermo": 0}
    for categoria in sorted(gruppi, key=lambda k: (-gruppi[k]["scadute"], k.casefold())):
        g = gruppi[categoria]
        for key in tot:
            tot[key] += g[key]
        dovute = g["eseguite"] + g["scadute"]
        tone = TONE_DANGER if g["scadute"] else (TONE_OK if dovute else "")
        result.add_row(
            [categoria, g["pianificate"], g["eseguite"], g["in_tempo"], g["scadute"],
             pct(g["in_tempo"], dovute), round(g["fermo"] / 60, 1)],
            tone,
        )
    dovute = tot["eseguite"] + tot["scadute"]
    result.kpis = [
        Kpi("Manutenzioni pianificate", tot["pianificate"]),
        Kpi("Eseguite", tot["eseguite"]),
        Kpi("Rispetto del piano", pct(tot["in_tempo"], dovute),
            TONE_OK if dovute and tot["in_tempo"] * 100 >= dovute * 90 else TONE_WARN if dovute else ""),
        Kpi("Scadute non eseguite", tot["scadute"], TONE_DANGER if tot["scadute"] else TONE_OK),
        Kpi("Fermo macchina (ore)", round(tot["fermo"] / 60, 1)),
    ]
    result.notes = [
        "Scadenze pianificate (occorrenze) con data nel periodo, annullate escluse: stessa fonte di Scadenzario e Calendario.",
        "Rispetto piano = eseguite entro la data di scadenza / scadenze già dovute (eseguite + scadute).",
    ]
    result.links = links(("Scadenze manutenzione", "assets:maintenance_scadenze"))
    return result


register(ReportDef(
    slug="manutenzione",
    title="Manutenzione di macchine e infrastrutture",
    area=AREA_QUALITA,
    description="Rispetto del piano di manutenzione per categoria, scadenze saltate, fermi.",
    clausole=(c(ISO_9001, "7.1.3"), c(EN_9100, "8.5.1"), c(ISO_45001, "8.1.2")),
    builder=_manutenzione,
    fonte="Asset › Manutenzione",
))
