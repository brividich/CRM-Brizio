from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("contatori", "0011_dispositivosnmp_community_macchina_snmp_community"),
    ]

    operations = [
        migrations.AddField(
            model_name="sondasnmp",
            name="profilo_colonna",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Colonna del catalogo che ha generato questa sonda; vuoto se manuale."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sonde_generate",
                to="contatori.colonnaprofilosnmp",
            ),
        ),
    ]
