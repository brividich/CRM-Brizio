"""Report area Competenze e qualifiche."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from ..people import cessati_ids, persone
from ..registry import (
    AREA_PERSONE,
    EN_9100,
    ISO_27001,
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
from ._common import d, links, pct, scadenza_stato, short

# ---------------------------------------------------------------------------
# Competenze: formazione obbligatoria e qualifiche in scadenza
# ---------------------------------------------------------------------------

_STATI_KO = {"SCADUTO": "Scaduto", "MAI_FREQUENTATO": "Mai frequentato", "IN_SCADENZA_30": "In scadenza 30 gg"}
_STATI_COPERTI = {"VALIDO", "IN_SCADENZA_30", "IN_SCADENZA_90", "UNA_TANTUM"}


def _competenze(params: ReportParams) -> ReportResult:
    from anagrafica.models import DipendenteQualifica, TrainingDeadline

    result = ReportResult()
    esclusi = cessati_ids(params.today)

    scadenze = list(
        TrainingDeadline.objects.filter(is_required=True)
        .exclude(legacy_anagrafica_id__in=esclusi)
        .select_related("corso")
        .only("legacy_anagrafica_id", "stato_scadenza", "data_scadenza", "corso__titolo", "corso__codice")
    )
    totale_req = len(scadenze)
    coperti = sum(1 for s in scadenze if s.stato_scadenza in _STATI_COPERTI)
    conteggi = defaultdict(int)
    for s in scadenze:
        conteggi[s.stato_scadenza] += 1

    limite_qualifiche = params.today + timedelta(days=60)
    qualifiche = list(
        DipendenteQualifica.objects.filter(data_scadenza__isnull=False, data_scadenza__lte=limite_qualifiche)
        .exclude(legacy_anagrafica_id__in=esclusi)
        .select_related("tipo")
        .order_by("data_scadenza")
    )
    # Una qualifica rinnovata lascia la riga vecchia: conta solo l'ultima per tipo.
    rinnovate = {
        (q["legacy_anagrafica_id"], q["tipo_id"])
        for q in DipendenteQualifica.objects.filter(data_scadenza__gt=limite_qualifiche).values(
            "legacy_anagrafica_id", "tipo_id"
        )
    }
    qualifiche = [q for q in qualifiche if (q.legacy_anagrafica_id, q.tipo_id) not in rinnovate]

    ko = [s for s in scadenze if s.stato_scadenza in _STATI_KO]
    anag = persone([s.legacy_anagrafica_id for s in ko] + [q.legacy_anagrafica_id for q in qualifiche])

    result.columns = ["Dipendente", "Reparto", "Tipo", "Voce", "Scadenza", "Stato"]
    righe = []
    for s in ko:
        p = anag.get(s.legacy_anagrafica_id)
        tone = TONE_WARN if s.stato_scadenza == "IN_SCADENZA_30" else TONE_DANGER
        corso = getattr(s.corso, "titolo", "") or getattr(s.corso, "codice", "")
        righe.append(((p.reparto if p else ""), (p.nominativo if p else ""),
                      [p.nominativo if p else "", p.reparto if p else "", "Formazione obbligatoria",
                       corso, d(s.data_scadenza), _STATI_KO[s.stato_scadenza]], tone))
    qual_scadute = 0
    for q in qualifiche:
        p = anag.get(q.legacy_anagrafica_id)
        stato, tone = scadenza_stato(q.data_scadenza, params.today, preavviso=60)
        if tone == TONE_DANGER:
            qual_scadute += 1
        righe.append(((p.reparto if p else ""), (p.nominativo if p else ""),
                      [p.nominativo if p else "", p.reparto if p else "", "Qualifica",
                       getattr(q.tipo, "nome", ""), d(q.data_scadenza), stato], tone))
    for _rep, _nom, values, tone in sorted(righe, key=lambda r: (r[0].casefold(), r[1].casefold())):
        result.add_row(values, tone)

    result.kpis = [
        Kpi("Copertura formazione obbligatoria", pct(coperti, totale_req),
            TONE_OK if totale_req and coperti * 100 >= totale_req * 95 else TONE_WARN if totale_req else "",
            f"{coperti} su {totale_req} requisiti"),
        Kpi("Formazione scaduta", conteggi["SCADUTO"], TONE_DANGER if conteggi["SCADUTO"] else TONE_OK),
        Kpi("Mai frequentata", conteggi["MAI_FREQUENTATO"], TONE_DANGER if conteggi["MAI_FREQUENTATO"] else TONE_OK),
        Kpi("In scadenza 30 gg", conteggi["IN_SCADENZA_30"], TONE_WARN if conteggi["IN_SCADENZA_30"] else ""),
        Kpi("Qualifiche scadute", qual_scadute, TONE_DANGER if qual_scadute else TONE_OK),
    ]
    result.notes = [
        "Solo dipendenti in forza. Requisiti di formazione derivati da mansione, ruolo e regole (scadenzario formazione).",
        "Righe: requisiti scaduti, mai frequentati o in scadenza entro 30 giorni; qualifiche scadute o in scadenza entro 60.",
    ]
    result.links = links(("Scadenzario formazione", "anagrafica:formazione_scadenzario"),
                         ("Scadenzario qualifiche", "anagrafica:qualifiche_scadenzario"))
    return result


register(ReportDef(
    slug="competenze",
    title="Competenze: formazione obbligatoria e qualifiche",
    area=AREA_PERSONE,
    description="Copertura dei requisiti di formazione, corsi scaduti o mai fatti, qualifiche in scadenza.",
    clausole=(c(ISO_9001, "7.2"), c(EN_9100, "7.2"), c(ISO_45001, "7.2"), c(ISO_27001, "7.2")),
    builder=_competenze,
    usa_periodo=False,
    fonte="Anagrafica › Formazione e qualifiche",
))


# ---------------------------------------------------------------------------
# Processi speciali: abilitazioni del personale
# ---------------------------------------------------------------------------

def _processi_speciali(params: ReportParams) -> ReportResult:
    from anagrafica.models import AbilitazioneProcesso, CertificazioneIndividuale, ProcessoQualificato

    result = ReportResult()
    processi = list(
        ProcessoQualificato.objects.filter(stato="ATTIVO").select_related("cliente").order_by("nome")
    )
    abilitazioni = list(
        AbilitazioneProcesso.objects.filter(processo__in=processi, stato="ATTIVA").order_by("processo_id", "id")
    )
    cert_scad: dict[int, object] = {}
    for cert in CertificazioneIndividuale.objects.filter(
        abilitazione__in=abilitazioni, stato="ATTIVA", data_scadenza__isnull=False
    ).order_by("data_scadenza"):
        cert_scad.setdefault(cert.abilitazione_id, cert.data_scadenza)
    anag = persone([a.legacy_anagrafica_id for a in abilitazioni], today=params.today)

    per_processo: dict[int, list] = defaultdict(list)
    for a in abilitazioni:
        per_processo[a.processo_id].append(a)

    result.columns = ["Processo", "Regime", "Cliente", "Scadenza processo", "Persona", "Ruolo",
                      "Certificazione individuale", "Esito"]
    proc_scaduti = senza_personale = cert_ko = cessati = 0
    for proc in processi:
        stato_proc, tone_proc = (
            scadenza_stato(proc.data_scadenza, params.today, preavviso=60)
            if proc.tipo_validita != "ILLIMITATA" else ("Illimitata", TONE_OK)
        )
        if tone_proc == TONE_DANGER:
            proc_scaduti += 1
        persone_proc = per_processo.get(proc.id, [])
        if not persone_proc:
            senza_personale += 1
            result.add_row(
                [proc.nome, proc.get_regime_display(), str(proc.cliente or ""), d(proc.data_scadenza) or stato_proc,
                 "—", "", "", "Nessun operatore abilitato"],
                TONE_DANGER,
            )
            continue
        for a in persone_proc:
            p = anag.get(a.legacy_anagrafica_id) if a.legacy_anagrafica_id else None
            nome = p.nominativo if p else (a.nominativo_esterno or "")
            ruoli = [label for flag, label in ((a.is_qualificato, "Qualificato"), (a.is_addetto, "Addetto"),
                                               (a.is_controllore, "Controllore"), (a.is_part145, "Part 145")) if flag]
            scad_cert = cert_scad.get(a.id)
            esito, tone = "Abilitato", TONE_OK
            if p and p.cessato:
                esito, tone = "Cessato ma abilitazione attiva", TONE_DANGER
                cessati += 1
            elif scad_cert and scad_cert < params.today:
                esito, tone = "Certificazione scaduta", TONE_DANGER
                cert_ko += 1
            elif tone_proc == TONE_DANGER:
                esito, tone = "Processo scaduto", TONE_DANGER
            elif tone_proc == TONE_WARN:
                esito, tone = "Processo in scadenza", TONE_WARN
            result.add_row(
                [proc.nome, proc.get_regime_display(), str(proc.cliente or ""),
                 d(proc.data_scadenza) or stato_proc, nome, ", ".join(ruoli), d(scad_cert), esito],
                tone,
            )

    result.kpis = [
        Kpi("Processi attivi", len(processi)),
        Kpi("Processi scaduti", proc_scaduti, TONE_DANGER if proc_scaduti else TONE_OK),
        Kpi("Senza operatori abilitati", senza_personale, TONE_DANGER if senza_personale else TONE_OK),
        Kpi("Abilitazioni attive", len(abilitazioni)),
        Kpi("Certificazioni individuali scadute", cert_ko, TONE_DANGER if cert_ko else TONE_OK),
        Kpi("Cessati ancora abilitati", cessati, TONE_DANGER if cessati else TONE_OK),
    ]
    result.notes = [
        "Processi speciali (NADCAP, Part 145, specifici cliente) in stato attivo e relative abilitazioni attive (MOD.128).",
        "EN 9100 §8.5.1.2: la validazione dei processi speciali comprende la qualifica del personale.",
    ]
    result.links = links(("Cruscotto processi qualificati", "anagrafica:mpq_cruscotto"))
    return result


register(ReportDef(
    slug="processi-speciali",
    title="Processi speciali e personale abilitato",
    area=AREA_PERSONE,
    description="Processi qualificati attivi, operatori abilitati, certificazioni individuali scadute.",
    clausole=(c(EN_9100, "8.5.1.2"), c(ISO_9001, "8.5.1 f)"), c(ISO_9001, "7.2")),
    builder=_processi_speciali,
    usa_periodo=False,
    fonte="Anagrafica › Processi qualificati",
))


# ---------------------------------------------------------------------------
# Efficacia della formazione
# ---------------------------------------------------------------------------

def _efficacia_formazione(params: ReportParams) -> ReportResult:
    from django.apps import apps

    TrainingEfficacia = apps.get_model("anagrafica", "TrainingEfficacia")
    result = ReportResult()
    valutazioni = list(
        TrainingEfficacia.objects.filter(attesa_dal__range=(params.date_from, params.date_to))
        .select_related("record")
        .order_by("-attesa_dal", "-id")
    )
    anag = persone([v.legacy_anagrafica_id for v in valutazioni])
    esiti = defaultdict(int)
    in_attesa_lunga = 0
    result.columns = ["Dipendente", "Reparto", "Corso", "Completato il", "Attesa dal", "Valutata il", "Esito", "Azione"]
    for v in valutazioni:
        p = anag.get(v.legacy_anagrafica_id)
        record = v.record
        corso = getattr(record, "course_title_snapshot", "") or getattr(getattr(record, "corso", None), "titolo", "")
        if v.esito:
            esiti[v.esito] += 1
            tone = {"EFFICACE": TONE_OK, "PARZIALE": TONE_WARN, "NON_EFFICACE": TONE_DANGER}.get(v.esito, "")
            esito = v.get_esito_display()
        else:
            esiti["attesa"] += 1
            ritardo = (params.today - v.attesa_dal).days if v.attesa_dal else 0
            if ritardo > 90:
                in_attesa_lunga += 1
                tone = TONE_DANGER
            else:
                tone = TONE_WARN
            esito = "Da valutare"
        result.add_row(
            [p.nominativo if p else "", p.reparto if p else "", corso,
             d(getattr(record, "data_completamento", None)), d(v.attesa_dal), d(v.valutata_il), esito, short(v.azione, 90)],
            tone,
        )
    totale = len(valutazioni)
    valutate = totale - esiti["attesa"]
    result.kpis = [
        Kpi("Valutazioni attese nel periodo", totale),
        Kpi("Eseguite", valutate, TONE_OK if totale and valutate == totale else "", pct(valutate, totale)),
        Kpi("Efficaci", esiti["EFFICACE"], TONE_OK),
        Kpi("Parziali", esiti["PARZIALE"], TONE_WARN if esiti["PARZIALE"] else ""),
        Kpi("Non efficaci", esiti["NON_EFFICACE"], TONE_DANGER if esiti["NON_EFFICACE"] else ""),
        Kpi("In attesa da oltre 90 gg", in_attesa_lunga, TONE_DANGER if in_attesa_lunga else TONE_OK),
    ]
    result.notes = [
        "ISO 9001 §7.2 c) chiede di valutare l'efficacia delle azioni intraprese per acquisire competenza.",
        "Esito «non efficace» o «parziale»: l'azione conseguente è riportata nell'ultima colonna.",
    ]
    result.links = links(("Scadenzario formazione", "anagrafica:formazione_scadenzario"))
    return result


register(ReportDef(
    slug="efficacia-formazione",
    title="Efficacia della formazione",
    area=AREA_PERSONE,
    description="Valutazioni di efficacia attese, eseguite, esiti e azioni conseguenti.",
    clausole=(c(ISO_9001, "7.2"), c(EN_9100, "7.2"), c(ISO_45001, "7.2")),
    builder=_efficacia_formazione,
    fonte="Anagrafica › Formazione",
))
