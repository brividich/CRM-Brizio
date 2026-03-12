from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_userdashboardlayout"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmployeeBoardConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_user_id", models.IntegerField(db_index=True, unique=True)),
                ("layout", models.JSONField(blank=True, default=list)),
                ("widget_configs", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
