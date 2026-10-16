"""Eccezione sul capo della persona (regola unica capo/team, fase 2a) e binding ACL
della pagina «Coerenza capi», copiato dall'organigramma (schema della 0168)."""

from django.db import migrations, models


ROTTE = {
    "anagrafica:coerenza_capi": "anagrafica:organigramma",
    "anagrafica:coerenza_capi_eccezione": "anagrafica:organigramma",
}
NOTA = "[COERENZA_CAPI_0179] copiato da {}"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = None
        for candidata in (sorella, "anagrafica:dipendenti_list"):
            modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
            if modello is not None:
                break
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

    dependencies = [
        ('anagrafica', '0178_ambito_incarichi'),
    ]

    operations = [
        migrations.AddField(
            model_name='dipendenteanagraficaaziendale',
            name='capo_eccezione_legacy_id',
            field=models.IntegerField(blank=True, db_index=True, help_text='ID legacy del capo indicato a mano per questa persona: vince su area, reparto e organigramma.', null=True, verbose_name='Capo (eccezione)'),
        ),
        migrations.AddField(
            model_name='dipendenteanagraficaaziendale',
            name='capo_eccezione_motivo',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name="Motivo dell'eccezione"),
        ),
        migrations.RunPython(avanti, indietro),
    ]
