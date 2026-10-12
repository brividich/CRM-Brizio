from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("contatori", "0030_acl_wizard_generici")]

    operations = [
        migrations.AddField(
            model_name="fattura",
            name="dettaglio",
            field=models.CharField(
                choices=[("FORMATO", "A4/A3 B/N e colore"), ("TOTALI", "Solo totali B/N e colore")],
                default="FORMATO", max_length=8, verbose_name="Letture in fattura",
                help_text="Copylab fattura solo i totali B/N e colore: si confrontano con A4+A3 interni."),
        ),
    ]
