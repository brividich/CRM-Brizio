from django.db import migrations, models


class Migration(migrations.Migration):
    """Finestra di riferimento degli indici (Impostazioni) e ordine dei report per giorno, ora del file, lettura."""

    dependencies = [("produzione", "0010_quota_capacita")]

    operations = [
        migrations.AddField(
            model_name="impostazioniquotecmm",
            name="finestra",
            field=models.PositiveSmallIntegerField(
                choices=[(30, "Ultimi 30 pezzi"), (50, "Ultimi 50 pezzi"), (100, "Ultimi 100 pezzi")], default=30,
                help_text="La stessa finestra in catalogo, scheda P/N, report, Quote CMM, Analisi quote e PDF di capacità.",
                verbose_name="Pezzi su cui si calcolano Cpk e Ppk"),
        ),
        migrations.AlterModelOptions(
            name="reportcmm",
            options={"ordering": ["-data", "-modificato", "-id"], "verbose_name": "Report CMM", "verbose_name_plural": "Report CMM"},
        ),
        migrations.AlterField(
            model_name="articolopn",
            name="quote_non_capaci",
            field=models.PositiveIntegerField(default=0, help_text="Quote «al limite» o «non capaci» (spc.verdetto) sulla finestra di riferimento."),
        ),
    ]
