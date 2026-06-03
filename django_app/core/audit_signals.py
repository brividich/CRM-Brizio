"""Segnali globali per audit automatico di INSERT/UPDATE/DELETE su tutti i modelli business.

Funzionamento:
- pre_save: cattura i valori PRIMA della modifica (per calcolare il diff sugli update)
- post_save: logga insert o update con diff dei campi cambiati
- post_delete: logga la cancellazione con i valori al momento della delete

Il contesto utente/IP è recuperato dal thread-local (AuditRequestMiddleware).
Se non c'è request attivo (management command, task asincrono) il log viene scritto
senza utente e IP.

Le app di sistema e i modelli interni sono esclusi per evitare rumore e ricorsione.
"""
from __future__ import annotations

import logging

from django.contrib.auth.signals import user_login_failed
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

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

# Modelli specifici esclusi (formato: "app_label.modelname" tutto minuscolo)
_EXCLUDED_MODELS: frozenset[str] = frozenset({
    "core.auditlog",           # evita ricorsione infinita
    "core.djangocachestore",   # tabella cache SQL (se presente)
})

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
    key = f"{meta.app_label.lower()}.{meta.model_name.lower()}"
    if key in _EXCLUDED_MODELS:
        return True
    return False


def _serialize_value(val):
    """Converte un valore campo in un tipo JSON-serializzabile."""
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    return str(val)


def _is_sensitive(field_name: str) -> bool:
    name_lower = field_name.lower()
    return any(kw in name_lower for kw in _SENSITIVE_FIELD_KEYWORDS)


def _field_snapshot(instance, update_fields=None) -> dict:
    """Restituisce un dict {attname: valore} per i campi concreti dell'istanza.

    Se update_fields è specificato, include solo quei campi.
    I campi sensibili vengono omessi.
    """
    result: dict = {}
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
        try:
            result[attname] = _serialize_value(getattr(instance, attname, None))
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


# ── Segnali ───────────────────────────────────────────────────────────────────

@receiver(pre_save)
def _audit_pre_save(sender, instance, **kwargs):
    """Cattura lo stato precedente dell'istanza prima di un save (solo per UPDATE)."""
    if kwargs.get("raw", False) or _should_skip(sender):
        return
    if instance.pk is None:
        # INSERT: non c'è stato precedente
        instance.__dict__["_audit_old"] = None
        return
    try:
        old_instance = sender.objects.get(pk=instance.pk)
        instance.__dict__["_audit_old"] = _field_snapshot(old_instance)
    except sender.DoesNotExist:
        instance.__dict__["_audit_old"] = None
    except Exception:
        instance.__dict__["_audit_old"] = None


@receiver(post_save)
def _audit_post_save(sender, instance, created, update_fields=None, **kwargs):
    """Logga INSERT o UPDATE dopo un save."""
    if kwargs.get("raw", False) or _should_skip(sender):
        return

    meta = sender._meta
    azione = "auto_insert" if created else "auto_update"
    dettaglio: dict = {
        "model": meta.object_name,
        "pk": str(instance.pk) if instance.pk is not None else None,
        "oggetto": _object_label(instance),
    }

    if created:
        snap = _field_snapshot(instance)
        if snap:
            dettaglio["valori"] = snap
    else:
        old = instance.__dict__.get("_audit_old")
        new_snap = _field_snapshot(instance, update_fields)
        if old:
            diff = _compute_diff(old, new_snap)
            if diff:
                dettaglio["modifiche"] = diff
            # Se diff è vuoto (es. save() senza cambiamenti reali) logghiamo comunque
            # l'evento ma senza payload, così rimane traccia del fatto che è stato chiamato.
        else:
            if new_snap:
                dettaglio["nuovi_valori"] = new_snap

    _write_audit(azione, meta.app_label, dettaglio)


@receiver(post_delete)
def _audit_post_delete(sender, instance, **kwargs):
    """Logga DELETE dopo una cancellazione."""
    if _should_skip(sender):
        return

    meta = sender._meta
    snap = _field_snapshot(instance)
    dettaglio: dict = {
        "model": meta.object_name,
        "pk": str(instance.pk) if instance.pk is not None else None,
        "oggetto": _object_label(instance),
    }
    if snap:
        dettaglio["valori"] = snap

    _write_audit("auto_delete", meta.app_label, dettaglio)


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
