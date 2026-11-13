from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0225_mpq_requisiti_persona_unici"),
    ]

    operations = [
        migrations.AddField(
            model_name="requisitopersona",
            name="gruppo_alternativo",
            field=models.CharField(
                blank=True, default="", max_length=30, verbose_name="Alternativa (basta una fra…)",
                help_text="Scrivi lo stesso nome su più righe (es. «UT») per dire che basta una di queste. "
                          "Le alternative non diventano obblighi in Formazione e Visite: si vede qui chi manca.",
            ),
        ),
    ]
