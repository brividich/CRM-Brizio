"""Sale proposte negli inviti (Reception → Configurazione → Sale) e permesso della pagina.

- ``SalaInviti``: una riga = la sala del KICK-OFF compare in «Prenota una sala». Si parte con tutte
  le sale attive, così niente cambia per chi usava già la scelta della sala.
- ``reception:sale``: stesso binding di ``reception:impostazioni`` (permesso reception.impostazioni.manage).
"""
import django.db.models.deletion
from django.db import migrations, models

NOTA = "[RECEPTION_0008] copiato da reception:impostazioni"


def avanti(apps, schema_editor):
    MeetingRoom = apps.get_model("tasks", "MeetingRoom")
    SalaInviti = apps.get_model("reception", "SalaInviti")
    for pk in MeetingRoom.objects.filter(attiva=True).values_list("pk", flat=True):
        SalaInviti.objects.get_or_create(sala_id=pk)
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if Binding.objects.filter(route_name="reception:sale").exists():
        return
    modello = Binding.objects.filter(route_name="reception:impostazioni", is_active=True).order_by("-priority", "pk").first()
    if modello is not None:
        Binding.objects.create(route_name="reception:sale", path_pattern="", match_strategy=modello.match_strategy,
                               permission_id=modello.permission_id, source_app="reception", priority=modello.priority,
                               is_active=True, note=NOTA)


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(note=NOTA).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("reception", "0007_preregistrazione_sala"),
        ("tasks", "0069_punto_odg_voci"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SalaInviti",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sala", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="tasks.meetingroom")),
            ],
            options={"verbose_name": "Sala per gli inviti", "verbose_name_plural": "Sale per gli inviti"},
        ),
        migrations.RunPython(avanti, indietro),
    ]
