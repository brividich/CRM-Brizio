from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0019_taskroledefinition_taskcategory_role_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskcategoryfield",
            name="asset_type_filter",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Solo per field_type=asset. CSV di codici asset_type "
                    "(es. 'CNC,WORK_MACHINE'). Vuoto = tutti i tipi."
                ),
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="taskcategoryfield",
            name="asset_category_filter",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Solo per field_type=asset. CSV di ID AssetCategory. "
                    "Vuoto = tutte le categorie."
                ),
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="taskimpostazioni",
            name="asset_conflict_check_enabled",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Se attivo, all'assegnazione di un asset mostra OdL, "
                    "verifiche, ticket e attivita in conflitto nella finestra "
                    "temporale."
                ),
                verbose_name="Verifica disponibilita asset",
            ),
        ),
        migrations.AddField(
            model_name="taskimpostazioni",
            name="asset_conflict_block",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Se attivo, impedisce di salvare l'attivita quando l'asset "
                    "selezionato ha conflitti rilevanti (OdL aperto, asset in "
                    "riparazione, sovrapposizione con altra attivita)."
                ),
                verbose_name="Blocca il salvataggio su conflitto asset",
            ),
        ),
    ]
