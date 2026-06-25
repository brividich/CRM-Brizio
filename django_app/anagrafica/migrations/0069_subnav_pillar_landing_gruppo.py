from django.db import migrations, models


class Migration(migrations.Migration):
    """Topbar anagrafica — capacità «pilastro» (Proposta A).

    - SubnavCategoriaAnagrafica: ``landing_url_type`` + ``landing_url_value`` →
      cliccando il testo della categoria si naviga alla dashboard del sotto-modulo,
      il caret/hover apre comunque il dropdown.
    - SubnavLinkAnagrafica: ``gruppo`` → intestazione di sezione dentro il dropdown
      (mega-menu a colonne).
    """

    dependencies = [
        ("anagrafica", "0068_cartella_targeting"),
    ]

    operations = [
        migrations.AddField(
            model_name="subnavcategoriaanagrafica",
            name="landing_url_type",
            field=models.CharField(
                choices=[("named", "URL Django (nome view)"), ("raw", "URL diretto (path o esterno)")],
                default="named",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="subnavcategoriaanagrafica",
            name="landing_url_value",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Nome view Django o path/URL della dashboard del sotto-modulo. "
                          "Vuoto = la categoria è solo un dropdown senza pagina propria.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="subnavlinkanagrafica",
            name="gruppo",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Intestazione di sezione dentro il dropdown (facoltativa). "
                          "Link con lo stesso gruppo vengono raggruppati in colonna nel mega-menu.",
                max_length=40,
            ),
        ),
    ]
