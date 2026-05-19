"""
Esegue il dump di NavigationItem, PermissionDefinition, RolePermissionGrant,
UserPermissionOverride e NavigationSnapshot salvando esplicitamente in UTF-8.
Uso: python django_app/fixtures/dump_nav_acl.py
"""
import os, sys, json, django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..","django_app"))

django.setup()

from django.core import serializers

MODELS = [
    "core.ModuleCategory",
    "core.NavigationItem",
    "core.NavigationSnapshot",
    "core.PermissionDefinition",
    "core.RolePermissionGrant",
    "core.UserPermissionOverride",
]

out = os.path.join(os.path.dirname(__file__), "nav_acl_snapshot.json")

data = serializers.serialize("json", sum(
    [list(__import__(
        "django.apps", fromlist=["apps"]
    ).apps.get_model(m).objects.all()) for m in MODELS], []
), indent=2)

with open(out, "w", encoding="utf-8") as f:
    f.write(data)

print(f"Salvato: {out}")
