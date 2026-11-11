"""Proposte di chiusura automatiche: l'AI locale controlla gli alert aperti contro i report arrivati dopo e impara.

Come funziona:

1. **Giro automatico** (lettura ``ai_proposte``, ogni 15 minuti): per gli alert aperti da almeno
   «Attesa» ore il portale raccoglie le **prove** (``prove_alert``): se lo stesso evento si è ripetuto
   dopo l'apertura, cosa dicono gli altri report sullo stesso PC, utente, IP o job di backup arrivati
   dopo l'alert, l'ultima esecuzione del job. Le prove le calcola il codice, numerate P1, P2, …
2. **Decisioni passate** (``decisioni_passate``): come ha chiuso o riaperto chi gestisce il SOC gli
   alert dello stesso tipo (prima quelli sullo stesso soggetto) e le proposte scartate con la nota.
   Entrano nella domanda: l'AI deve seguirle. È così che «impara».
3. L'AI risponde in JSON: esito, confidenza, motivo e i codici delle prove usate. Prove inventate
   (codici che non esistono) vengono tolte; un esito di chiusura senza nessuna prova diventa «aperto».
4. **Fiducia** (``fiducia``): per ogni tipo di alert (sorgente + tipo di evento) e ogni esito si contano
   le ultime decisioni delle persone sulle proposte. Se le ultime «Conferme per chiudere da sola» sono
   tutte conferme, le proposte successive con quell'esito **chiudono l'alert da sole** (attore
   ``system:ai``), con il motivo e le prove in timeline. Mai per alert critici, minacce/malware, CVE
   sfruttate (KEV) o tipi esclusi (stessi limiti della soppressione appresa), mai sotto la confidenza
   minima, mai senza prove.
5. Ogni decisione insegna: confermare (o chiudere l'alert con lo stesso esito) aggiunge fiducia;
   chiudere con un altro esito, scartare la proposta o **riaprire** un alert chiuso dall'AI la azzera
   per quel tipo e quell'esito. Le chiusure delle regole automatiche rendono la proposta «superata».
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from security.models import (
    BackupJobRecord,
    SecurityAlert,
    SecurityAlertActionLog,
    SecurityAlertProposta,
    SecurityEventRecord,
    Severity,
)
from security.services import soc_settings
from security.services.alert_lifecycle import CLOSE_OUTCOMES, DA_DECIDERE_ALERT_STATUSES

logger = logging.getLogger(__name__)

ACTOR = "system:ai"
ACTION = "alert_proposta"
BUDGET_PIANIFICATO = 60   # secondi: il worker django-q ha 120 s, una risposta in produzione 15-40 s
BUDGET_MANUALE = 300      # «Esegui ora» gira in coda (600 s)
GIORNI_ALERT = 60         # alert più vecchi restano alle persone
GIORNI_DECISIONI = 180
MAX_PROVE = 10
APERTI = tuple(DA_DECIDERE_ALERT_STATUSES)  # «da decidere»: senza rimandati e silenziati
POSITIVI = (SecurityAlertProposta.CONFERMATA,)
NEGATIVI = (SecurityAlertProposta.CORRETTA, SecurityAlertProposta.SCARTATA, SecurityAlertProposta.ANNULLATA)
DA_AI = {"risolto": "resolved", "non_rilevante": "not_relevant", "rischio_accettato": "accepted_risk",
         "falso_positivo": "false_positive", "aperto": "aperto"}
SOGLIE_GIORNI = (1, 3, 7, 14, 30)

SISTEMA = (
    "Sei l'analista della sicurezza IT di una piccola azienda manifatturiera italiana. Ricevi un alert ancora aperto, "
    "le PROVE raccolte dal portale dai report arrivati dopo l'alert (numerate P1, P2, …) e le DECISIONI PASSATE del "
    "responsabile su alert dello stesso tipo. Decidi se l'alert si può chiudere.\n"
    'Rispondi solo con un oggetto JSON: {"esito": "risolto|non_rilevante|rischio_accettato|falso_positivo|aperto", '
    '"confidenza": 0-100, "motivo": "una frase in italiano per il registro di chiusura", "prove": ["P1"]}\n'
    "Regole:\n"
    "- «risolto» solo se una prova dice che il problema è rientrato dopo l'alert (un backup riuscito dopo il fallimento, "
    "l'evento che non si ripete più da giorni, la versione corretta installata).\n"
    "- «falso_positivo», «non_rilevante» o «rischio_accettato» solo se i fatti o le decisioni passate su casi uguali lo dicono.\n"
    "- Segui le decisioni passate del responsabile: se ha chiuso casi uguali con un esito e un motivo, proponi lo stesso; "
    "se ha scartato una proposta o riaperto un alert, non ripetere quell'errore.\n"
    "- Se le prove non bastano, «aperto». Nel dubbio, «aperto».\n"
    "- In \"prove\" metti solo i codici delle prove che usi davvero. Non inventare dati, nomi o date."
)
ESEMPI = (
    ("ALERT\nTitolo: Backup fallito: job SRV-DEMO-01\nSeverità: warning\nTipo di evento: backup_job\n\n"
     "PROVE\nP1: Job «SRV-DEMO-01»: esecuzione del 02/11/2099 01:00 con esito «completed» (dopo l'alert)\n"
     "P2: Lo stesso evento non si è più ripetuto dopo l'apertura (31/10/2099)\n\nDECISIONI PASSATE\n"
     "- 12/10/2099 · «Backup fallito: job SRV-DEMO-01» · chiuso come Risolto da operatore.demo: backup della notte dopo riuscito",
     {"esito": "risolto", "confidenza": 90, "motivo": "Il backup del 02/11 è riuscito e il fallimento non si è più ripetuto.",
      "prove": ["P1", "P2"]}),
    ("ALERT\nTitolo: Accesso VPN negato: utente demo.user\nSeverità: warning\nTipo di evento: vpn_auth_denied\n\n"
     "PROVE\nP1: Lo stesso evento si è ripetuto 14 volte dopo l'apertura; l'ultima il 03/11/2099 22:10\n\nDECISIONI PASSATE\n"
     "(nessuna)",
     {"esito": "aperto", "confidenza": 70, "motivo": "I tentativi negati continuano: serve una verifica dell'utente.", "prove": ["P1"]}),
)


# --- Impostazioni ------------------------------------------------------------------------------------

def attivo():
    return soc_settings.value("ai.proposte.attivo")


def chiusura_auto_attiva():
    return soc_settings.value("ai.proposte.chiusura_auto")


def soglia():
    return soc_settings.value("ai.proposte.soglia")


def confidenza_minima():
    return soc_settings.value("ai.proposte.confidenza_auto")


def is_persona(actor):
    """True per le decisioni di una persona (non del sistema, delle regole automatiche o dell'AI)."""
    from security.services.learned_suppression import is_system_actor

    return not is_system_actor(actor)


# --- Cosa si impara: il tipo di alert ----------------------------------------------------------------

def schema_di(alert):
    """(chiave, etichetta) del tipo di alert: sorgente + tipo di evento (o tipo del problema se manca l'evento)."""
    from security.services.investigation import alert_kind
    from security.templatetags.security_i18n import metric_label

    tipo = alert.event.event_type if alert.event_id and alert.event else f"tipo:{alert_kind(alert)}"
    etichetta = metric_label(alert.event.event_type) if alert.event_id and alert.event else alert_kind(alert)
    return f"{alert.source_id}|{tipo}"[:200], f"{getattr(alert.source, 'name', '')} · {etichetta}"[:255]


def _impronta(alert):
    from security.services.learned_suppression import alert_fingerprint

    fp = alert_fingerprint(alert)
    return fp.hash if fp else ""


# --- Prove dai report --------------------------------------------------------------------------------

def _quando(dt):
    return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M") if dt else "—"


def _soglia_giorni(giorni):
    """Fascia «da almeno N giorni»: cambia poche volte, così la proposta si rifà solo quando conta."""
    raggiunte = [s for s in SOGLIE_GIORNI if giorni >= s]
    return raggiunte[-1] if raggiunte else 0


def _soggetti(alert):
    from security.services.investigation import entities

    found = entities(alert)
    return {k: v.casefold() for k, v in found.items() if v and k in ("ip", "user", "computer", "job")}


def _esito_evento(payload):
    for key in ("status", "result", "outcome", "action", "state"):
        value = payload.get(key)
        if value not in (None, "", [], {}) and not isinstance(value, (dict, list)):
            return str(value)[:60]
    return ""


def prove_alert(alert, *, now=None):
    """Le prove, calcolate dal portale: elenco di frasi (senza codici P, li aggiunge ``contesto``)."""
    now = now or timezone.now()
    prove = []
    aperto_il = alert.created_at or now
    if alert.dedup_hash:
        stessi = SecurityEventRecord.objects.filter(dedup_hash=alert.dedup_hash)
        dopo = stessi.filter(occurred_at__gt=aperto_il)
        n_dopo = dopo.count()
        ultima = stessi.order_by("-occurred_at").values_list("occurred_at", flat=True).first()
        if n_dopo:
            prove.append(f"Lo stesso evento si è ripetuto {n_dopo} volte dopo l'apertura; l'ultima il {_quando(ultima)}")
        else:
            giorni = _soglia_giorni((now - max(ultima or aperto_il, aperto_il)).days)
            prove.append(f"Lo stesso evento non si è più ripetuto dopo l'apertura ({_quando(aperto_il)})"
                         + (f": nessuna nuova occorrenza da almeno {giorni} giorni" if giorni else ""))
    soggetti = _soggetti(alert)
    if soggetti.get("job"):
        run = (BackupJobRecord.objects.filter(job_name__iexact=soggetti["job"])
               .filter(Q(started_at__gt=aperto_il) | Q(started_at__isnull=True, created_at__gt=aperto_il))
               .order_by("-started_at", "-created_at").first())
        if run:
            prove.append(f"Job «{run.job_name}»: esecuzione del {_quando(run.started_at or run.created_at)} con esito «{run.status}» (dopo l'alert)")
        else:
            prove.append(f"Job «{soggetti['job']}»: nessuna esecuzione registrata dopo l'alert")
    gruppo = getattr(alert, "_gruppo_alert", None) or []
    if len(gruppo) > 1:
        prove.append(f"Alert uguali ancora aperti sullo stesso soggetto: {len(gruppo)}, il primo del {_quando(gruppo[-1].created_at)}")
    prove.extend(_eventi_collegati(alert, soggetti, aperto_il))
    return prove[:MAX_PROVE]


def _eventi_collegati(alert, soggetti, aperto_il, limite=6):
    """Eventi di altri report arrivati dopo l'alert sullo stesso PC (asset) o con lo stesso utente/IP/PC nei dati."""
    base = SecurityEventRecord.objects.filter(occurred_at__gt=aperto_il).select_related("source")
    if alert.dedup_hash:
        base = base.exclude(dedup_hash=alert.dedup_hash)
    trovati = {}
    if alert.event_id and alert.event and alert.event.asset_id:
        for ev in base.filter(asset_id=alert.event.asset_id).order_by("-occurred_at")[:limite]:
            trovati[ev.pk] = ev
    valori = {v for k, v in soggetti.items() if k in ("ip", "user", "computer")}
    if valori and len(trovati) < limite:
        for ev in base.order_by("-occurred_at")[:400]:
            if ev.pk in trovati:
                continue
            payload = ev.payload or {}
            testo = {str(v).casefold() for v in payload.values() if isinstance(v, (str, int)) and v not in ("", None)}
            if testo & valori:
                trovati[ev.pk] = ev
                if len(trovati) >= limite:
                    break
    from security.templatetags.security_i18n import metric_label

    righe = []
    for ev in sorted(trovati.values(), key=lambda e: e.occurred_at, reverse=True)[:limite]:
        esito = _esito_evento(ev.payload or {})
        righe.append(f"Dopo l'alert, report «{getattr(ev.source, 'name', '')}» del {_quando(ev.occurred_at)}: "
                     f"{metric_label(ev.event_type)} (gravità {ev.severity})" + (f", esito «{esito}»" if esito else ""))
    return righe


# --- Decisioni passate -------------------------------------------------------------------------------

_ESITO_AZIONE = {"false_positive": "false_positive"}


def _esito_log(log):
    if log.action == "close":
        return (log.details or {}).get("outcome") or "resolved"
    return _ESITO_AZIONE.get(log.action, "")


def decisioni_passate(alert, *, limite=8):
    """Come hanno deciso le persone sugli alert dello stesso tipo (prima lo stesso soggetto) e le proposte scartate."""
    schema, _label = schema_di(alert)
    impronta = _impronta(alert)
    since = timezone.now() - timedelta(days=GIORNI_DECISIONI)
    stesso_tipo = SecurityAlert.objects.filter(source_id=alert.source_id).exclude(pk=alert.pk)
    if alert.event_id and alert.event:
        stesso_tipo = stesso_tipo.filter(event__event_type=alert.event.event_type)
    logs = (SecurityAlertActionLog.objects.filter(alert__in=stesso_tipo, action__in=("close", "false_positive", "reopen"),
                                                  created_at__gte=since)
            .select_related("alert", "alert__event").order_by("-created_at")[:80])
    stessa_impronta, altre = [], []
    for log in logs:
        if not is_persona(log.actor):
            continue
        reason = str((log.details or {}).get("reason") or "").strip()[:200]
        if log.action == "reopen":
            riga = f"{_quando(log.created_at)} · «{log.alert.title[:90]}» · riaperto da {log.actor}" + (f": {reason}" if reason else "")
        else:
            esito = CLOSE_OUTCOMES.get(_esito_log(log)) or "Falso positivo"
            riga = f"{_quando(log.created_at)} · «{log.alert.title[:90]}» · chiuso come {esito} da {log.actor}" + (f": {reason}" if reason else "")
        same = bool(impronta) and _impronta(log.alert) == impronta
        (stessa_impronta if same else altre).append(("[stesso soggetto] " if same else "") + riga)
    errori = (SecurityAlertProposta.objects.filter(schema=schema, stato__in=NEGATIVI, decisa_il__gte=since)
              .exclude(alert=alert).select_related("alert").order_by("-decisa_il")[:4])
    righe_errori = []
    for p in errori:
        cosa = {SecurityAlertProposta.SCARTATA: "proposta scartata", SecurityAlertProposta.CORRETTA: f"chiuso invece come {p.esito_deciso_label}",
                SecurityAlertProposta.ANNULLATA: "chiusura automatica annullata: alert riaperto"}[p.stato]
        righe_errori.append(f"L'AI aveva proposto «{p.esito_label}» per «{p.alert.title[:90]}»: {cosa}" + (f" ({p.nota[:200]})" if p.nota else ""))
    return (stessa_impronta + altre)[:limite] + righe_errori


# --- Domanda all'AI ----------------------------------------------------------------------------------

def contesto(alert):
    """(testo per l'AI, prove numerate, hash). L'hash cambia solo se cambiano prove, decisioni o stato."""
    from security.services.ai_explain import alert_context

    prove = prove_alert(alert)
    decisioni = decisioni_passate(alert)
    numerate = [f"P{i}: {testo}" for i, testo in enumerate(prove, 1)]
    testo = (f"Oggi è il {timezone.localtime():%d/%m/%Y}.\n\nALERT\n{alert_context(alert)}\n\nPROVE\n"
             + ("\n".join(numerate) or "(nessuna prova dai report successivi)")
             + "\n\nDECISIONI PASSATE\n" + ("\n".join(f"- {d}" for d in decisioni) or "(nessuna)"))
    impronta = hashlib.sha256(json.dumps([alert.pk, alert.status, numerate, decisioni], ensure_ascii=False).encode()).hexdigest()
    return testo, numerate, impronta


def _valida(data, numerate):
    """Risposta dell'AI → proposta pulita, o None se non è utilizzabile."""
    if not isinstance(data, dict):
        return None
    esito = DA_AI.get(str(data.get("esito") or "").strip().lower().replace(" ", "_"))
    if not esito:
        return None
    try:
        confidenza = max(0, min(100, int(data.get("confidenza") or 0)))
    except (TypeError, ValueError):
        confidenza = 0
    codici = {riga.split(":", 1)[0]: riga for riga in numerate}
    citate = []
    for codice in data.get("prove") or []:
        codice = str(codice).strip().upper()
        if codice in codici and codici[codice] not in citate:
            citate.append(codici[codice])
    motivo = " ".join(str(data.get("motivo") or "").split())[:500]
    if esito != "aperto" and not citate:
        # Chiudere senza nessuna prova vera: non si propone.
        esito, motivo = "aperto", (motivo + " (nessuna prova citata: resta aperto)").strip()
    return {"esito": esito, "confidenza": confidenza, "motivo": motivo, "prove": citate}


def proponi(alert, ctx=None):
    """(proposta dict | None, errore). Non salva. ``ctx`` = ``contesto(alert)`` già calcolato."""
    from security.services.cpe_ai import _chiedi, _messaggi

    testo, numerate, impronta = ctx or contesto(alert)
    risposta = _chiedi(_messaggi(SISTEMA, ESEMPI, testo), action=ACTION, object_type="SecurityAlert", object_id=alert.pk)
    if not risposta["ok"]:
        return None, risposta["error"]
    proposta = _valida(risposta["data"], numerate)
    if proposta is None:
        return None, "Risposta dell'AI non valida"
    proposta.update({"contesto_hash": impronta, "modello": risposta["model"], "ms": risposta["ms"]})
    return proposta, ""


# --- Fiducia e chiusura automatica -------------------------------------------------------------------

def fiducia(schema, esito):
    """Quante delle ultime decisioni delle persone su proposte di questo tipo ed esito sono conferme di fila."""
    n = soglia()
    decise = (SecurityAlertProposta.objects.filter(schema=schema, esito=esito, stato__in=POSITIVI + NEGATIVI)
              .order_by("-decisa_il").values_list("stato", flat=True)[:max(n, 1) * 3])
    di_fila = 0
    for stato in decise:
        if stato in NEGATIVI:
            break
        di_fila += 1
    errori = sum(1 for s in decise if s in NEGATIVI)
    return {"conferme": di_fila, "soglia": n, "errori": errori, "affidabile": esito != "aperto" and di_fila >= n}


def blocco_auto(alert, proposta):
    """Perché questa proposta NON può chiudere da sola ('' = può)."""
    from security.services.learned_suppression import effective_severity, guardrail_reason

    if not chiusura_auto_attiva():
        return "chiusura automatica spenta"
    if proposta["esito"] == "aperto":
        return "l'AI propone di lasciarlo aperto"
    if proposta["confidenza"] < confidenza_minima():
        return f"confidenza {proposta['confidenza']}% sotto il {confidenza_minima()}%"
    if not proposta["prove"]:
        return "nessuna prova citata"
    severita = effective_severity(alert.event, alert) if alert.event_id and alert.event else alert.severity
    if severita == Severity.CRITICAL:
        return "alert critico"
    if alert.event_id and alert.event:
        motivo = guardrail_reason(alert.event, severity=severita)
        if motivo:
            return motivo
    stato = fiducia(proposta["schema"], proposta["esito"])
    if not stato["affidabile"]:
        return f"sta imparando: {stato['conferme']} conferme di fila su {stato['soglia']}"
    return ""


def _chiudi(alert, esito, actor, reason, user=None):
    from security.services.alert_lifecycle import close_alert, mark_false_positive

    if esito == "false_positive":
        return mark_false_positive(alert, actor=actor, reason=reason, user=user)
    return close_alert(alert, actor=actor, reason=reason, outcome=esito, user=user)


def chiudi_da_sola(proposta_obj, alert):
    """Chiude l'alert per conto dell'AI: motivo e prove in timeline, casi collegati aggiornati."""
    from security.services.auto_resolution import _cases_of, maybe_resolve_case

    stato = fiducia(proposta_obj.schema, proposta_obj.esito)
    proposta_obj.stato = SecurityAlertProposta.CHIUSA_AUTO
    proposta_obj.decisa_da = ACTOR
    proposta_obj.decisa_il = timezone.now()
    proposta_obj.save(update_fields=["stato", "decisa_da", "decisa_il"])
    prove = "; ".join(p.split(": ", 1)[-1] for p in proposta_obj.prove)[:600]
    reason = (f"Chiuso dall'AI (appreso da {stato['conferme']} conferme di fila): {proposta_obj.motivo}"
              + (f" Prove: {prove}" if prove else ""))[:2000]
    _chiudi(alert, proposta_obj.esito, ACTOR, reason)
    for case in _cases_of(alert):
        maybe_resolve_case(case)
    _chiudi_resto_del_gruppo(proposta_obj, alert, reason)


def _chiudi_resto_del_gruppo(proposta_obj, alert, reason):
    """Gli alert uguali più vecchi seguono la decisione: ciascuno passa dagli stessi limiti (mai critici, minacce, KEV)."""
    from security.services.auto_resolution import _cases_of, maybe_resolve_case
    from security.services.learned_suppression import effective_severity, guardrail_reason

    for altro in getattr(alert, "_gruppo_alert", None) or []:
        if altro.pk == alert.pk or altro.status not in APERTI:
            continue
        if altro.event_id and altro.event:
            severita = effective_severity(altro.event, altro)
            if severita == Severity.CRITICAL or guardrail_reason(altro.event, severity=severita):
                continue
        elif altro.severity == Severity.CRITICAL:
            continue
        _chiudi(altro, proposta_obj.esito, ACTOR, f"Stesso gruppo dell'alert #{alert.pk}. {reason}"[:2000])
        for case in _cases_of(altro):
            maybe_resolve_case(case)


# --- Giro automatico ---------------------------------------------------------------------------------

def alert_da_esaminare(limit):
    """Un alert per gruppo (il più recente), dai gruppi più grandi: una risposta dell'AI vale per tutto il gruppo."""
    from security.services.alert_gruppi import rappresentanti

    attesa = timezone.now() - timedelta(hours=soc_settings.value("ai.proposte.attesa_ore"))
    since = timezone.now() - timedelta(days=GIORNI_ALERT)
    return rappresentanti(created_at__lte=attesa, created_at__gte=since)[:limit]


def _salva(alert, proposta, schema, label, impronta):
    """Una proposta aperta per alert: si aggiorna; quelle decise restano come storia."""
    esistente = SecurityAlertProposta.objects.filter(alert=alert, stato=SecurityAlertProposta.APERTA).first()
    campi = {"schema": schema, "schema_label": label, "impronta": impronta, "esito": proposta["esito"], "motivo": proposta["motivo"],
             "prove": proposta["prove"], "confidenza": proposta["confidenza"], "contesto_hash": proposta["contesto_hash"],
             "modello": proposta["modello"][:160], "creata_il": timezone.now()}
    if esistente:
        for k, v in campi.items():
            setattr(esistente, k, v)
        esistente.save()
        return esistente
    return SecurityAlertProposta.objects.create(alert=alert, **campi)


def _salva_non_valida(alert, schema, label, impronta, contesto_hash, errore):
    """Risposta dell'AI non utilizzabile: si ricorda col contesto, così l'alert non si richiede a ogni giro.

    Stato «non_valida» (non è una decisione di una persona: non entra nella fiducia né nelle decisioni passate);
    una sola riga per alert, aggiornata a ogni nuovo scarto.
    """
    campi = {"schema": schema, "schema_label": label, "impronta": impronta, "esito": "aperto", "motivo": str(errore or "")[:500],
             "prove": [], "confidenza": 0, "contesto_hash": contesto_hash, "modello": "", "creata_il": timezone.now()}
    esistente = SecurityAlertProposta.objects.filter(alert=alert, stato=SecurityAlertProposta.NON_VALIDA).first()
    if esistente:
        for k, v in campi.items():
            setattr(esistente, k, v)
        esistente.save()
        return esistente
    return SecurityAlertProposta.objects.create(alert=alert, stato=SecurityAlertProposta.NON_VALIDA, **campi)


def aggiorna_superate():
    """Proposte aperte di alert non più aperti (chiusi da regole, posticipati, silenziati): superate."""
    return (SecurityAlertProposta.objects.filter(stato=SecurityAlertProposta.APERTA).exclude(alert__status__in=APERTI)
            .update(stato=SecurityAlertProposta.SUPERATA, decisa_il=timezone.now()))


def giro(*, limit, time_budget_seconds=BUDGET_PIANIFICATO):
    """Nessuna nuova richiesta dopo ``time_budget_seconds``; ogni richiesta ha come timeout il minimo fra
    quello configurato e il tempo che resta al tetto del giro (``cpe_ai._tetto``: 100 s pianificato)."""
    from ai_assistant.http_client import scadenza
    from security.services.cpe_ai import _tetto

    with scadenza(_tetto(time_budget_seconds)):
        return _giro(limit=limit, time_budget_seconds=time_budget_seconds)


def _giro(*, limit, time_budget_seconds):
    from security.services.cpe_ai import _ai_ferma, disponibile

    started = time.monotonic()
    superate = aggiorna_superate()
    ok, motivo = disponibile()
    if not ok:
        return {"ok": False, "errore": motivo, "superate": superate}
    esito = {"superate": superate, "esaminati": 0, "proposte": 0, "chiusi_da_soli": 0, "scartate": 0}
    tempi, fermo = [], ""
    ultimi = {}
    for p in SecurityAlertProposta.objects.filter(alert__status__in=APERTI).order_by("creata_il"):
        ultimi[p.alert_id] = p  # la più recente per alert
    for alert in alert_da_esaminare(limit * 20):
        if esito["esaminati"] >= limit or fermo or time.monotonic() - started > time_budget_seconds:
            break
        schema, label = schema_di(alert)
        ctx = contesto(alert)
        contesto_hash = ctx[2]
        precedente = ultimi.get(alert.pk)
        if precedente is not None and precedente.contesto_hash == contesto_hash:
            continue  # niente di nuovo dall'ultima proposta (anche se scartata o non valida)
        esito["esaminati"] += 1
        proposta, errore = proponi(alert, ctx)
        if proposta is None:
            esito["scartate"] += 1
            if _ai_ferma(errore):
                fermo = errore
            else:
                # Risposta non utilizzabile: si ricorda, e l'alert torna all'AI solo quando il contesto cambia.
                ultimi[alert.pk] = _salva_non_valida(alert, schema, label, _impronta(alert), contesto_hash, errore)
            continue
        tempi.append(proposta["ms"])
        proposta["schema"] = schema
        riga = _salva(alert, proposta, schema, label, _impronta(alert))
        # Una proposta aperta per gruppo: quelle su alert più vecchi dello stesso gruppo sono superate.
        (SecurityAlertProposta.objects.filter(stato=SecurityAlertProposta.APERTA, alert__in=getattr(alert, "_gruppo_alert", []))
         .exclude(pk=riga.pk).update(stato=SecurityAlertProposta.SUPERATA, decisa_il=timezone.now()))
        esito["proposte"] += 1
        if not blocco_auto(alert, proposta):
            try:
                chiudi_da_sola(riga, alert)
                esito["chiusi_da_soli"] += 1
            except Exception:  # noqa: BLE001 - una chiusura fallita lascia la proposta da confermare
                logger.exception("Chiusura automatica dell'alert %s non riuscita", alert.pk)
                riga.stato = SecurityAlertProposta.APERTA
                riga.save(update_fields=["stato"])
    if tempi:
        esito["ms_medi"] = int(sum(tempi) / len(tempi))
    if fermo:
        esito["errore"] = f"AI locale non ha risposto: {fermo}"
    return esito


def giro_lettura():
    if not attivo():
        return {"skipped": "proposte di chiusura dell'AI spente"}
    return giro(limit=soc_settings.value("ai.proposte.max_per_giro"), time_budget_seconds=BUDGET_PIANIFICATO)


def giro_manuale():
    return giro(limit=soc_settings.value("ai.proposte.max_per_giro") * 3, time_budget_seconds=BUDGET_MANUALE)


# --- Decisioni delle persone (da alert_lifecycle e dalla pagina) -------------------------------------

def registra_decisione(alert, action, actor, details):
    """Chiamata a ogni cambio di stato dell'alert: aggiorna le proposte e quindi la fiducia."""
    if actor == ACTOR:
        return
    persona = is_persona(actor)
    adesso = timezone.now()
    if action in ("close", "false_positive"):
        esito = (details.get("outcome") or "resolved") if action == "close" else "false_positive"
        aperta = SecurityAlertProposta.objects.filter(alert=alert, stato=SecurityAlertProposta.APERTA).first()
        if aperta is None:
            return
        if not persona:
            aperta.stato = SecurityAlertProposta.SUPERATA
        else:
            aperta.stato = SecurityAlertProposta.CONFERMATA if esito == aperta.esito else SecurityAlertProposta.CORRETTA
            aperta.esito_deciso = esito
            if aperta.stato == SecurityAlertProposta.CORRETTA:
                aperta.nota = str(details.get("reason") or "")[:2000]
        aperta.decisa_da = str(actor)[:120]
        aperta.decisa_il = adesso
        aperta.save(update_fields=["stato", "esito_deciso", "nota", "decisa_da", "decisa_il"])
    elif action == "reopen" and persona:
        auto = SecurityAlertProposta.objects.filter(alert=alert, stato=SecurityAlertProposta.CHIUSA_AUTO).order_by("-decisa_il").first()
        if auto is not None:
            auto.stato = SecurityAlertProposta.ANNULLATA
            auto.nota = str(details.get("reason") or "Riaperto a mano")[:2000]
            auto.decisa_da = str(actor)[:120]
            auto.decisa_il = adesso
            auto.save(update_fields=["stato", "nota", "decisa_da", "decisa_il"])


def conferma(proposta, user, motivo=""):
    """«Conferma» dalla pagina: chiude l'alert con l'esito proposto, a nome della persona."""
    actor = getattr(user, "username", "") or "ui"
    reason = (motivo or proposta.motivo or "Confermata la proposta dell'AI").strip()[:2000]
    _chiudi(proposta.alert, proposta.esito, actor, reason, user=user)
    proposta.refresh_from_db()
    return proposta


def scarta(proposta, user, nota=""):
    """«Scarta»: l'alert resta aperto; la nota entra nelle decisioni passate dei prossimi alert dello stesso tipo."""
    proposta.stato = SecurityAlertProposta.SCARTATA
    proposta.nota = (nota or "").strip()[:2000]
    proposta.decisa_da = (getattr(user, "username", "") or "ui")[:120]
    proposta.decisa_il = timezone.now()
    proposta.save(update_fields=["stato", "nota", "decisa_da", "decisa_il"])
    return proposta


def riapri(proposta, user, nota=""):
    """«Riapri» una chiusura automatica sbagliata: l'alert torna aperto e quel tipo perde la fiducia."""
    from security.services.alert_lifecycle import reopen_alert

    actor = getattr(user, "username", "") or "ui"
    reopen_alert(proposta.alert, actor=actor, reason=(nota or "Chiusura dell'AI sbagliata").strip()[:2000], user=user)
    proposta.refresh_from_db()
    return proposta


# --- Dati per la pagina ------------------------------------------------------------------------------

def pagina():
    from security.services.alert_gruppi import per_pagina

    since = timezone.now() - timedelta(days=30)
    auto = list(SecurityAlertProposta.objects.filter(stato__in=(SecurityAlertProposta.CHIUSA_AUTO, SecurityAlertProposta.ANNULLATA),
                                                     decisa_il__gte=since)
                .select_related("alert", "alert__source").order_by("-decisa_il")[:100])
    gruppi = {}
    for p in SecurityAlertProposta.objects.filter(creata_il__gte=timezone.now() - timedelta(days=GIORNI_DECISIONI)).exclude(esito="aperto"):
        gruppi.setdefault((p.schema, p.esito), p.schema_label)
    imparato = []
    for (schema, esito), label in gruppi.items():
        stato = fiducia(schema, esito)
        imparato.append({"label": label, "esito": dict(SecurityAlertProposta.ESITI).get(esito, esito), **stato,
                         "percento": min(100, int(100 * stato["conferme"] / max(stato["soglia"], 1)))})
    imparato.sort(key=lambda r: (not r["affidabile"], -r["conferme"], r["label"]))
    return {
        **per_pagina(),
        "auto": auto,
        "imparato": imparato,
        "n_auto_7": sum(1 for p in auto if p.stato == SecurityAlertProposta.CHIUSA_AUTO and p.decisa_il >= timezone.now() - timedelta(days=7)),
        "n_affidabili": sum(1 for r in imparato if r["affidabile"]),
        "attivo": attivo(),
        "chiusura_auto": chiusura_auto_attiva(),
        "soglia": soglia(),
        "confidenza_minima": confidenza_minima(),
    }


def proposta_aperta(alert):
    p = SecurityAlertProposta.objects.filter(alert=alert, stato=SecurityAlertProposta.APERTA).first()
    if p is not None:
        p.blocco = blocco_auto(alert, {"esito": p.esito, "confidenza": p.confidenza, "prove": p.prove, "schema": p.schema})
    return p
