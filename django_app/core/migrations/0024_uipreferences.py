import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Crea UserUiPreference: preferenze interfaccia per-utente (nav_mode, font_scale, sidebar)."""

    dependencies = [
        ("core", "0023_data_module_categories"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserUiPreference",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "nav_mode",
                    models.CharField(
                        choices=[("top", "Barra superiore"), ("side", "Barra laterale")],
                        default="top",
                        max_length=4,
                    ),
                ),
                (
                    "font_scale",
                    models.CharField(
                        choices=[
                            ("small", "Piccolo"),
                            ("normal", "Normale"),
                            ("large", "Grande"),
                            ("xl", "Molto grande"),
                        ],
                        default="normal",
                        max_length=6,
                    ),
                ),
                ("sidebar_collapsed", models.BooleanField(default=False)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ui_prefs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Preferenza interfaccia",
                "verbose_name_plural": "Preferenze interfaccia",
                "db_table": "core_useruipreference",
            },
        ),
    ]
