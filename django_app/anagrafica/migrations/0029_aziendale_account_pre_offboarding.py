from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0028_subnav_onboarding_offboarding"),
    ]

    operations = [
        migrations.AddField(
            model_name="dipendenteanagraficaaziendale",
            name="utente_id_pre_offboarding",
            field=models.IntegerField(
                blank=True,
                db_index=True,
                help_text="ID legacy dell'account portale da ricollegare se il dipendente viene rimesso in forza.",
                null=True,
                verbose_name="Account portale pre-offboarding",
            ),
        ),
    ]
