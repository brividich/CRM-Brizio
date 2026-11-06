"""Fonti dello scadenzario generale dagli altri moduli (Fase 2).

Ogni fonte normalizza le scadenze del suo modulo in ``ScadenzaItem``. Permesso di
partenza (prima delle regole del pannello): la voce compare a chi può aprire la
pagina dove si gestisce, con la stessa decisione dell'ACL (``acl_allows_path``),
come le verifiche impianti. Alcune voci personali compaiono sempre al diretto
interessato (la sua CAR, la sua presa visione).

Fonti e tipi (chiavi del pannello «Gestione»):

- ``sgi`` Sistema di gestione: sorveglianza e scadenza delle certificazioni,
  audit interni ed esterni da svolgere, risposta all'ente, analisi e chiusura
  delle CAR, verifica di efficacia, qualifica degli auditor, azioni della SoA,
  scenari di rischio OT;
- ``qualifiche`` MOD.128 e skill matrix: scadenza e revisione dei processi
  qualificati, requisiti, certificazioni individuali, abilitazioni macchina;
- ``formazione``: documenti di enti e docenti, verifica NC a 6 mesi (MOD.040);
- ``soc``: azioni correttive degli incidenti, accettazioni del rischio;
- ``gdpr``: revisione periodica degli amministratori di sistema;
- ``procedure``: prese visione assegnate e campagne.
"""
from __future__ import annotations

import logging
from datetime import date

from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)

SOURCE_SGI = "sgi"
SOURCE_QUALIFICHE = "qualifiche"
SOURCE_FORMAZIONE = "formazione"
SOURCE_SOC = "soc"
SOURCE_GDPR = "gdpr"
SOURCE_PROCEDURE = "procedure"
SOURCE_FORNITORI = "fornitori"
SOURCE_OFI = "ofi"
SOURCE_ANOMALIE = "anomalie"
SOURCE_LAVORO = "lavoro"
SOURCE_SUGGESTION = "suggestion"
SOURCE_ATTREZZATURE = "attrezzature"
SOURCE_INGRESSI = "ingressi"
SOURCE_MANUTENZIONE = "manutenzione"

SOURCE_LABELS = {
    SOURCE_SGI: "Sistema di gestione",
    SOURCE_QUALIFICHE: "Qualifiche di processo",
    SOURCE_FORMAZIONE: "Formazione (enti e verifiche)",
    SOURCE_SOC: "SOC / NIS2",
    SOURCE_GDPR: "GDPR",
    SOURCE_PROCEDURE: "Presa visione procedure",
    SOURCE_FORNITORI: "Fornitori (documenti di sicurezza)",
    SOURCE_OFI: "Registro OFI",
    SOURCE_ANOMALIE: "Anomalie e NC",
    SOURCE_LAVORO: "KICK-OFF e attività",
    SOURCE_SUGGESTION: "Suggestion Corner",
    SOURCE_ATTREZZATURE: "Attrezzature",
    SOURCE_INGRESSI: "Ingressi e cambi mansione",
    SOURCE_MANUTENZIONE: "Manutenzione programmata",
}

TIPI = {
    SOURCE_SGI: {
        "sorveglianza": "Sorveglianza certificazione",
        "certificato": "Scadenza certificato",
        "audit_interno": "Audit interno da svolgere",
        "audit_esterno": "Audit esterno",
        "risposta_ente": "Risposta all'ente",
        "car_analisi": "Analisi CAR",
        "car_chiusura": "Chiusura CAR",
        "efficacia": "Verifica di efficacia",
        "auditor": "Qualifica auditor",
        "soa": "Azione SoA",
        "rischio_ot": "Scenario di rischio OT",
    },
    SOURCE_QUALIFICHE: {
        "processo": "Processo qualificato",
        "processo_revisione": "Revisione processo qualificato",
        "requisito": "Requisito di qualifica",
        "certificazione_individuale": "Certificazione individuale",
        "abilitazione_macchina": "Abilitazione macchina",
    },
    SOURCE_FORMAZIONE: {
        "documento_ente": "Documento ente / docente",
        "verifica_nc": "Verifica NC a 6 mesi",
    },
    SOURCE_SOC: {
        "azione_correttiva": "Azione correttiva incidente",
        "accettazione_rischio": "Accettazione del rischio",
        "termine_legale": "Termine NIS2 o GDPR",
    },
    SOURCE_GDPR: {"ads_revisione": "Revisione amministratore di sistema"},
    SOURCE_PROCEDURE: {"assegnazione": "Presa visione", "campagna": "Campagna di presa visione"},
    SOURCE_FORNITORI: {"documento": "Documento fornitore"},
    SOURCE_OFI: {"ofi": "Chiusura OFI"},
    SOURCE_ANOMALIE: {"azione_nc": "Azione su NC", "verifica_nc": "Verifica di efficacia NC"},
    SOURCE_LAVORO: {"attivita": "Attività", "azione_incontro": "Azione da incontro"},
    SOURCE_SUGGESTION: {"esecuzione": "Da eseguire", "controllo": "Da controllare"},
    SOURCE_ATTREZZATURE: {"task": "Attività su attrezzatura"},
    SOURCE_INGRESSI: {"onboarding": "Voce di inserimento", "cambio_mansione": "Adempimento cambio mansione", "deroga": "Deroga operativa"},
    SOURCE_MANUTENZIONE: {"ordinaria": "Manutenzione o taratura"},
}


def _url(nome: str, *args) -> str:
    try:
        return reverse(nome, args=args)
    except NoReverseMatch:
        return ""


def _apre(ctx, nome: str) -> bool:
    """Chi guarda può aprire la pagina ``nome`` (sempre vero nella raccolta di sistema)."""
    if ctx.sistema:
        return True
    cache = ctx.__dict__.setdefault("_pagine_aperte", {})
    if nome in cache:
        return cache[nome]
    from core.middleware import acl_allows_path

    percorso = _url(nome)
    esito = False
    if percorso:
        try:
            esito = bool(acl_allows_path(percorso, django_user=ctx.request.user, request=ctx.request))
        except Exception:
            logger.exception("scadenzario: permesso della pagina %s non valutabile", nome)
    cache[nome] = esito
    return esito


def _utente_id(ctx):
    return getattr(getattr(ctx.request, "user", None), "id", None)


def _item(ctx, source, kind, titolo, soggetto, scadenza: date, url, *, elemento="", elemento_label="", reparto="", extra=None):
    from dashboard.scadenze_providers import ScadenzaItem

    return ScadenzaItem(
        source=source, kind=kind, kind_label=TIPI[source][kind], titolo=titolo or "", soggetto=soggetto or "",
        reparto=reparto or "", data_scadenza=scadenza, giorni=(scadenza - ctx.oggi).days if scadenza else None,
        url=url, extra=extra or {}, elemento=elemento or "", elemento_label=elemento_label or elemento or "",
    )


def _nomi_anagrafica(ids) -> dict[int, tuple[str, str]]:
    """{legacy_anagrafica_id: (nome completo, reparto)}."""
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    from core.legacy_anagrafica import fetch_anagrafica_rows
    from core.naming import nome_completo

    esito = {}
    for r in fetch_anagrafica_rows(ids=ids, deduplicate=True):
        if r.get("id"):
            esito[int(r["id"])] = (nome_completo(r.get("nome") or "", r.get("cognome") or ""), str(r.get("reparto") or ""))
    return esito


def _nome_utente(u) -> str:
    return (u.get_full_name() or u.username) if u else ""


def _nome_auditor(au) -> str:
    if au is None:
        return ""
    return _nome_utente(au.user) if au.user_id else (au.nome_esterno or "")


def _sicuro(ctx, funzione) -> list:
    try:
        return funzione(ctx)
    except Exception:
        logger.exception("scadenzario: raccolta %s fallita", getattr(funzione, "__name__", funzione))
        return []


# ---------------------------------------------------------------------------
# Sistema di gestione
# ---------------------------------------------------------------------------

def _sgi_certificazioni(ctx) -> list:
    if not _apre(ctx, "sistema_gestione:esterni_elenco"):
        return []
    from django.db.models import Q

    from sistema_gestione.models import AuditEsterno, Certificazione

    items = []
    for c in Certificazione.objects.filter(attiva=True).filter(
        Q(prossima_sorveglianza__lte=ctx.orizzonte) | Q(scade_il__lte=ctx.orizzonte)
    ):
        norma = c.get_norma_display()
        url = _url("sistema_gestione:esterni_certificazione_scheda", c.pk)
        for kind, data in (("sorveglianza", c.prossima_sorveglianza), ("certificato", c.scade_il)):
            if data and data <= ctx.orizzonte:
                items.append(_item(ctx, SOURCE_SGI, kind, f"{norma} {c.descrizione}".strip(), c.ente, data, url,
                                   elemento=c.norma, elemento_label=norma))
    for a in AuditEsterno.objects.exclude(stato="CHIUSO"):
        url = _url("sistema_gestione:esterni_audit", a.pk)
        if a.stato == "PIANIFICATO" and a.data_inizio and a.data_inizio <= ctx.orizzonte:
            items.append(_item(ctx, SOURCE_SGI, "audit_esterno", f"{a.get_tipo_display()} {a.ente}".strip(), a.ente,
                               a.data_inizio, url, elemento=a.tipo, elemento_label=a.get_tipo_display()))
        if a.risposta_entro and not a.piano_inviato_il and a.risposta_entro <= ctx.orizzonte:
            items.append(_item(ctx, SOURCE_SGI, "risposta_ente", f"Risposta a {a.ente}".strip(), a.ente,
                               a.risposta_entro, url, elemento=a.tipo, elemento_label=a.get_tipo_display()))
    return items


def _sgi_audit(ctx) -> list:
    vede_tutto = _apre(ctx, "sistema_gestione:audit_calendario")
    from sistema_gestione.models import Audit, AuditVerificaEfficacia, AzioneCorrettivaAudit, Auditor

    items = []
    if vede_tutto:
        for a in Audit.objects.filter(stato__in=("PIANIFICATO", "PIANO_APPROVATO"), data_inizio__isnull=False,
                                      data_inizio__lte=ctx.orizzonte).select_related("lead_auditor__user"):
            items.append(_item(ctx, SOURCE_SGI, "audit_interno", f"Audit {a.numero}".strip(), _nome_auditor(a.lead_auditor),
                               a.data_inizio, _url("sistema_gestione:audit_dettaglio", a.pk),
                               elemento=a.modulo, elemento_label=a.get_modulo_display()))
        # Verifica di efficacia: l'ultima verifica di ogni rilievo con una data successiva.
        ultime = {}
        for v in AuditVerificaEfficacia.objects.select_related("esito").order_by("esito_id", "registrato_il", "pk"):
            ultime[v.esito_id] = v
        for v in ultime.values():
            if v.risultato != "EFFICACE" and v.prossima_verifica and v.prossima_verifica <= ctx.orizzonte:
                items.append(_item(ctx, SOURCE_SGI, "efficacia", f"Efficacia rilievo {v.esito.clausola or v.esito_id}",
                                   v.get_risultato_display(), v.prossima_verifica,
                                   _url("sistema_gestione:audit_dettaglio", v.esito.audit_id)))
        for au in Auditor.objects.filter(attivo=True, qualifica_scadenza__isnull=False,
                                         qualifica_scadenza__lte=ctx.orizzonte).select_related("user"):
            nome = _nome_auditor(au)
            items.append(_item(ctx, SOURCE_SGI, "auditor", f"Qualifica auditor {nome}", nome, au.qualifica_scadenza,
                               _url("sistema_gestione:auditor_modifica", au.pk), elemento=nome))
    car = AzioneCorrettivaAudit.objects.filter(chiusa_il__isnull=True).select_related("responsabile", "registro")
    if not vede_tutto:
        uid = _utente_id(ctx)
        if not uid:
            return items
        car = car.filter(responsabile_id=uid)  # la propria CAR la vede sempre
    for c in car:
        url = _url("sistema_gestione:procedura_car", c.registro_id)
        nome = _nome_utente(c.responsabile)
        titolo = f"CAR {getattr(c.registro, 'numero', '') or c.pk}".strip()
        if not c.analizzata_il and c.scadenza_analisi <= ctx.orizzonte:
            items.append(_item(ctx, SOURCE_SGI, "car_analisi", titolo, nome, c.scadenza_analisi, url))
        if c.scadenza_chiusura <= ctx.orizzonte:
            items.append(_item(ctx, SOURCE_SGI, "car_chiusura", titolo, nome, c.scadenza_chiusura, url,
                               extra={"prorogata": bool(c.proroga_al)}))
    return items


def _sgi_soa(ctx) -> list:
    if not _apre(ctx, "sistema_gestione:soa"):
        return []
    from sistema_gestione.models import ScenarioRischioOT, SoaVoce

    items = []
    for v in SoaVoce.objects.filter(revisione__stato="APPROVATA", scadenza__isnull=False,
                                    scadenza__lte=ctx.orizzonte).select_related("controllo"):
        if not v.ha_azione_aperta:
            continue
        controllo = str(v.controllo)
        items.append(_item(ctx, SOURCE_SGI, "soa", (v.azione or controllo)[:200], v.responsabile, v.scadenza,
                           _url("sistema_gestione:soa_voce", v.pk), elemento=controllo))
    for s in ScenarioRischioOT.objects.filter(revisione__stato="APPROVATA", scadenza__isnull=False,
                                              scadenza__lte=ctx.orizzonte).select_related("revisione"):
        if (s.stato or "").strip().lower() in ("chiuso", "chiusa", "completato", "completata", "fatto"):
            continue
        items.append(_item(ctx, SOURCE_SGI, "rischio_ot", f"{s.codice} {s.scenario}"[:200], s.responsabile, s.scadenza,
                           _url("sistema_gestione:soa_rischio_ot", s.revisione.numero, s.pk), elemento=s.codice))
    return items


def collect_sgi(ctx) -> list:
    return _sicuro(ctx, _sgi_certificazioni) + _sicuro(ctx, _sgi_audit) + _sicuro(ctx, _sgi_soa)


# ---------------------------------------------------------------------------
# Qualifiche di processo (MOD.128) e abilitazioni macchina
# ---------------------------------------------------------------------------

def _mod128(ctx) -> list:
    if not _apre(ctx, "anagrafica:mpq_cruscotto"):
        return []
    from anagrafica.models_mpq import CertificazioneIndividuale, ProcessoQualificato, RequisitoQualifica

    items = []
    for p in ProcessoQualificato.objects.filter(stato="ATTIVO"):
        url = _url("anagrafica:mpq_processo_detail", p.pk)
        scadenza = p.scadenza_effettiva
        if scadenza and scadenza <= ctx.orizzonte:
            items.append(_item(ctx, SOURCE_QUALIFICHE, "processo", p.nome, p.get_regime_display(), scadenza, url,
                               elemento=p.regime, elemento_label=p.get_regime_display()))
        if p.data_revisione and p.data_revisione <= ctx.orizzonte:
            items.append(_item(ctx, SOURCE_QUALIFICHE, "processo_revisione", p.nome, p.responsabile_qualita,
                               p.data_revisione, url, elemento=p.regime, elemento_label=p.get_regime_display()))
    for r in RequisitoQualifica.objects.filter(attivo=True, data_scadenza__isnull=False, data_scadenza__lte=ctx.orizzonte,
                                               processo__stato="ATTIVO").exclude(stato="NON_APPLICABILE").select_related("processo"):
        items.append(_item(ctx, SOURCE_QUALIFICHE, "requisito", r.descrizione or r.get_tipo_display(), r.processo.nome,
                           r.data_scadenza, _url("anagrafica:mpq_processo_detail", r.processo_id),
                           elemento=r.tipo, elemento_label=r.get_tipo_display()))
    for c in CertificazioneIndividuale.objects.filter(stato="ATTIVA", data_scadenza__isnull=False,
                                                      data_scadenza__lte=ctx.orizzonte):
        items.append(_item(ctx, SOURCE_QUALIFICHE, "certificazione_individuale", f"{c.schema} {c.livello}".strip(),
                           c.numero, c.data_scadenza, _url("anagrafica:mpq_cruscotto"), elemento=c.schema))
    return items


def _abilitazioni(ctx) -> list:
    if not _apre(ctx, "anagrafica:skm_scadenzario"):
        return []
    from anagrafica.models_skillmatrix import AbilitazioneMacchina

    righe = list(AbilitazioneMacchina.objects.filter(stato="attiva", prossima_revisione__isnull=False,
                                                     prossima_revisione__lte=ctx.orizzonte).select_related("asset"))
    nomi = _nomi_anagrafica({a.legacy_anagrafica_id for a in righe})
    url = _url("anagrafica:skm_scadenzario")
    items = []
    for a in righe:
        nome, reparto = nomi.get(a.legacy_anagrafica_id, ("", ""))
        macchina = a.asset.name if a.asset_id else ""
        items.append(_item(ctx, SOURCE_QUALIFICHE, "abilitazione_macchina", f"Abilitazione {macchina}".strip(), nome,
                           a.prossima_revisione, url, elemento=macchina, reparto=reparto))
    return items


def collect_qualifiche(ctx) -> list:
    return _sicuro(ctx, _mod128) + _sicuro(ctx, _abilitazioni)


# ---------------------------------------------------------------------------
# Formazione: documenti di enti e docenti, verifica NC a 6 mesi
# ---------------------------------------------------------------------------

def collect_formazione(ctx) -> list:
    if not _apre(ctx, "anagrafica:formazione_sessioni_list"):
        return []
    from anagrafica.models_formazione import TrainingProviderDocument, TrainingSession

    items = []
    for d in TrainingProviderDocument.objects.filter(data_scadenza__isnull=False, data_scadenza__lte=ctx.orizzonte
                                                     ).select_related("azienda", "docente"):
        if d.azienda_id:
            chi, url = d.azienda.nome, _url("anagrafica:formazione_azienda_detail", d.azienda_id)
        else:
            chi, url = d.docente.nome, _url("anagrafica:formazione_istruttore_detail", d.docente_id)
        items.append(_item(ctx, SOURCE_FORMAZIONE, "documento_ente", d.get_tipo_display(), chi, d.data_scadenza, url,
                           elemento=d.tipo, elemento_label=d.get_tipo_display()))
    for s in TrainingSession.objects.filter(approvata_il__isnull=False, verifica_nc_esito="").select_related("corso"):
        dovuta = s.verifica_nc_dovuta_dal
        if dovuta and dovuta <= ctx.orizzonte:
            items.append(_item(ctx, SOURCE_FORMAZIONE, "verifica_nc", f"Verifica NC {s.codice_sessione}", s.corso.titolo,
                               dovuta, _url("anagrafica:formazione_sessione_detail", s.pk), elemento=s.corso.titolo))
    return items


# ---------------------------------------------------------------------------
# SOC / NIS2
# ---------------------------------------------------------------------------

def collect_soc(ctx) -> list:
    from security.models import SecurityAccettazioneRischio, SecurityCorrectiveAction

    items = _sicuro(ctx, _termini_soc)
    if _apre(ctx, "security:incidents"):
        for a in SecurityCorrectiveAction.objects.filter(fatta_il__isnull=True, scadenza__isnull=False,
                                                         scadenza__lte=ctx.orizzonte).select_related("incident"):
            items.append(_item(ctx, SOURCE_SOC, "azione_correttiva", a.titolo, a.responsabile, a.scadenza,
                               _url("security:incident_detail", a.incident_id)))
    if _apre(ctx, "security:accettazioni_rischio"):
        for r in SecurityAccettazioneRischio.objects.filter(revocata_il__isnull=True, scadenza__isnull=False,
                                                            scadenza__lte=ctx.orizzonte).select_related("cve"):
            items.append(_item(ctx, SOURCE_SOC, "accettazione_rischio", f"Accettazione {r.cve}", r.host, r.scadenza,
                               _url("security:accettazioni_rischio"), elemento=r.host))
    return items


# ---------------------------------------------------------------------------
# GDPR: amministratori di sistema
# ---------------------------------------------------------------------------

def collect_gdpr(ctx) -> list:
    if not _apre(ctx, "security:registro_log_ads"):
        return []
    from registro_log.models import AmministratoreSistema

    url = _url("security:registro_log_ads")
    return [
        _item(ctx, SOURCE_GDPR, "ads_revisione", f"Verifica operato {a.nome}", a.societa or a.get_tipo_display(),
              a.prossima_revisione, url, elemento=a.nome)
        for a in AmministratoreSistema.objects.filter(revocato_il__isnull=True, prossima_revisione__isnull=False,
                                                      prossima_revisione__lte=ctx.orizzonte)
    ]


# ---------------------------------------------------------------------------
# Presa visione delle procedure
# ---------------------------------------------------------------------------

def collect_procedure(ctx) -> list:
    from procedure_refresh.models import ProcedureAssignment, ProcedureCampaign

    gestore = _apre(ctx, "procedure_refresh:campaign_list")
    items = []
    qs = ProcedureAssignment.objects.filter(
        status__in=("assigned", "opened", "overdue"), due_date__isnull=False, due_date__lte=ctx.orizzonte,
    ).select_related("campaign", "revision", "user")
    if not gestore:
        uid = _utente_id(ctx)
        if not uid:
            return []
        qs = qs.filter(user_id=uid)  # le proprie prese visione si vedono sempre
    uid = _utente_id(ctx)
    for a in qs:
        campagna = a.campaign.name if a.campaign_id else ""
        # La scheda dell'assegnazione si apre solo per la propria: al gestore la campagna.
        if a.campaign_id and a.user_id != uid:
            url = _url("procedure_refresh:campaign_detail", a.campaign_id)
        else:
            url = _url("procedure_refresh:assignment_detail", a.pk)
        items.append(_item(ctx, SOURCE_PROCEDURE, "assegnazione", str(a.revision) if a.revision_id else campagna,
                           _nome_utente(a.user), a.due_date, url, elemento=campagna))
    if gestore:
        for c in ProcedureCampaign.objects.filter(status="published", due_date__isnull=False, due_date__lte=ctx.orizzonte):
            items.append(_item(ctx, SOURCE_PROCEDURE, "campagna", c.name, "", c.due_date,
                               _url("procedure_refresh:campaign_detail", c.pk), elemento=c.name))
    return items


# ---------------------------------------------------------------------------
# Fornitori: documenti di sicurezza (DURC, visura, DUVRI, polizza…)
# ---------------------------------------------------------------------------

def collect_fornitori(ctx) -> list:
    """Per ogni fornitore attivo e per tipo di documento, quello con la scadenza più
    lontana: un documento rinnovato fa sparire il vecchio dallo scadenzario."""
    if not _apre(ctx, "fornitori:fornitori_list"):
        return []
    from anagrafica.models import FornitoreDocumento
    from fornitori.requisiti import documenti_con_scadenza

    items = []
    for d in documenti_con_scadenza(
        FornitoreDocumento.objects.filter(fornitore__is_active=True, data_scadenza__isnull=False)
        .select_related("fornitore")
    ):
        if d.data_scadenza <= ctx.orizzonte:
            items.append(_item(ctx, SOURCE_FORNITORI, "documento", d.get_tipo_display(), d.fornitore.ragione_sociale,
                               d.data_scadenza, _url("fornitori:fornitore_detail", d.fornitore_id),
                               elemento=d.tipo, elemento_label=d.get_tipo_display()))
    from fornitori.models import TecnicoFornitore

    for t in (TecnicoFornitore.objects.filter(fornitore__is_active=True, attivo=True, attestati_fino_al__isnull=False,
                                              attestati_fino_al__lte=ctx.orizzonte).select_related("fornitore")):
        items.append(_item(ctx, SOURCE_FORNITORI, "tecnico", "Attestati tecnico",
                           f"{t.fornitore.ragione_sociale} — {t.nome}", t.attestati_fino_al,
                           _url("fornitori:fornitore_detail", t.fornitore_id) + "#tab-tecnici",
                           elemento="TECNICO", elemento_label="Attestati dei tecnici"))
    return items


# ---------------------------------------------------------------------------
# Fonti operative: lavoro quotidiano dei moduli
# ---------------------------------------------------------------------------

def _legacy_id(ctx):
    from . import visibilita as vis

    try:
        return vis.identita_di(ctx.request).legacy_user_id
    except Exception:
        return None


def collect_ofi(ctx) -> list:
    """Voci aperte del registro MOD.174. Quelle con CAR entrano già dalla fonte Sistema di gestione."""
    from gestione_specifiche.models import RegistroOFI

    qs = (RegistroOFI.objects.filter(RegistroOFI.q_aperte(), data_richiesta__isnull=False, data_richiesta__lte=ctx.orizzonte,
                                     car_procedurale__isnull=True).select_related("responsabile"))
    if not _apre(ctx, "registro_ofi:home"):
        uid = _utente_id(ctx)
        if not uid:
            return []
        qs = qs.filter(responsabile_id=uid)
    return [_item(ctx, SOURCE_OFI, "ofi", f"OFI {v.numero} {v.processo or ''}".strip(),
                  _nome_utente(v.responsabile) or v.owner_processo or v.proprietario or "", v.data_richiesta,
                  _url("registro_ofi:dettaglio", v.pk), extra={"utente_id": v.responsabile_id}) for v in qs]


def collect_anomalie(ctx) -> list:
    from anomalie.quality_models import AnomaliaNC, AnomaliaNCAzione

    azioni = AnomaliaNCAzione.objects.filter(stato__in=("DA_FARE", "IN_CORSO"), scadenza__isnull=False,
                                             scadenza__lte=ctx.orizzonte).select_related("nc")
    tutte = _apre(ctx, "anomalie_nc_lista")
    if not tutte:
        legacy = _legacy_id(ctx)
        if not legacy:
            return []
        azioni = azioni.filter(responsabile_legacy_id=legacy)
    items = [_item(ctx, SOURCE_ANOMALIE, "azione_nc", (a.descrizione or "")[:200], a.responsabile_nome, a.scadenza,
                   _url("anomalie_nc_dettaglio", a.nc_id), elemento=a.get_tipo_display()) for a in azioni]
    if tutte:
        for nc in AnomaliaNC.objects.exclude(stato="CHIUSA").filter(verifica_prevista__isnull=False, verifica_data__isnull=True,
                                                                    verifica_prevista__lte=ctx.orizzonte):
            items.append(_item(ctx, SOURCE_ANOMALIE, "verifica_nc", f"Verifica di efficacia {nc}"[:200], "", nc.verifica_prevista,
                               _url("anomalie_nc_dettaglio", nc.pk)))
    return items


def collect_lavoro(ctx) -> list:
    """Solo le proprie: attività e azioni degli incontri assegnate a chi guarda."""
    from tasks.models import MeetingActionItem, Task

    uid = _utente_id(ctx)
    if not uid:
        return []
    items = []
    for t in Task.objects.filter(assigned_to_id=uid, due_date__isnull=False, due_date__lte=ctx.orizzonte).exclude(
            status__in=("DONE", "CANCELED")).select_related("project"):
        items.append(_item(ctx, SOURCE_LAVORO, "attivita", t.title, str(t.project) if t.project_id else "", t.due_date,
                           _url("tasks:detail", t.pk), extra={"utente_id": uid}))
    for a in MeetingActionItem.objects.filter(assigned_to_id=uid, status="OPEN", due_date__isnull=False,
                                              due_date__lte=ctx.orizzonte).select_related("project"):
        items.append(_item(ctx, SOURCE_LAVORO, "azione_incontro", a.title, str(a.project) if a.project_id else "", a.due_date,
                           _url("tasks:mie_azioni"), extra={"utente_id": uid}))
    return items


def collect_suggestion(ctx) -> list:
    from suggestion_corner.models import SuggestionCorner
    from suggestion_corner.permissions import visible_segnalazioni

    qs = SuggestionCorner.objects.all() if ctx.sistema else visible_segnalazioni(ctx.request.user)
    qs = qs.exclude(stato=SuggestionCorner.Stato.CHIUSA).select_related("incaricato", "controllore")
    S = SuggestionCorner.Stato
    prima_del_do = (S.INSERITA, S.DA_CLASSIFICARE, S.CLASSIFICATA, S.PLAN_DEFINITO, S.DO_IN_CORSO)
    prima_del_check = prima_del_do + (S.DO_COMPLETATO, S.CHECK_IN_CORSO)
    items = []
    for s in qs:
        url = _url("suggestion_corner:dettaglio", s.pk)
        if s.stato in prima_del_do and s.data_limite_esecuzione and s.data_limite_esecuzione <= ctx.orizzonte:
            items.append(_item(ctx, SOURCE_SUGGESTION, "esecuzione", str(s)[:200], _nome_utente(s.incaricato),
                               s.data_limite_esecuzione, url, extra={"utente_id": s.incaricato_id}))
        if s.stato in prima_del_check and s.data_limite_controllo and s.data_limite_controllo <= ctx.orizzonte:
            items.append(_item(ctx, SOURCE_SUGGESTION, "controllo", str(s)[:200], _nome_utente(s.controllore),
                               s.data_limite_controllo, url, extra={"utente_id": s.controllore_id}))
    return items


def collect_attrezzature(ctx) -> list:
    if not _apre(ctx, "attrezzature:task_list"):
        return []
    from attrezzature.models import AttrezzaturaTask

    return [_item(ctx, SOURCE_ATTREZZATURE, "task", t.titolo, str(t.attrezzatura) if t.attrezzatura_id else "", t.scadenza,
                  _url("attrezzature:task_detail", t.pk))
            for t in AttrezzaturaTask.objects.filter(stato__in=("aperta", "in_lavorazione", "bloccata"), scadenza__isnull=False,
                                                     scadenza__lte=ctx.orizzonte).select_related("attrezzatura")]


def collect_ingressi(ctx) -> list:
    from anagrafica.models import AdempimentoCambioMansione, OnboardingPratica, OnboardingTask
    from anagrafica.models_mansioni_rischio import DerogaOperativaVisita

    items = []
    if _apre(ctx, "anagrafica:onboarding_list"):
        for t in OnboardingTask.objects.filter(stato=OnboardingTask.STATO_DA_FARE, pratica__stato=OnboardingPratica.STATO_IN_CORSO,
                                               scadenza__isnull=False, scadenza__lte=ctx.orizzonte).select_related("pratica"):
            items.append(_item(ctx, SOURCE_INGRESSI, "onboarding", t.titolo, t.pratica.dipendente_nome, t.scadenza,
                               _url("anagrafica:onboarding_detail", t.pratica_id),
                               extra={"legacy_id": t.pratica.legacy_anagrafica_id}))
    if _apre(ctx, "anagrafica:scadenzario"):
        righe = list(AdempimentoCambioMansione.objects.filter(stato=AdempimentoCambioMansione.STATO_APERTO, entro_il__lte=ctx.orizzonte))
        nomi = _nomi_anagrafica(r.legacy_anagrafica_id for r in righe)
        for r in righe:
            nome, reparto = nomi.get(r.legacy_anagrafica_id, ("", ""))
            items.append(_item(ctx, SOURCE_INGRESSI, "cambio_mansione", r.descrizione, nome, r.entro_il,
                               _url("anagrafica:dipendente_detail", r.legacy_anagrafica_id), reparto=reparto,
                               extra={"legacy_id": r.legacy_anagrafica_id}))
    if _apre(ctx, "anagrafica:visite_mediche_dashboard"):
        righe = list(DerogaOperativaVisita.objects.filter(attivo=True, valida_fino__lte=ctx.orizzonte))
        nomi = _nomi_anagrafica(r.legacy_anagrafica_id for r in righe)
        for r in righe:
            nome, reparto = nomi.get(r.legacy_anagrafica_id, ("", ""))
            items.append(_item(ctx, SOURCE_INGRESSI, "deroga", "Deroga operativa in scadenza", nome, r.valida_fino,
                               _url("anagrafica:dipendente_detail", r.legacy_anagrafica_id) + "#scheda-visite", reparto=reparto,
                               extra={"legacy_id": r.legacy_anagrafica_id}))
    return items


def collect_manutenzione(ctx) -> list:
    """Manutenzioni ordinarie e tarature: tante, quindi spente finché il pannello non le accende."""
    from assets.services import deadline_feed as feed
    from core.acl import user_can_modulo_action

    from .models import VoceConfig

    if not VoceConfig.objects.filter(chiave=SOURCE_MANUTENZIONE, attiva=True).exists():
        return []
    request = ctx.request
    if not ctx.sistema:
        if not getattr(request.user, "is_superuser", False) and not user_can_modulo_action(request, "assets", "assets_deadlines"):
            return []
        if feed.KIND_ORDINARY not in feed.allowed_kinds(request):
            return []
    righe = feed.collect(start=None, end=ctx.orizzonte, filters=feed.FeedFilters(kinds=frozenset({feed.KIND_ORDINARY})), today=ctx.oggi)
    return [_item(ctx, SOURCE_MANUTENZIONE, "ordinaria", r.title, (r.asset_name or r.asset_tag or r.target_label or "").strip(), r.due_date,
                  r.detail_url, elemento=r.title or "", reparto=(r.reparto or "").strip(), extra={"asset_tag": r.asset_tag})
            for r in righe if r.due_date]


def _termini_soc(ctx) -> list:
    """Termini di legge NIS2 e GDPR degli incidenti: l'ora precisa resta nel titolo."""
    if not _apre(ctx, "security:incidents"):
        return []
    from django.db.models import Q
    from django.utils import timezone

    from security.models import SecurityIncident
    from security.services.incidents import deadlines

    items = []
    for inc in SecurityIncident.objects.filter(Q(is_significant=True) | Q(personal_data_breach=True)):
        for d in deadlines(inc):
            if d["state"] not in {"overdue", "due_soon", "pending"}:
                continue
            quando = timezone.localtime(d["due_at"])
            if quando.date() <= ctx.orizzonte:
                items.append(_item(ctx, SOURCE_SOC, "termine_legale", f"{d['label']} entro le {quando:%H:%M}", inc.code, quando.date(),
                                   _url("security:incident_detail", inc.pk), elemento=d["key"], elemento_label=d["label"]))
    return items


PROVIDERS = {
    SOURCE_SGI: collect_sgi,
    SOURCE_QUALIFICHE: collect_qualifiche,
    SOURCE_FORMAZIONE: collect_formazione,
    SOURCE_SOC: collect_soc,
    SOURCE_GDPR: collect_gdpr,
    SOURCE_PROCEDURE: collect_procedure,
    SOURCE_FORNITORI: collect_fornitori,
    SOURCE_OFI: lambda ctx: _sicuro(ctx, collect_ofi),
    SOURCE_ANOMALIE: lambda ctx: _sicuro(ctx, collect_anomalie),
    SOURCE_LAVORO: lambda ctx: _sicuro(ctx, collect_lavoro),
    SOURCE_SUGGESTION: lambda ctx: _sicuro(ctx, collect_suggestion),
    SOURCE_ATTREZZATURE: lambda ctx: _sicuro(ctx, collect_attrezzature),
    SOURCE_INGRESSI: lambda ctx: _sicuro(ctx, collect_ingressi),
    SOURCE_MANUTENZIONE: lambda ctx: _sicuro(ctx, collect_manutenzione),
}
