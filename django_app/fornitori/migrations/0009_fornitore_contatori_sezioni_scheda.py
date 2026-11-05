"""Scheda fornitore con manutenzione, copie MFC, scadenze e tecnici.

- ``FornitoreContatori``: abbinamento facoltativo tra un codice del modulo Contatori e il
  fornitore dell'HUB, quando il nome non basta a riconoscerlo.
- Permessi: la sezione segue «Scheda fornitore» (i dati dei singoli moduli sono ricontrollati
  nella view), il collegamento segue «Modifica fornitore». Schema create-only come la 0006.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

ROTTE = {
    "fornitori:fornitore_sezione": "fornitori:fornitore_detail",
    "fornitori:fornitore_collega_contatori": "fornitori:fornitore_edit",
}
NOTA = "[SCHEDA_FORNITORE_0009] copiato da {}"


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
            permission_id=modello.permission_id, source_app="fornitori", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0214_fornitore_requisiti_sicurezza"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("fornitori", "0008_avviso_ingresso_non_in_regola"),
    ]

    operations = [
        migrations.CreateModel(
            name="FornitoreContatori",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codice", models.CharField(help_text="Macchina.fornitore / Fattura.fornitore", max_length=10, unique=True)),
                ("creato_il", models.DateTimeField(auto_now_add=True)),
                ("creato_da", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("fornitore", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="codici_contatori", to="anagrafica.fornitore")),
            ],
            options={
                "verbose_name": "Fornitore del modulo Contatori",
                "verbose_name_plural": "Fornitori del modulo Contatori",
                "ordering": ["codice"],
            },
        ),
        migrations.RunPython(avanti, indietro),
    ]
