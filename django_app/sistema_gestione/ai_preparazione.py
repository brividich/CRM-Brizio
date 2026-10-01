"""Copilota per la preparazione dell'audit (MT CN 12), costruita sugli audit gia' fatti.

Per i processi dell'audit il portale raccoglie (senza AI): gli audit chiusi precedenti, le NC e le OFI
emerse con il requisito e lo scostamento, le CAR collegate con causa, azione e stato, le verifiche di
efficacia (in particolare quelle NON efficaci) e gli ultimi KPI sotto target. Sono i punti deboli da
riguardare. L'AI scrive la bozza dei quattro campi della preparazione; l'auditor la copia, la corregge
e registra. Impara: al salvataggio si confronta la bozza con quanto registrato.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

MODULO = "sgi"
AZIONE = "preparazione_audit"
CAMPI = ("audit_precedenti", "car_cliente", "documenti_registrazioni", "obiettivi_carenze")
_EFFICACIA = {"EFFICACE": "efficace", "NON_EFFICACE": "NON efficace", "DA_RIVERIFICARE": "da riverificare"}


def _testo_domanda(esito) -> str:
    if esito.domanda_id:
        return esito.domanda.testo
    snap = esito.domanda_snapshot or {}
    return str(snap.get("testo") or esito.testo_aggiuntivo or "")


def storico_audit(audit, *, limite_audit: int = 6) -> dict:
    from .models import Audit, AuditEsito, AuditVerificaEfficacia

    processi = list(audit.processi_catalogo.all())
    precedenti = list(
        Audit.objects.filter(processi_catalogo__in=processi, stato=Audit.STATO_CHIUSO, data_inizio__lt=audit.data_inizio)
        .exclude(pk=audit.pk).distinct().order_by("-data_inizio")[:limite_audit]
    ) if processi else []
    rilievi = []
    esiti = (AuditEsito.objects.filter(audit__in=precedenti, esito__in=[AuditEsito.ESITO_NC, AuditEsito.ESITO_OFI])
             .select_related("audit", "processo", "domanda", "ofi").order_by("-audit__data_inizio")[:40])
    for esito in esiti:
        car = None
        try:
            car_obj = getattr(esito.ofi, "car_procedurale", None) if esito.ofi_id else None
        except Exception:  # noqa: BLE001 - OFI senza CAR
            car_obj = None
        if car_obj is not None:
            car = {"causa": (car_obj.causa or "")[:200], "azione": (car_obj.azione or "")[:200], "chiusa": bool(car_obj.chiusa_il)}
        verifiche = [_EFFICACIA.get(v, v.lower()) for v in
                     AuditVerificaEfficacia.objects.filter(esito=esito).order_by("-data_verifica").values_list("risultato", flat=True)[:1]]
        rilievi.append({
            "audit": esito.audit.numero,
            "data": esito.audit.data_inizio,
            "processo": esito.processo.nome if esito.processo_id else "",
            "tipo": esito.esito,
            "domanda": _testo_domanda(esito)[:200],
            "requisito": (esito.requisito_atteso or "")[:200],
            "scostamento": (esito.scostamento or esito.evidenze or "")[:250],
            "documento": esito.documento,
            "car": car,
            "efficacia": verifiche[0] if verifiche else "",
        })
    kpi = []
    try:
        from .services.procedure import risultato_kpi

        for processo in processi:
            for r in processo.rilevazioni_kpi.order_by("-periodo_a")[:3]:
                risultato = risultato_kpi(r)
                if not risultato.get("target_raggiunto"):
                    kpi.append({"processo": processo.nome, "codice": r.codice, "periodo": f"{r.periodo_da:%m/%Y}-{r.periodo_a:%m/%Y}",
                                "valore": risultato.get("valore"), "target": r.target, "commento": (r.commento or "")[:200]})
    except Exception:  # noqa: BLE001 - KPI non leggibili: si prepara senza
        logger.debug("KPI non disponibili per la preparazione", exc_info=True)

    # Domande con NC/OFI in piu' audit: i punti deboli che si ripetono.
    contatore: dict[str, int] = {}
    for r in rilievi:
        if r["domanda"]:
            contatore[r["domanda"]] = contatore.get(r["domanda"], 0) + 1
    ricorrenti = [d for d, n in sorted(contatore.items(), key=lambda x: -x[1]) if n >= 2][:5]
    return {
        "processi": [p.nome for p in processi],
        "precedenti": [{"pk": a.pk, "numero": a.numero, "data": a.data_inizio} for a in precedenti],
        "rilievi": rilievi,
        "non_efficaci": [r for r in rilievi if r["efficacia"] == _EFFICACIA["NON_EFFICACE"] or (r["car"] and not r["car"]["chiusa"])],
        "ricorrenti": ricorrenti,
        "kpi_sotto_target": kpi[:6],
    }


def contesto(audit, storico: dict) -> str:
    righe = [
        f"Audit {audit.numero} del {audit.data_inizio:%d/%m/%Y}, processi: {', '.join(storico['processi']) or audit.processi or 'n.d.'}",
        f"Punti norma: {audit.punti_norma or 'n.d.'}",
        "Audit chiusi precedenti sugli stessi processi: " + (", ".join(f"{a['numero']} ({a['data']:%d/%m/%Y})" for a in storico["precedenti"]) or "nessuno"),
    ]
    for r in storico["rilievi"]:
        car = ""
        if r["car"]:
            car = f"; CAR: causa «{r['car']['causa'] or 'n.d.'}», azione «{r['car']['azione'] or 'n.d.'}», {'chiusa' if r['car']['chiusa'] else 'ANCORA APERTA'}"
        righe.append(f"- {r['audit']} {r['tipo']} su {r['processo'] or 'processo n.d.'}: «{r['domanda']}» — scostamento: {r['scostamento'] or 'n.d.'}"
                     + (f" (documento {r['documento']})" if r["documento"] else "") + car
                     + (f"; verifica efficacia: {r['efficacia']}" if r["efficacia"] else ""))
    if storico["ricorrenti"]:
        righe.append("DOMANDE CON RILIEVI IN PIÙ AUDIT: " + " | ".join(storico["ricorrenti"]))
    for k in storico["kpi_sotto_target"]:
        righe.append(f"KPI sotto target: {k['processo']} {k['codice']} {k['periodo']} valore {k['valore']} target {k['target']}. {k['commento']}")
    try:
        from ai_assistant.apprendimento import lezioni_testo

        lezioni = lezioni_testo(MODULO, AZIONE)
        if lezioni:
            righe.append(lezioni)
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(righe)[:7000]


ISTRUZIONI = (
    "Sei un auditor interno di un'azienda certificata EN 9100. Dal contesto scrivi la bozza della preparazione "
    "dell'audit (MT CN 12). Rispondi SOLO con JSON con queste quattro chiavi; ogni valore è UN TESTO (una stringa "
    "in italiano, frasi brevi, niente liste né oggetti annidati): "
    "\"audit_precedenti\" (riferimenti degli audit precedenti e cosa è emerso; se non ce ne sono, dillo), "
    "\"car_cliente\" (CAR collegate e il loro stato, evidenziando quelle aperte o non efficaci; se non ce ne sono, dillo), "
    "\"documenti_registrazioni\" (documenti e registrazioni da campionare, partendo da quelli citati nei rilievi), "
    "\"obiettivi_carenze\" (obiettivi della verifica: prima le domande con rilievi ripetuti, le azioni non efficaci e i "
    "KPI sotto target). Usa solo i dati del contesto, non inventare numeri o riferimenti; cita KPI solo se nel "
    "contesto ci sono righe «KPI sotto target»."
)


def _testo(valore) -> str:
    """Il modello a volte risponde con liste o oggetti al posto del testo: li rende righe leggibili."""
    if valore is None:
        return ""
    if isinstance(valore, str):
        return valore
    if isinstance(valore, dict):
        return " — ".join(_testo(v) for v in valore.values() if _testo(v).strip())
    if isinstance(valore, (list, tuple)):
        return "\n".join("- " + _testo(v) for v in valore if _testo(v).strip())
    return str(valore)


def proponi_preparazione(audit, *, user=None) -> dict:
    storico = storico_audit(audit)
    raw = ""
    try:
        from ai_assistant.services import chat_with_ollama

        raw = getattr(chat_with_ollama(ISTRUZIONI, runtime_context=contesto(audit, storico), timeout=120), "content", "") or ""
    except Exception as exc:  # noqa: BLE001
        logger.info("copilota preparazione audit: AI non disponibile: %s", exc)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        dati = json.loads(match.group(0)) if match else {}
    except Exception:  # noqa: BLE001
        dati = {}
    bozza = {campo: _testo(dati.get(campo)).strip()[:3000] for campo in CAMPI} if isinstance(dati, dict) else {c: "" for c in CAMPI}
    proposta = {"ai_disponibile": bool(raw), "bozza": bozza, "storico": storico}
    try:
        from ai_assistant.apprendimento import lezioni, registra_proposta

        if any(bozza.values()):
            registra_proposta(modulo=MODULO, azione=AZIONE, oggetto_ref=audit.pk, proposta=bozza, user=user)
        proposta["apprendimento"] = lezioni(MODULO, AZIONE)
    except Exception:  # noqa: BLE001
        proposta["apprendimento"] = None
    return proposta


def registra_esito(preparazione, user=None) -> None:
    try:
        from ai_assistant.apprendimento import registra_decisione

        registra_decisione(modulo=MODULO, azione=AZIONE, oggetto_ref=preparazione.audit_id, user=user,
                           decisione={campo: getattr(preparazione, campo) for campo in CAMPI})
    except Exception:  # noqa: BLE001
        logger.exception("Esito preparazione audit non registrato")
