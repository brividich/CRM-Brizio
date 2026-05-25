from __future__ import annotations

from django.db import migrations


_SEED_MARKER = "[FORNITORI_ACL_SPLIT]"

_BUTTONS = [
    ("fornitori_index", "Fornitori - Dashboard", "route:fornitori:index", "briefcase"),
    ("fornitori_list", "Fornitori - Lista", "route:fornitori:fornitori_list", "briefcase"),
    ("fornitori_create", "Fornitori - Nuovo fornitore", "route:fornitori:fornitore_create", "plus"),
    ("fornitore_detail", "Fornitori - Scheda fornitore", "route:fornitori:fornitore_detail", "file-text"),
    ("fornitore_edit", "Fornitori - Modifica fornitore", "route:fornitori:fornitore_edit", "edit"),
    ("fornitore_toggle_active", "Fornitori - Attiva/disattiva", "route:fornitori:fornitore_toggle_active", "toggle-left"),
    ("fornitore_documento_add", "Fornitori - Aggiungi documento", "route:fornitori:fornitore_documento_add", "upload"),
    ("fornitore_documento_delete", "Fornitori - Elimina documento", "route:fornitori:fornitore_documento_delete", "trash"),
    ("fornitore_ordine_add", "Fornitori - Aggiungi ordine", "route:fornitori:fornitore_ordine_add", "shopping-cart"),
    ("fornitore_ordine_stato", "Fornitori - Cambia stato ordine", "route:fornitori:fornitore_ordine_stato", "refresh-cw"),
    ("fornitore_valutazione_add", "Fornitori - Aggiungi valutazione", "route:fornitori:fornitore_valutazione_add", "star"),
    ("fornitore_valutazione_delete", "Fornitori - Elimina valutazione", "route:fornitori:fornitore_valutazione_delete", "trash"),
    ("fornitore_asset_add", "Fornitori - Collega asset", "route:fornitori:fornitore_asset_add", "link"),
    ("fornitore_asset_remove", "Fornitori - Scollega asset", "route:fornitori:fornitore_asset_remove", "unlink"),
]

_ROUTE_BINDINGS = [
    ("fornitori:index", "fornitori_index"),
    ("fornitori:fornitori_list", "fornitori_list"),
    ("fornitori:fornitore_create", "fornitori_create"),
    ("fornitori:fornitore_detail", "fornitore_detail"),
    ("fornitori:fornitore_edit", "fornitore_edit"),
    ("fornitori:fornitore_toggle_active", "fornitore_toggle_active"),
    ("fornitori:fornitore_documento_add", "fornitore_documento_add"),
    ("fornitori:fornitore_documento_delete", "fornitore_documento_delete"),
    ("fornitori:fornitore_ordine_add", "fornitore_ordine_add"),
    ("fornitori:fornitore_ordine_stato", "fornitore_ordine_stato"),
    ("fornitori:fornitore_valutazione_add", "fornitore_valutazione_add"),
    ("fornitori:fornitore_valutazione_delete", "fornitore_valutazione_delete"),
    ("fornitori:fornitore_asset_add", "fornitore_asset_add"),
    ("fornitori:fornitore_asset_remove", "fornitore_asset_remove"),
]

_LEGACY_ALIASES = [
    ("anagrafica", "view_anagrafica_fornitori", "fornitori_list"),
    ("anagrafica", "anagrafica_fornitori", "fornitori_list"),
    ("anagrafica", "anagrafica_fornitore_create", "fornitori_create"),
    ("anagrafica", "view_anagrafica_fornitore_create", "fornitori_create"),
]


def _boolish(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"} or value is True


def _merge_permesso(Permesso, *, old_modulo: str, old_azione: str, new_azione: str) -> None:
    old_rows = list(
        Permesso.objects.filter(modulo__iexact=old_modulo, azione__iexact=old_azione).order_by("id")
    )
    for old in old_rows:
        role_id = int(getattr(old, "ruolo_id", 0) or 0)
        if not role_id:
            continue
        target = (
            Permesso.objects.filter(
                ruolo_id=role_id,
                modulo__iexact="fornitori",
                azione__iexact=new_azione,
            )
            .order_by("id")
            .first()
        )
        if target is None:
            Permesso.objects.create(
                ruolo_id=role_id,
                modulo="fornitori",
                azione=new_azione,
                consentito=getattr(old, "consentito", 0) or 0,
                can_view=getattr(old, "can_view", 0) or 0,
                can_edit=getattr(old, "can_edit", 0) or 0,
                can_delete=getattr(old, "can_delete", 0) or 0,
                can_approve=getattr(old, "can_approve", 0) or 0,
            )
            continue

        updates = []
        for field in ("consentito", "can_view", "can_edit", "can_delete", "can_approve"):
            old_value = getattr(old, field, 0)
            target_value = getattr(target, field, 0)
            if _boolish(old_value) and not _boolish(target_value):
                setattr(target, field, 1)
                updates.append(field)
        if updates:
            target.save(update_fields=updates)


def seed_fornitori_acl(apps, schema_editor):
    Pulsante = apps.get_model("core", "Pulsante")
    Permesso = apps.get_model("core", "Permesso")
    Ruolo = apps.get_model("core", "Ruolo")
    PermissionDefinition = apps.get_model("core", "PermissionDefinition")
    RoutePermissionBinding = apps.get_model("core", "RoutePermissionBinding")

    button_by_code = {code: (label, url, icon) for code, label, url, icon in _BUTTONS}

    for old_modulo, old_codice, new_codice in _LEGACY_ALIASES:
        label, url, icon = button_by_code[new_codice]
        for button in Pulsante.objects.filter(modulo__iexact=old_modulo, codice__iexact=old_codice):
            target_exists = Pulsante.objects.filter(codice__iexact=new_codice).exclude(id=button.id).exists()
            button.modulo = "fornitori"
            button.nome_visibile = f"{label} (storico)"
            button.icona = icon
            if target_exists:
                button.modulo = ""
                button.url = f"/__legacy_disabled__/fornitori/{old_codice}/"
                button.save(update_fields=["modulo", "nome_visibile", "url", "icona"])
            else:
                button.codice = new_codice
                button.nome_visibile = label
                button.url = url
                button.save(update_fields=["modulo", "codice", "nome_visibile", "url", "icona"])
        _merge_permesso(Permesso, old_modulo=old_modulo, old_azione=old_codice, new_azione=new_codice)

    for codice, label, url, icon in _BUTTONS:
        existing = list(Pulsante.objects.filter(codice__iexact=codice).order_by("id"))
        if not existing:
            Pulsante.objects.create(
                modulo="fornitori",
                codice=codice,
                nome_visibile=label,
                url=url,
                icona=icon,
            )
            continue
        for button in existing:
            updates = []
            if button.modulo != "fornitori":
                button.modulo = "fornitori"
                updates.append("modulo")
            if button.nome_visibile != label:
                button.nome_visibile = label
                updates.append("nome_visibile")
            if button.url != url:
                button.url = url
                updates.append("url")
            if button.icona != icon:
                button.icona = icon
                updates.append("icona")
            if updates:
                button.save(update_fields=updates)

    role_ids = [int(role_id) for role_id in Ruolo.objects.values_list("id", flat=True)]
    for role_id in role_ids:
        for codice, _label, _url, _icon in _BUTTONS:
            exists = Permesso.objects.filter(
                ruolo_id=role_id,
                modulo__iexact="fornitori",
                azione__iexact=codice,
            ).exists()
            if not exists:
                Permesso.objects.create(
                    ruolo_id=role_id,
                    modulo="fornitori",
                    azione=codice,
                    consentito=0,
                    can_view=0,
                    can_edit=0,
                    can_delete=0,
                    can_approve=0,
                )

    for codice, label, _url, _icon in _BUTTONS:
        PermissionDefinition.objects.update_or_create(
            code=f"legacy.fornitori.{codice}",
            defaults={
                "label": label,
                "module": "fornitori",
                "description": f"{_SEED_MARKER} Compat permessi legacy modulo Fornitori",
                "is_active": True,
            },
        )

    for route_name, codice in _ROUTE_BINDINGS:
        RoutePermissionBinding.objects.update_or_create(
            route_name=route_name,
            path_pattern="",
            defaults={
                "match_strategy": "exact",
                "permission_id": f"legacy.fornitori.{codice}",
                "source_app": "fornitori",
                "note": f"{_SEED_MARKER} split Anagrafica HR / Fornitori",
                "priority": 80,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_fornitori_acl, reverse_code=migrations.RunPython.noop),
    ]
