from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0176_mansioni_rischio_unificate_pulizia"),
        ("core", "0080_bacheca_self_help"),
    ]

    operations = [
        migrations.AddField(
            model_name="ruolooperativo",
            name="profili_permessi",
            field=models.ManyToManyField(
                blank=True,
                help_text="Chi ricopre questo ruolo riceve questi ruoli del portale finché lo ricopre.",
                related_name="ruoli_organigramma",
                to="core.accessgroup",
                verbose_name="Ruoli del portale collegati",
            ),
        ),
    ]
