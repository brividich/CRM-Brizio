from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0086_asset_prodotto_chimico_alter_asset_asset_type_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkOrderExecutionDay",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("execution_date", models.DateField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "work_order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="execution_days",
                        to="assets.workorder",
                    ),
                ),
            ],
            options={
                "verbose_name": "Giorno esecuzione intervento",
                "verbose_name_plural": "Giorni esecuzione interventi",
                "ordering": ["execution_date", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("work_order", "execution_date"),
                        name="assets_wo_execution_day_unique",
                    ),
                ],
            },
        ),
    ]
