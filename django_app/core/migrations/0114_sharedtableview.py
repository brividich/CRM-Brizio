"""Viste comuni delle tabelle (menu «Viste ▾»): uguali per tutti, una predefinita per tabella."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0113_tasks_subnav_cruscotto"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SharedTableView",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("table_id", models.CharField(db_index=True, max_length=100)),
                ("nome", models.CharField(max_length=60)),
                ("state_json", models.JSONField(blank=True, default=dict)),
                ("predefinita", models.BooleanField(default=False)),
                ("aggiornata_il", models.DateTimeField(auto_now=True)),
                ("aggiornata_da", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "verbose_name": "Vista comune tabella",
                "verbose_name_plural": "Viste comuni tabelle",
                "db_table": "core_sharedtableview",
                "ordering": ["table_id", "nome"],
                "unique_together": {("table_id", "nome")},
            },
        ),
    ]
