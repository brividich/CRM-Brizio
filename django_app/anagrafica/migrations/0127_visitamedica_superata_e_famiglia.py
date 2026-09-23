import re

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


# Solo la visita medica periodica "pura": varianti come preassuntiva o
# straordinaria restano fuori dalla famiglia (non azzerano la periodicità).
_VISITA_MEDICA_PERIODICA = re.compile(
    r"^visita medica( (semestrale|annuale|biennale|triennale|quadriennale|quinquennale|periodica))?$"
)


def _normalizza(nome: str) -> str:
    return " ".join((nome or "").replace("(", " ").replace(")", " ").lower().split())


def famiglia_visita_medica(apps, schema_editor):
    TipoVisitaMedica = apps.get_model("anagrafica", "TipoVisitaMedica")
    for tipo in TipoVisitaMedica.objects.filter(categoria=""):
        if _VISITA_MEDICA_PERIODICA.match(_normalizza(tipo.nome)):
            tipo.categoria = "Visita medica"
            tipo.save(update_fields=["categoria"])


class Migration(migrations.Migration):

    dependencies = [
        ('anagrafica', '0126_dipendentevisitafacoltativa'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='tipovisitamedica',
            name='categoria',
            field=models.CharField(blank=True, default='', help_text='Famiglia dello stesso esame con periodicità diverse (es. "Visita medica" per annuale, biennale e quinquennale): la visita più recente della famiglia supera le precedenti nello scadenziario. Serve anche a selezionarle insieme nei requisiti di mansione o ruolo.', max_length=100),
        ),
        migrations.AddField(
            model_name='visitamedica',
            name='superata_il',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='visitamedica',
            name='superata_da',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='visitamedica',
            name='superata_motivo',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.RunPython(famiglia_visita_medica, migrations.RunPython.noop),
    ]
