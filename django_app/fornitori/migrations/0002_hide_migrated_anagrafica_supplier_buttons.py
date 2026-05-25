from __future__ import annotations

from django.db import migrations


_OLD_CODES = [
    "view_anagrafica_fornitori",
    "anagrafica_fornitori",
    "anagrafica_fornitore_create",
    "view_anagrafica_fornitore_create",
]


def hide_migrated_supplier_buttons(apps, schema_editor):
    Pulsante = apps.get_model("core", "Pulsante")

    for code in _OLD_CODES:
        Pulsante.objects.filter(
            codice__iexact=code,
            url__startswith="/__legacy_disabled__/fornitori/",
        ).update(modulo="")


class Migration(migrations.Migration):
    dependencies = [
        ("fornitori", "0001_split_fornitori_acl"),
    ]

    operations = [
        migrations.RunPython(hide_migrated_supplier_buttons, reverse_code=migrations.RunPython.noop),
    ]
