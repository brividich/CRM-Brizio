from django.db import migrations, models


DEFAULT_LAYOUTS = [
    {
        "context_key": "all",
        "visible_columns": [
            "name",
            "status",
            "category",
            "assigned",
            "last_seen",
            "reparto",
            "serial_number",
            "manufacturer",
            "model",
            "assignment_location",
        ],
        "sort_order": 100,
        "is_customized": False,
    },
    {
        "context_key": "devices",
        "visible_columns": [
            "name",
            "status",
            "category",
            "assigned",
            "reparto",
            "serial_number",
            "manufacturer",
            "model",
            "assignment_location",
            "last_seen",
        ],
        "sort_order": 110,
        "is_customized": False,
    },
    {
        "context_key": "servers",
        "visible_columns": [
            "name",
            "status",
            "category",
            "reparto",
            "serial_number",
            "manufacturer",
            "model",
            "ip",
            "assigned",
            "last_seen",
        ],
        "sort_order": 120,
        "is_customized": False,
    },
    {
        "context_key": "workstations",
        "visible_columns": [
            "name",
            "status",
            "category",
            "assigned",
            "reparto",
            "serial_number",
            "manufacturer",
            "model",
            "ip",
            "last_seen",
        ],
        "sort_order": 130,
        "is_customized": False,
    },
    {
        "context_key": "network",
        "visible_columns": [
            "name",
            "status",
            "category",
            "reparto",
            "serial_number",
            "manufacturer",
            "model",
            "vlan",
            "ip",
            "last_seen",
        ],
        "sort_order": 140,
        "is_customized": False,
    },
    {
        "context_key": "virtual_machines",
        "visible_columns": [
            "name",
            "status",
            "category",
            "assigned",
            "last_seen",
            "reparto",
            "serial_number",
            "manufacturer",
            "model",
            "assignment_location",
        ],
        "sort_order": 150,
        "is_customized": False,
    },
    {
        "context_key": "cctv",
        "visible_columns": [
            "name",
            "status",
            "category",
            "assigned",
            "last_seen",
            "reparto",
            "serial_number",
            "manufacturer",
            "model",
            "assignment_location",
        ],
        "sort_order": 160,
        "is_customized": False,
    },
]


def seed_asset_list_layouts(apps, schema_editor):
    AssetListLayout = apps.get_model("assets", "AssetListLayout")
    for row in DEFAULT_LAYOUTS:
        AssetListLayout.objects.get_or_create(
            context_key=row["context_key"],
            defaults={
                "visible_columns": list(row["visible_columns"]),
                "sort_order": row["sort_order"],
                "is_customized": row["is_customized"],
            },
        )


def unseed_asset_list_layouts(apps, schema_editor):
    AssetListLayout = apps.get_model("assets", "AssetListLayout")
    AssetListLayout.objects.filter(context_key__in=[row["context_key"] for row in DEFAULT_LAYOUTS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0026_assetdetailsectionlayout_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssetListLayout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "context_key",
                    models.CharField(
                        choices=[
                            ("all", "Inventario completo"),
                            ("devices", "Dispositivi"),
                            ("servers", "Server"),
                            ("workstations", "Postazioni di lavoro"),
                            ("network", "Rete"),
                            ("virtual_machines", "Macchine virtuali"),
                            ("cctv", "Videosorveglianza"),
                        ],
                        max_length=32,
                        unique=True,
                    ),
                ),
                ("visible_columns", models.JSONField(blank=True, default=list)),
                ("sort_order", models.IntegerField(default=100)),
                ("is_customized", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
        migrations.RunPython(seed_asset_list_layouts, reverse_code=unseed_asset_list_layouts),
    ]
