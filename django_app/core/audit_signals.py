"""Audit automatico di INSERT/UPDATE/DELETE sui modelli, governato da ``core.audit_policy``.

Funzionamento:
- pre_save: cattura i valori PRIMA della modifica (per calcolare il diff sugli update)
- post_save: logga insert o update con diff dei campi cambiati
- post_delete: logga la cancellazione con i valori al momento della delete

I receiver sono collegati **per modello** (``connect_audit_signals``, chiamata da
``CoreConfig.ready``) e solo ai modelli che la politica non esclude: i modelli
tecnici di classe B non hanno listener, così Django può tornare a cancellarli in
blocco (fast-delete) e nessuna SELECT in più viene fatta per i loro save.

Regole (vedi ``core/audit_policy.py``):
- un update senza modifiche reali (diff vuoto dopo aver tolto i campi ``auto_now``
  e i campi tecnici del modello) non scrive nulla;
- i valori lunghi sono troncati a ``MAX_VALUE_CHARS`` con lunghezza e impronta;
- i modelli ``metadata_only`` registrano solo i nomi dei campi, mai i valori.

Il contesto utente/IP è recuperato dal thread-local (AuditRequestMiddleware).
Se non c'è request attivo (management command, task asincrono) il log viene scritto
senza utente e IP.
"""
from __future__ import annotations

import hashlib
import logging

from django.contrib.auth.signals import user_login_failed
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from core import audit_policy

logger = logging.getLogger(__name__)

# ── Esclusioni ────────────────────────────────────────────────────────────────

# App Django/sistema: troppo rumorosi o irrilevanti per l'audit business
_EXCLUDED_APPS: frozenset[str] = frozenset({
    "sessions",
    "contenttypes",
    "auth",          # last_login aggiornato ad ogni accesso → rumoroso
    "admin",
    "axes",          # gestisce il proprio log accessi
    "django_q",
    "django_htmx",
    "django_extensions",
    "migrations",    # MigrationRecorder.Migration: salvato a ogni migrazione applicata;
                     # durante setup DB core_auditlog può non esistere ancora e l'INSERT
                     # fallita romperebbe la transazione atomica della migrazione.
})

# Modelli esclusi (formato "app_label.modelname"): ora dichiarati nella politica.
_EXCLUDED_MODELS: frozenset[str] = audit_policy.EXCLUDED_MODELS

# Nomi di campo (o sottostringhe) da non includere nei valori loggati
_SENSITIVE_FIELD_KEYWORDS: frozenset[str] = frozenset({
    "password", "token", "secret", "hash_versione_letta",
})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ip_origin_label(ip: str | None) -> str:
    """Restituisce 'locale' se l'IP è privato/loopback, 'internet' altrimenti."""
    if not ip:
        return "sconosciuto"
    try:
        import ipaddress
        addr = ipaddress.ip_address(ip)
        if addr.is_loopback or addr.is_private or addr.is_link_local:
            return "locale"
        return "internet"
    except ValueError:
        return "sconosciuto"


def _should_skip(sender) -> bool:
    meta = getattr(sender, "_meta", None)
    if meta is None:
        return True
    # Modelli storici delle migrazioni: __module__ == "__fake__".
    # Gli oggetti creati/modificati dalle data-migration non sono eventi business
    # e, durante l'applicazione delle migrazioni, la tabella core_auditlog può non
    # esistere ancora: una INSERT fallita romperebbe la transazione atomica della
    # migrazione (TransactionManagementError). Mai loggare in questo contesto.
    if getattr(sender, "__module__", "") == "__fake__":
        return True
    if meta.app_label.lower() in _EXCLUDED_APPS:
        return True
    if audit_policy.classify(sender) == "excluded":
        return True
    return False


def _fingerprint(val) -> str:
    """Impronta breve (16 cifre esadecimali) di un valore, senza conservarlo."""
    if isinstance(val, memoryview):
        val = val.tobytes()
    raw = val if isinstance(val, (bytes, bytearray)) else str(val).encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()[:16]


def _truncate(text: str) -> str:
    limit = audit_policy.MAX_VALUE_CHARS
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…[troncato, {len(text)} caratteri, sha256={_fingerprint(text)}]"


def _serialize_value(val):
    """Converte un valore campo in un tipo JSON-serializzabile, troncando i valori lunghi."""
    if val is None or isinstance(val, (int, float, bool)):
        return val
    if isinstance(val, (bytes, bytearray, memoryview)):
        return f"<binario {len(val)} byte>"
    if isinstance(val, str):
        return _truncate(val)
    return _truncate(str(val))


def _is_sensitive(field_name: str) -> bool:
    name_lower = field_name.lower()
    return any(kw in name_lower for kw in _SENSITIVE_FIELD_KEYWORDS)


def _concrete_attnames(instance, update_fields=None):
    for f in instance._meta.get_fields():
        # get_fields include relazioni; i campi concreti hanno attname
        attname = getattr(f, "attname", None)
        if not attname:
            continue
        if _is_sensitive(attname):
            continue
        if update_fields is not None:
            # update_fields può contenere sia il name che l'attname
            fname = getattr(f, "name", attname)
            if attname not in update_fields and fname not in update_fields:
                continue
        yield attname


def _field_snapshot(instance, update_fields=None) -> dict:
    """Restituisce un dict {attname: valore} per i campi concreti dell'istanza.

    Se update_fields è specificato, include solo quei campi.
    I campi sensibili vengono omessi.
    """
    result: dict = {}
    for attname in _concrete_attnames(instance, update_fields):
        try:
            result[attname] = _serialize_value(getattr(instance, attname, None))
        except Exception:
            pass
    return result


def _fingerprint_snapshot(instance, update_fields=None) -> dict:
    """Come ``_field_snapshot`` ma con le sole impronte: per i modelli metadata_only
    basta sapere *quali* campi cambiano, senza tenere in memoria i contenuti."""
    result: dict = {}
    for attname in _concrete_attnames(instance, update_fields):
        try:
            val = getattr(instance, attname, None)
            result[attname] = None if val is None else _fingerprint(val)
        except Exception:
            pass
    return result


def _compute_diff(old: dict, new: dict) -> dict:
    """Restituisce solo i campi che sono cambiati tra old e new."""
    return {
        k: {"old": old.get(k), "new": v}
        for k, v in new.items()
        if old.get(k) != v
    }


def _object_label(instance) -> str:
    try:
        return str(instance)[:200]
    except Exception:
        return ""


def _base_dettaglio(meta, instance) -> dict:
    return {
        "model": meta.object_name,
        "pk": str(instance.pk) if instance.pk is not None else None,
        "oggetto": _object_label(instance),
    }


# ── Segnali ───────────────────────────────────────────────────────────────────

def _audit_pre_save(sender, instance, **kwargs):
    """Cattura lo stato precedente dell'istanza prima di un save (solo per UPDATE)."""
    if kwargs.get("raw", False) or _should_skip(sender):
        return
    if instance.pk is None:
        # INSERT: non c'è stato precedente
        instance.__dict__["_audit_old"] = None
        return
    snapshot = (
        _fingerprint_snapshot if audit_policy.classify(sender) == "metadata_only" else _field_snapshot
    )
    try:
        old_instance = sender.objects.get(pk=instance.pk)
        instance.__dict__["_audit_old"] = snapshot(old_instance)
    except sender.DoesNotExist:
        instance.__dict__["_audit_old"] = None
    except Exception:
        instance.__dict__["_audit_old"] = None


def _audit_post_save(sender, instance, created, update_fields=None, **kwargs):
    """Logga INSERT o UPDATE dopo un save."""
    if kwargs.get("raw", False) or _should_skip(sender):
        return

    meta = sender._meta
    azione = "auto_insert" if created else "auto_update"
    dettaglio = _base_dettaglio(meta, instance)
    metadata_only = audit_policy.classify(sender) == "metadata_only"

    if created:
        if metadata_only:
            valorizzati = [
                k for k, v in _fingerprint_snapshot(instance).items()
                if v is not None and v != _fingerprint("")
            ]
            if valorizzati:
                dettaglio["campi_valorizzati"] = valorizzati
        else:
            snap = _field_snapshot(instance)
            if snap:
                dettaglio["valori"] = snap
    else:
        old = instance.__dict__.get("_audit_old")
        snapshot = _fingerprint_snapshot if metadata_only else _field_snapshot
        new_snap = snapshot(instance, update_fields)
        if old:
            diff = _compute_diff(old, new_snap)
            ignorati = audit_policy.ignored_fields(sender)
            significativi = {k: v for k, v in diff.items() if k not in ignorati}
            if not significativi:
                # Nessuna modifica reale (save a vuoto o solo campi tecnici/auto_now):
                # nessuna riga di audit.
                return
            if metadata_only:
                dettaglio["campi"] = sorted(significativi)
            else:
                dettaglio["modifiche"] = significativi
            tecnici = sorted(k for k in diff if k in ignorati)
            if tecnici:
                dettaglio["campi_tecnici_cambiati"] = tecnici
        else:
            if metadata_only:
                if new_snap:
                    dettaglio["campi"] = sorted(new_snap)
            elif new_snap:
                dettaglio["nuovi_valori"] = new_snap

    _write_audit(azione, meta.app_label, dettaglio)


def _audit_post_delete(sender, instance, **kwargs):
    """Logga DELETE dopo una cancellazione."""
    if _should_skip(sender):
        return

    meta = sender._meta
    dettaglio = _base_dettaglio(meta, instance)
    if audit_policy.classify(sender) != "metadata_only":
        snap = _field_snapshot(instance)
        if snap:
            dettaglio["valori"] = snap

    _write_audit("auto_delete", meta.app_label, dettaglio)


def _dispatch_uid(signal_name: str, model) -> str:
    return f"core.audit.{signal_name}.{model._meta.label_lower}"


def connect_audit_signals(models=None) -> int:
    """Collega i receiver di audit ai soli modelli che la politica non esclude.

    Idempotente (``dispatch_uid``). Restituisce il numero di modelli collegati.
    """
    if models is None:
        from django.apps import apps

        models = apps.get_models()
    collegati = 0
    for model in models:
        if model._meta.abstract or _should_skip(model):
            continue
        pre_save.connect(_audit_pre_save, sender=model, dispatch_uid=_dispatch_uid("pre_save", model))
        post_save.connect(_audit_post_save, sender=model, dispatch_uid=_dispatch_uid("post_save", model))
        post_delete.connect(_audit_post_delete, sender=model, dispatch_uid=_dispatch_uid("post_delete", model))
        collegati += 1
    return collegati


def is_audited(model) -> bool:
    """True se il modello ha i receiver di audit collegati."""
    uid = _dispatch_uid("post_delete", model)
    return any(key[0] == uid for key, *_ in post_delete.receivers)


# ── Segnale login fallito ─────────────────────────────────────────────────────

@receiver(user_login_failed)
def _audit_login_failed(sender, credentials, request, **kwargs):
    """Logga ogni tentativo di login fallito (username errato o password sbagliata)."""
    try:
        username = str(credentials.get("username", ""))[:200] if credentials else ""
        dettaglio: dict = {"username": username}
        if request is not None:
            from core.audit import _get_client_ip
            ip = _get_client_ip(request)
            if ip:
                dettaglio["ip"] = ip
            dettaglio["origine"] = _ip_origin_label(ip)
        _write_audit("login_fallito", "core", dettaglio)
    except Exception:
        logger.exception("audit: login_fallito signal fallito")


# ── Scrittura audit ───────────────────────────────────────────────────────────

def _write_audit(azione: str, modulo: str, dettaglio: dict) -> None:
    try:
        from core.audit import log_action
        from core.audit_middleware import get_current_request

        request = get_current_request()
        if request is not None:
            log_action(request, azione, modulo, dettaglio)
        else:
            # Nessun contesto HTTP: management command, task async, ecc.
            from core.models import AuditLog
            AuditLog.objects.create(
                azione=azione,
                modulo=modulo,
                dettaglio=dettaglio,
            )
    except Exception:
        logger.exception("audit_signals: scrittura fallita azione=%s modulo=%s", azione, modulo)
