from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("contatori", "0012_sondasnmp_profilo_colonna")]
    operations = [
        migrations.AddField(
            model_name="rilevazionesnmp", name="dati_stampante",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
