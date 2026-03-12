from django.db import migrations, models


def seed_report_definitions(apps, schema_editor):
    AssetReportDefinition = apps.get_model("assets", "AssetReportDefinition")
    defaults = [
        {
            "code": "asset-detail",
            "label": "Scheda asset PDF",
            "description": "Report PDF del singolo asset con riepilogo, documenti e storico.",
            "sort_order": 10,
        },
        {
            "code": "work-machine-maintenance-month",
            "label": "Manutenzioni macchine mese",
            "description": "Report mensile delle manutenzioni pianificate per le macchine di lavoro.",
            "sort_order": 20,
        },
    ]
    for row in defaults:
        AssetReportDefinition.objects.update_or_create(
            code=row["code"],
            defaults={
                "label": row["label"],
                "description": row["description"],
                "sort_order": row["sort_order"],
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0029_assetreporttemplate"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssetReportDefinition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=80, unique=True)),
                ("label", models.CharField(max_length=120)),
                ("description", models.CharField(blank=True, default="", max_length=255)),
                ("sort_order", models.IntegerField(default=100)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["sort_order", "label", "id"],
            },
        ),
        migrations.AlterField(
            model_name="assetreporttemplate",
            name="report_code",
            field=models.SlugField(db_index=True, max_length=80),
        ),
        migrations.RunPython(seed_report_definitions, migrations.RunPython.noop),
    ]
