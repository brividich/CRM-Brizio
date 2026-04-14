from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0005_register_teams_action"),
    ]

    operations = [
        migrations.CreateModel(
            name="AutomationTableConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action_type", models.CharField(choices=[("insert_record", "Insert record"), ("update_record", "Update record")], max_length=50)),
                ("table_name", models.CharField(max_length=200)),
                ("allowed_fields", models.JSONField(default=list, help_text="Campi scrivibili (lista stringhe)")),
                ("where_fields", models.JSONField(default=list, help_text="Campi usabili nel WHERE (solo update_record)")),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["action_type", "table_name"],
                "unique_together": {("action_type", "table_name")},
            },
        ),
    ]
