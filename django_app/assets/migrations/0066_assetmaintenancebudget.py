from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0065_workorder_meter_value_at_close"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssetMaintenanceBudget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year", models.PositiveSmallIntegerField(db_index=True)),
                ("budget_eur", models.DecimalField(decimal_places=2, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "asset_category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="maintenance_budgets",
                        to="assets.assetcategory",
                    ),
                ),
            ],
            options={
                "verbose_name": "Budget manutenzione categoria",
                "verbose_name_plural": "Budget manutenzione categoria",
                "ordering": ["-year", "asset_category"],
                "unique_together": {("asset_category", "year")},
            },
        ),
    ]
