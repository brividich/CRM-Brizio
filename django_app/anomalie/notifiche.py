"""Pannello unico delle mail del modulo anomalie.

La stessa vista compare in due posti — Gestione anomalie → Configurazione →
Notifiche e Automazioni → Notifiche di sistema — e legge/scrive i dati dove
stanno già, senza copie:

- liste email del modulo (file JSON delle liste anomalie);
- interruttori e orari dell'escalation (SiteConfig, ``escalation_config``);
- indirizzo della regola Automazioni «nuova anomalia fuori da un controllo».
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Regola Automazioni che manda il link alla nuova anomalia inserita fuori da un
# controllo (le anomalie di un controllo hanno la loro mail, vedi controllo_service).
REGOLA_NUOVA_ANOMALIA = "au-mail-anomalie-cc-car-insert"

# Liste email del modulo modificabili dal pannello: (chiave, etichetta, uso).
LISTE = (
    ("conferma_aggiornamenti", "Riepilogo modifiche",
     "Ricevono sempre il riepilogo delle modifiche alle anomalie."),
    ("rdc_segnalazione", "RDC / segnalazione cliente",
     "Ricevono il riepilogo solo se un'anomalia è da aprire RDC o da segnalare al cliente, "
     "e l'allarme difetto ricorrente."),
    ("escalation_supervisori", "Supervisori",
     "Ricevono il resoconto giornaliero, il digest settimanale e l'allarme difetto ricorrente."),
)
LISTE_KEYS = tuple(k for k, _l, _u in LISTE)
LISTE_LABEL = {k: label for k, label, _u in LISTE}

# Interruttori modificabili: chiave del pannello → chiave di get_escalation_config().
TOGGLE_KEYS = (
    "attivo", "ricorrenza_attivo", "rdc_attivo", "digest_attivo",
    "op_completato_attivo", "decisioni_operatore_attivo",
)
PARAM_KEYS = ("soglia_ore", "ora_invio", "ricorrenza_n", "ricorrenza_giorni", "rdc_giorni",
              "controllo_promemoria_minuti", "controllo_invio_auto_minuti")
AUTO_PARAM_KEYS = ("ricorrenza_n", "ricorrenza_giorni", "rdc_giorni",
                   "controllo_promemoria_minuti", "controllo_invio_auto_minuti")

# Flussi pianificati che spediscono le mail (Automazioni → processi del modulo).
MOTORI = (
    ("anomalie_pending_notifications", "Coda mail anomalie (ogni minuto)"),
    ("anomalie_escalation", "Escalation anomalie (ogni ora)"),
)

_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def _regola_nuova_anomalia():
    """(regola, azione) della mail «nuova anomalia», o (None, None) se assente."""
    try:
        from automazioni.models import AutomationActionType, AutomationRule
        rule = AutomationRule.objects.filter(code=REGOLA_NUOVA_ANOMALIA).first()
        if rule is None:
            return None, None
        action = rule.actions.filter(
            action_type=AutomationActionType.SEND_ANOMALIE_MAIL_ACTION
        ).order_by("order", "id").first()
        return rule, action
    except Exception:
        logger.warning("notifiche anomalie: regola nuova anomalia non leggibile", exc_info=True)
        return None, None


def _motori() -> list[dict]:
    out = []
    try:
        from automazioni.models import ManagedFlow
        flows = {f.code: f for f in ManagedFlow.objects.select_related("rule").filter(
            code__in=[c for c, _l in MOTORI])}
    except Exception:
        flows = {}
    for code, label in MOTORI:
        flow = flows.get(code)
        out.append({
            "code": code,
            "label": label,
            "rule_id": flow.rule_id if flow else None,
            # Senza binding il processo gira come prima dell'installazione dei flussi.
            "attivo": (flow.rule.is_active and not flow.rule.is_draft) if flow else True,
        })
    return out


def _ultimi_invii(kinds: set[str]) -> dict[str, dict]:
    """Ultimo invio (riuscito o fallito) per riga del pannello, dal log email."""
    from .mail_log_models import AnomalieEmailLog

    out: dict[str, dict] = {}
    try:
        rows = AnomalieEmailLog.objects.filter(kind__in=kinds).only(
            "kind", "status", "created_at", "context", "error"
        ).order_by("-created_at", "-id")[:400]
        for row in rows:
            key = row.kind
            if row.kind == "mail_action":
                src = str((row.context or {}).get("source_automation") or "")
                key = "mail_action:controllo" if src.startswith("controllo:") else "mail_action:altro"
            if key not in out:
                out[key] = {"at": row.created_at, "ok": row.status == "sent", "error": row.error or ""}
    except Exception:
        logger.warning("notifiche anomalie: log email non leggibile", exc_info=True)
    return out


def stato_pannello() -> dict:
    """Tutto quello che serve al pannello: mail, destinatari, interruttori, motori."""
    from .escalation_config import durata_label, get_escalation_config
    from .views import _load_anomalie_lists

    cfg = get_escalation_config()
    prom = durata_label(cfg["controllo_promemoria_minuti"])
    auto_inv = durata_label(cfg["controllo_invio_auto_minuti"])
    liste_correnti = _load_anomalie_lists() or {}
    rule, action = _regola_nuova_anomalia()
    nuova_to = str(((action.config_json or {}) if action else {}).get("to") or "").strip()
    nuova_attiva = bool(rule and rule.is_active and not rule.is_draft and action is not None)
    ora = f"{int(cfg['ora_invio']):02d}:00"

    righe = [
        {
            "code": "controllo", "titolo": "Controllo OP: decisione al capocommessa",
            "quando": f"A «Termina controllo»; se il controllo resta fermo parte da sola {auto_inv} dopo "
                      "l'ultimo blocco salvato.",
            "auto": "Capocommessa dell'OP, in copia il CAR e le persone aggiunte dal controllore.", "liste": [],
            "toggle": None, "attiva": True, "log": "mail_action:controllo", "motore": "anomalie_pending_notifications",
        },
        {
            "code": "promemoria_controllo", "titolo": "Promemoria al controllore: mail non ancora inviata",
            "quando": f"{prom} dopo l'ultimo blocco salvato, se la mail del controllo non è ancora partita.",
            "auto": "Chi ha aperto il controllo (notifica nel portale e mail con il riepilogo).", "liste": [],
            "toggle": None, "attiva": True, "log": "promemoria_controllo", "motore": "anomalie_pending_notifications",
        },
        {
            "code": "nuova_anomalia", "titolo": "Nuova anomalia inserita fuori da un controllo",
            "quando": "All'inserimento: mail con il link per decidere.",
            "auto": "", "liste": ["nuova_anomalia"],
            "toggle": "nuova_anomalia" if rule else None, "attiva": nuova_attiva,
            "log": "mail_action:altro", "motore": "",
            "regola_id": rule.pk if rule else None,
        },
        {
            "code": "riepilogo", "titolo": "Riepilogo modifiche",
            "quando": "5 minuti dopo l'ultima modifica sull'OP; dalla pagina della mail parte subito.",
            "auto": "Chi ha segnalato, capocommessa e CAR dell'OP.",
            "liste": ["conferma_aggiornamenti", "rdc_segnalazione"],
            "toggle": None, "attiva": True, "log": "conferma_aggiornamenti", "motore": "anomalie_pending_notifications",
        },
        {
            "code": "decisioni_operatore", "titolo": "Decisioni all'operatore",
            "quando": "Insieme al riepilogo, se a decidere non è stato chi ha segnalato.",
            "auto": "Chi ha segnalato (email di notifica della scheda anagrafica).", "liste": [],
            "toggle": "decisioni_operatore_attivo", "attiva": cfg["decisioni_operatore_attivo"],
            "log": "decisioni_operatore", "motore": "anomalie_pending_notifications",
        },
        {
            "code": "op_completato", "titolo": "OP completato",
            "quando": "Circa 5 minuti dopo la chiusura dell'ultima anomalia aperta dell'OP.",
            "auto": "Capocommessa e CAR dell'OP.", "liste": [],
            "toggle": "op_completato_attivo", "attiva": cfg["op_completato_attivo"],
            "log": "op_completato", "motore": "anomalie_pending_notifications",
        },
        {
            "code": "resoconto", "titolo": "Resoconto OP da controllare",
            "quando": f"Giorni lavorativi alle {ora}, se ci sono anomalie «In attesa» da oltre "
                      f"{cfg['soglia_ore']} ore.",
            "auto": "Capocommessa e CAR degli OP coinvolti.", "liste": ["escalation_supervisori"],
            "toggle": "attivo", "attiva": cfg["attivo"], "log": "escalation_resoconto",
            "motore": "anomalie_escalation",
        },
        {
            "code": "rdc", "titolo": "RDC richiesto ma senza numero",
            "quando": f"«Aprire RDC» senza numero da oltre {cfg['rdc_giorni']} giorni.",
            "auto": "Sezione nel resoconto giornaliero e promemoria in dashboard a capocommessa e CAR.",
            "liste": [], "toggle": "rdc_attivo", "attiva": cfg["rdc_attivo"], "log": "",
            "motore": "anomalie_escalation",
        },
        {
            "code": "ricorrenza", "titolo": "Difetto ricorrente per P/N",
            "quando": f"Lo stesso P/N arriva a {cfg['ricorrenza_n']} anomalie in "
                      f"{cfg['ricorrenza_giorni']} giorni.",
            "auto": "", "liste": ["escalation_supervisori", "rdc_segnalazione"],
            "toggle": "ricorrenza_attivo", "attiva": cfg["ricorrenza_attivo"], "log": "ricorrenza_pn",
            "motore": "anomalie_escalation",
        },
        {
            "code": "digest", "titolo": "Digest settimanale",
            "quando": f"Ogni lunedì alle {ora}.",
            "auto": "", "liste": ["escalation_supervisori"],
            "toggle": "digest_attivo", "attiva": cfg["digest_attivo"], "log": "digest_settimanale",
            "motore": "anomalie_escalation",
        },
    ]

    invii = _ultimi_invii({"mail_action", "promemoria_controllo", "conferma_aggiornamenti", "decisioni_operatore",
                           "op_completato", "escalation_resoconto", "ricorrenza_pn",
                           "digest_settimanale"})
    motori = _motori()
    motori_spenti = {m["code"] for m in motori if not m["attivo"]}
    label_liste = {k: f"lista «{v}»" for k, v in LISTE_LABEL.items()}
    label_liste["nuova_anomalia"] = "indirizzo «Nuova anomalia fuori controllo»"
    for r in righe:
        r["ultimo"] = invii.get(r["log"]) if r["log"] else None
        r["motore_spento"] = r["motore"] in motori_spenti
        r["liste_label"] = [label_liste[k] for k in r["liste"]]

    liste = [
        {"key": k, "label": label, "uso": uso,
         "valori": [e for e in (liste_correnti.get(k) or []) if e]}
        for k, label, uso in LISTE
    ]
    return {
        "righe": righe,
        "liste": liste,
        "nuova_anomalia": {"presente": rule is not None, "to": nuova_to,
                           "attiva": nuova_attiva, "regola_id": rule.pk if rule else None},
        "parametri": {k: cfg[k] for k in PARAM_KEYS},
        "motori": motori,
    }


def _email_list(raw) -> tuple[list[str], list[str]]:
    """(validi, non validi) da una lista o da un testo una-email-per-riga."""
    if isinstance(raw, str):
        raw = re.split(r"[\r\n,;]+", raw)
    if not isinstance(raw, list):
        return [], []
    ok, bad, seen = [], [], set()
    for item in raw:
        value = str(item or "").strip()
        if not value:
            continue
        if not _EMAIL_RE.match(value):
            bad.append(value)
            continue
        if value.lower() not in seen:
            seen.add(value.lower())
            ok.append(value)
    return ok, bad


def salva_pannello(payload: dict) -> tuple[bool, str]:
    """Salva liste, interruttori, orari e indirizzo «nuova anomalia».

    Ogni dato torna dove stava; le chiavi assenti dal payload restano invariate.
    """
    from .escalation_config import get_escalation_config, save_automazioni_config, save_escalation_config
    from .views import ANOMALIE_DERIVED_LIST_KEYS, _load_anomalie_lists, _save_anomalie_lists

    if not isinstance(payload, dict):
        return False, "Dati non validi."

    liste_in = payload.get("liste") if isinstance(payload.get("liste"), dict) else {}
    nuove_liste: dict[str, list[str]] = {}
    errori: list[str] = []
    for key in LISTE_KEYS:
        if key not in liste_in:
            continue
        ok, bad = _email_list(liste_in[key])
        if bad:
            errori.append(f"{LISTE_LABEL[key]}: {', '.join(bad)}")
        nuove_liste[key] = ok

    nuova = payload.get("nuova_anomalia") if isinstance(payload.get("nuova_anomalia"), dict) else None
    nuova_to = None
    if nuova is not None and "to" in nuova:
        ok, bad = _email_list(nuova.get("to"))
        if bad:
            errori.append(f"Nuova anomalia fuori controllo: {', '.join(bad)}")
        elif len(ok) > 1:
            errori.append("Nuova anomalia fuori controllo: un solo indirizzo.")
        nuova_to = ok[0] if ok else ""
    if errori:
        return False, "Indirizzi non validi — " + "; ".join(errori)

    if nuove_liste:
        current = {k: v for k, v in (_load_anomalie_lists() or {}).items()
                   if k not in ANOMALIE_DERIVED_LIST_KEYS}
        current.update(nuove_liste)
        _save_anomalie_lists(current)

    attivi = payload.get("attivi") if isinstance(payload.get("attivi"), dict) else {}
    parametri = payload.get("parametri") if isinstance(payload.get("parametri"), dict) else {}
    cfg = get_escalation_config()
    if "attivo" in attivi or "soglia_ore" in parametri or "ora_invio" in parametri:
        save_escalation_config(
            attivo=bool(attivi.get("attivo", cfg["attivo"])),
            soglia_ore=parametri.get("soglia_ore", cfg["soglia_ore"]),
            ora_invio=parametri.get("ora_invio", cfg["ora_invio"]),
        )
    auto = {k: bool(attivi[k]) for k in TOGGLE_KEYS if k != "attivo" and k in attivi}
    auto.update({k: parametri[k] for k in AUTO_PARAM_KEYS if k in parametri})
    if auto:
        save_automazioni_config(auto)

    if nuova is not None:
        rule, action = _regola_nuova_anomalia()
        if rule is not None and action is not None:
            if nuova_to is not None:
                config = dict(action.config_json or {})
                config["to"] = nuova_to
                action.config_json = config
                action.save(update_fields=["config_json"])
            attiva = bool(nuova.get("attiva", rule.is_active)) and bool(
                nuova_to if nuova_to is not None else (action.config_json or {}).get("to")
            )
            if rule.is_active != attiva or (attiva and rule.is_draft):
                rule.is_active = attiva
                if attiva:
                    rule.is_draft = False
                rule.save(update_fields=["is_active", "is_draft"])
    return True, "Notifiche salvate."
