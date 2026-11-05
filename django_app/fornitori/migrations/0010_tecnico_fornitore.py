"""Registro dei tecnici di ogni fornitore.

Registra subito le persone degli ingressi già collegati a un intervento. I permessi delle
rotte di scrittura seguono «Modifica fornitore» (schema create-only come la 0006).
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from fornitori.nomi import chiave_tecnico

ROTTE = {
    "fornitori:tecnico_add": "fornitori:fornitore_edit",
    "fornitori:tecnico_registra": "fornitori:fornitore_edit",
    "fornitori:tecnico_edit": "fornitori:fornitore_edit",
    "fornitori:tecnico_stato": "fornitori:fornitore_edit",
}
NOTA = "[TECNICI_FORNITORE_0010] copiato da {}"


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
    Ingresso = apps.get_model("fornitori", "IngressoIntervento")
    Tecnico = apps.get_model("fornitori", "TecnicoFornitore")
    righe = (Ingresso.objects.filter(fornitore__isnull=False).exclude(tecnico_nome="")
             .values_list("fornitore_id", "tecnico_nome").distinct())
    for fornitore_id, nome in righe:
        nome = (nome or "").strip()[:200]
        if not nome or nome.lower() == "ospite anonimizzato":
            continue
        Tecnico.objects.get_or_create(
            fornitore_id=fornitore_id, chiave=chiave_tecnico(nome),
            defaults={"nome": nome, "origine": "INTERVENTO"},
        )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0214_fornitore_requisiti_sicurezza"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("fornitori", "0009_fornitore_contatori_sezioni_scheda"),
    ]

    operations = [
        migrations.CreateModel(
            name="TecnicoFornitore",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=200, verbose_name="Nome e cognome")),
                ("chiave", models.CharField(editable=False, help_text="Nome confrontabile: maiuscole e ordine delle parole ignorati", max_length=200)),
                ("qualifica", models.CharField(blank=True, max_length=120, verbose_name="Qualifica")),
                ("telefono", models.CharField(blank=True, max_length=30, verbose_name="Telefono")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="Email")),
                ("attestati_fino_al", models.DateField(blank=True, help_text="Facoltativo: compare nelle scadenze della ditta e nello Scadenzario.", null=True, verbose_name="Attestati validi fino al")),
                ("note", models.CharField(blank=True, max_length=255, verbose_name="Note")),
                ("attivo", models.BooleanField(default=True, verbose_name="Attivo")),
                ("origine", models.CharField(choices=[("MANUALE", "Aggiunto a mano"), ("GUESTPORTAL", "Dal GuestPortal"), ("INTERVENTO", "Da un intervento")], default="MANUALE", max_length=12)),
                ("creato_il", models.DateTimeField(auto_now_add=True)),
                ("aggiornato_il", models.DateTimeField(auto_now=True)),
                ("creato_da", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("fornitore", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tecnici", to="anagrafica.fornitore")),
            ],
            options={
                "verbose_name": "Tecnico del fornitore",
                "verbose_name_plural": "Tecnici dei fornitori",
                "ordering": ["-attivo", "nome", "pk"],
                "constraints": [models.UniqueConstraint(fields=("fornitore", "chiave"), name="fornitori_tecnico_unico_per_fornitore")],
            },
        ),
        migrations.RunPython(avanti, indietro),
    ]
