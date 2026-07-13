import fnmatch
import json
import re

from django.core.exceptions import PermissionDenied
from django.forms.models import model_to_dict

from security.models import (
    SecurityCenterSetting,
    SecurityConfigurationAuditLog,
    SecuritySourceConfig,
    SettingValueType,
)


REDACTED = "[redacted]"


def can_manage_security_config(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_staff or user.has_perm("security.manage_security_configuration"))
    )


def require_security_config_access(user):
    if not can_manage_security_config(user):
        raise PermissionDenied


def get_setting(key, default=None):
    try:
        setting = SecurityCenterSetting.objects.get(key=key)
    except SecurityCenterSetting.DoesNotExist:
        return default
    return _coerce_value(setting.value, setting.value_type, default)


def set_setting(key, value, actor=None, **defaults):
    setting, created = SecurityCenterSetting.objects.get_or_create(
        key=key,
        defaults={
            "value": value,
            "value_type": defaults.get("value_type", _infer_value_type(value)),
            "category": defaults.get("category", "general"),
            "description": defaults.get("description", ""),
            "is_secret": defaults.get("is_secret", False),
            "updated_by": actor if getattr(actor, "is_authenticated", False) else None,
        },
    )
    if created:
        audit_config_change(actor, "create", setting, "value", "", _audit_value(value, setting.is_secret))
        return setting
    old_value = setting.value
    setting.value = value
    if "value_type" in defaults:
        setting.value_type = defaults["value_type"]
    if "category" in defaults:
        setting.category = defaults["category"]
    if "description" in defaults:
        setting.description = defaults["description"]
    if "is_secret" in defaults:
        setting.is_secret = defaults["is_secret"]
    if getattr(actor, "is_authenticated", False):
        setting.updated_by = actor
    setting.save()
    audit_config_change(actor, "update", setting, "value", _audit_value(old_value, setting.is_secret), _audit_value(value, setting.is_secret))
    return setting


def get_bool_setting(key, default=False):
    return bool(get_setting(key, default))


def get_int_setting(key, default=0):
    try:
        return int(get_setting(key, default))
    except (TypeError, ValueError):
        return default


def get_float_setting(key, default=0.0):
    try:
        return float(get_setting(key, default))
    except (TypeError, ValueError):
        return default


def get_json_setting(key, default=None):
    value = get_setting(key, default if default is not None else {})
    return value if isinstance(value, (dict, list)) else default


def source_matches_sample(source_config, sender="", subject="", body=""):
    sender_subject_body = f"{sender or ''}\n{subject or ''}\n{body or ''}"
    sender_ok = _matches_any(source_config.mailbox_sender_patterns, sender)
    subject_ok = _matches_any(source_config.mailbox_subject_patterns, subject)
    if not source_config.mailbox_sender_patterns and not source_config.mailbox_subject_patterns:
        metadata = source_config.metadata_json or {}
        tokens = metadata.get("match_tokens", [])
        return _matches_any(tokens, sender_subject_body)
    return sender_ok and subject_ok if source_config.mailbox_sender_patterns and source_config.mailbox_subject_patterns else sender_ok or subject_ok


def audit_model_form_changes(actor, instance, old_data, new_data, request=None, secret_fields=None):
    secret_fields = set(secret_fields or [])
    changed = False
    for field, new_value in new_data.items():
        old_value = old_data.get(field)
        if old_value != new_value:
            changed = True
            audit_config_change(
                actor,
                "update",
                instance,
                field,
                _audit_value(old_value, field in secret_fields),
                _audit_value(new_value, field in secret_fields),
                request=request,
            )
    return changed


def snapshot_instance(instance):
    return model_to_dict(instance)


def audit_config_change(actor, action, instance, field_name="", old_value="", new_value="", request=None):
    SecurityConfigurationAuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        model_name=instance.__class__.__name__,
        object_id=str(getattr(instance, "pk", "") or ""),
        object_repr=str(instance)[:255],
        field_name=field_name,
        old_value=_to_audit_text(old_value),
        new_value=_to_audit_text(new_value),
        request_ip=_request_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:1000] if request else ""),
    )


def masked_setting_value(setting):
    return "********" if setting.is_secret and setting.value not in ("", None) else setting.value


def _matches_any(patterns, value):
    value = value or ""
    for pattern in patterns or []:
        pattern = str(pattern or "").strip()
        if not pattern:
            continue
        if pattern.startswith("regex:"):
            if re.search(pattern[6:], value, re.I):
                return True
        elif fnmatch.fnmatch(value.lower(), pattern.lower()):
            return True
        elif pattern.lower() in value.lower():
            return True
    return False


def _coerce_value(value, value_type, default):
    try:
        if value_type == SettingValueType.BOOL:
            if isinstance(value, bool):
                return value
            return str(value).lower() in {"1", "true", "yes", "on"}
        if value_type == SettingValueType.INT:
            return int(value)
        if value_type == SettingValueType.FLOAT:
            return float(value)
        if value_type == SettingValueType.JSON:
            return value if isinstance(value, (dict, list)) else json.loads(value)
        return "" if value is None else str(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _infer_value_type(value):
    if isinstance(value, bool):
        return SettingValueType.BOOL
    if isinstance(value, int):
        return SettingValueType.INT
    if isinstance(value, float):
        return SettingValueType.FLOAT
    if isinstance(value, (dict, list)):
        return SettingValueType.JSON
    return SettingValueType.STRING


def _audit_value(value, is_secret=False):
    return REDACTED if is_secret else value


def _to_audit_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:2000]
    return json.dumps(value, default=str, sort_keys=True)[:2000]


def _request_ip(request):
    if not request:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or None


def source_config_for_parser(parser_name):
    return SecuritySourceConfig.objects.filter(parser_name=parser_name, enabled=True).first()
