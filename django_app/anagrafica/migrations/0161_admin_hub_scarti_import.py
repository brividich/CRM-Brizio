"""Hub «Amministrazione anagrafica» (prompt 03, obiettivo C).

* ``scarti`` sugli import retribuzioni e cedolini: le righe scartate con il motivo, per lo storico
  centralizzato e lo scarico dello scarto (vuoto per gli import precedenti).
* Binding ACL v2 delle nuove rotte, copiati da ``anagrafica:impostazioni`` (schema della 0159).
"""
from django.db import migrations, models

ROTTE = {
    "anagrafica:amministrazione_hub": "anagrafica:impostazioni",
    "anagrafica:import_scarti_export": "anagrafica:impostazioni",
}
NOTA = "[ADMIN_HUB_0161] copiato da {}"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = Binding.objects.filter(route_name=sorella, is_active=True).order_by("-priority", "pk").first()
        if modello is None:
            continue
        Binding.objects.create(
            route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):
    dependencies = [("anagrafica", "0160_account_portale_acl")]
    operations = [
        migrations.AddField(
            model_name="importazioneretributiva", name="scarti",
            field=models.JSONField(blank=True, default=list, help_text="Righe scartate: [{riga, chiave, motivo}]"),
        ),
        migrations.AddField(
            model_name="importazionecedolini", name="scarti",
            field=models.JSONField(blank=True, default=list, help_text="Righe scartate o non abbinate: [{riga, chiave, motivo}]"),
        ),
        migrations.RunPython(avanti, indietro),
    ]
