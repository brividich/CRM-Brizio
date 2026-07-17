from django.db import migrations


# La pagina dedicata "Asset produzione" (work_machine_list) e' confluita
# nell'inventario unico asset_list?group=production. Ripuntiamo il bottone di
# navigazione gia' seminato a DB (code="work_machines") sulla lista unica. La
# voce sottostante "Dashboard officina" resta invariata.
_OLD_TARGET = "django:assets:work_machine_list"
_OLD_ACTIVE_MATCH = "/assets/work-machines/"
_NEW_TARGET = "django:assets:asset_list?group=production&rows={rows}"
_NEW_ACTIVE_MATCH = "group=production"


def repoint_work_machines_button(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code="work_machines").update(
        target_url=_NEW_TARGET,
        active_match=_NEW_ACTIVE_MATCH,
    )


def restore_work_machines_button(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code="work_machines").update(
        target_url=_OLD_TARGET,
        active_match=_OLD_ACTIVE_MATCH,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0084_seed_part_145_sidebar_button"),
    ]

    operations = [
        migrations.RunPython(
            repoint_work_machines_button,
            restore_work_machines_button,
        ),
    ]
