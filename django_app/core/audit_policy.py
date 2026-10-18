"""Politica dell'audit automatico: unica fonte di verità, dichiarativa e versionata.

L'audit automatico (``core/audit_signals.py``) registra insert/update/delete dei
modelli. Questa politica decide **quanto** registrare per ciascun modello:

- classe **A** (default, ``"full"``): audit completo. Ogni modello non elencato
  qui sotto resta in classe A (fail-safe: si riduce solo ciò che è elencato);
- classe **B** (``"excluded"``): modelli tecnici ad alto volume che sono già log
  o dati derivati con tabelle proprie → nessuna riga e nessun listener;
- classe **C** (``"metadata_only"``): contenuti voluminosi o personali (file,
  corpi email, testi estratti) → solo chi/cosa/quando/quale record e i **nomi**
  dei campi, mai i valori (minimizzazione GDPR);
- classe **D** (``IGNORED_FIELDS``): audit completo, ma un update che tocca
  solo campi tecnici di stato non produce righe.

Le chiamate esplicite ``log_action(...)`` e ``login_fallito`` non passano da qui
e restano invariate. Modificare questa politica è una modifica della politica di
logging (ISO/IEC 27001): passa da PR + CHANGELOG e incrementa
``AUDIT_POLICY_VERSION``. Dettaglio e motivazioni: ``docs/dr/AUDIT_POLICY.md``.
"""
from __future__ import annotations

from typing import Literal

AUDIT_POLICY_VERSION = 1

# Esclusioni storiche (precedenti alla politica): ricorsione, cache, log già dedicati.
_LEGACY_EXCLUDED_MODELS: frozenset[str] = frozenset({
    "core.auditlog",                      # evita ricorsione infinita
    "core.djangocachestore",              # tabella cache SQL (se presente)
    "anomalie.anomalieemaillog",          # è già una traccia con corpo e destinatari
    "anomalie.anomalieautomazionemarker", # marcatori tecnici di idempotenza
})

# Chiavi ammesse anche se il modello non è installato (nessun warning dal check).
OPTIONAL_KEYS: frozenset[str] = frozenset({"core.djangocachestore"})

# Classe B — tecnici ad alto volume, con tabella di log propria.
TECHNICAL_EXCLUDED_MODELS: frozenset[str] = frozenset({
    "automazioni.automationrunlog",
    "automazioni.automationactionlog",
    "automazioni.clusterheartbeat",
    "automazioni.brokerrecoveryentry",
    "monitoring.automationexecution",
    "monitoring.issueoccurrence",
    "security.securitycveimpact",
    "security.securitykpisnapshot",
    "security.securityreportmetric",
    "contatori.rilevazionesnmp",
})

EXCLUDED_MODELS: frozenset[str] = _LEGACY_EXCLUDED_MODELS | TECHNICAL_EXCLUDED_MODELS

# Classe C — solo metadati, mai i valori.
METADATA_ONLY_MODELS: frozenset[str] = frozenset({
    "security.securitysourcefile",
    "security.securitymailboxmessage",
    "security.securityreport",
    "procedure_refresh.sgitestoestratto",
})

# Classe D — campi tecnici di stato (attname) che da soli non generano audit.
IGNORED_FIELDS: dict[str, frozenset[str]] = {
    "automazioni.automationrule": frozenset({"last_run_at", "last_test_at", "updated_at"}),
    "automazioni.managedflow": frozenset({"queued_task_id", "running_until", "lease_token"}),
    "contatori.dispositivosnmp": frozenset({
        # scritti a ogni interrogazione SNMP (contatori/services.py)
        "snmp_stato", "snmp_ultimo_controllo", "snmp_tempo_risposta_ms",
        "snmp_ultimo_errore", "sys_name", "sys_description", "sys_object_id",
        "sys_uptime_seconds", "firmware_rilevato_il",
    }),
    "security.securitycverecord": frozenset({
        "nvd_fetched_at", "impact_computed_at", "epss", "epss_percentile", "nvd_error",
    }),
    "core.notifica": frozenset({"popup_shown", "letta", "letta_il"}),
}

# Campi «di servizio» mai considerati una modifica reale (oltre ai campi auto_now=True).
ALWAYS_IGNORED_FOR_CHANGE_DETECTION: frozenset[str] = frozenset({
    "updated_at", "modified_at", "aggiornato_il",
})

MAX_VALUE_CHARS = 500

# Conservazione (decisione 16/10/2026): classe A 60 mesi online, poi archivio;
# archivi conservati 120 mesi.
AUDIT_RETENTION_POLICY: dict = {
    "A": {"online_months": 60},
    "archive_months": 120,
}

Classe = Literal["full", "metadata_only", "excluded"]


def model_key(model) -> str:
    meta = model._meta
    return f"{meta.app_label.lower()}.{meta.model_name.lower()}"


def classify_key(key: str) -> Classe:
    key = (key or "").lower()
    if key in EXCLUDED_MODELS:
        return "excluded"
    if key in METADATA_ONLY_MODELS:
        return "metadata_only"
    return "full"


def classify(model) -> Classe:
    # I proxy ereditano la classe del modello concreto.
    concrete = getattr(model._meta, "concrete_model", None) or model
    return classify_key(model_key(concrete))


def ignored_fields(model) -> frozenset[str]:
    """Attname che non contano come modifica reale per ``model``."""
    concrete = getattr(model._meta, "concrete_model", None) or model
    names = set(IGNORED_FIELDS.get(model_key(concrete), ()))
    for f in model._meta.concrete_fields:
        if f.attname in ALWAYS_IGNORED_FOR_CHANGE_DETECTION or getattr(f, "auto_now", False):
            names.add(f.attname)
    return frozenset(names)


def configured_keys() -> frozenset[str]:
    """Tutte le chiavi dichiarate (per la verifica dei refusi)."""
    return EXCLUDED_MODELS | METADATA_ONLY_MODELS | frozenset(IGNORED_FIELDS)


def summary() -> dict:
    """Riepilogo leggibile (doctor / Centrale di comando)."""
    return {
        "version": AUDIT_POLICY_VERSION,
        "excluded": sorted(TECHNICAL_EXCLUDED_MODELS),
        "metadata_only": sorted(METADATA_ONLY_MODELS),
        "ignored_fields": {k: sorted(v) for k, v in sorted(IGNORED_FIELDS.items())},
        "max_value_chars": MAX_VALUE_CHARS,
        "retention": AUDIT_RETENTION_POLICY,
    }
