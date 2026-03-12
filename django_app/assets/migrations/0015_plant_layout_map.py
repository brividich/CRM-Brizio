import assets.models

from django.db import migrations, models


def seed_plant_layout_sidebar_button(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.get_or_create(
        code="plant_layout_map",
        defaults={
            "section": "MAIN",
            "label": "Mappa officina",
            "target_url": "django:assets:plant_layout_map",
            "active_match": "/assets/work-machines/map/",
            "is_subitem": True,
            "sort_order": 57,
            "is_visible": True,
        },
    )


def unseed_plant_layout_sidebar_button(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")
    AssetSidebarButton.objects.filter(code="plant_layout_map").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0014_assetlabeltemplate_scope_asset_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlantLayout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("description", models.CharField(blank=True, default="", max_length=255)),
                ("image", models.ImageField(upload_to=assets.models._plant_layout_image_upload_to)),
                ("is_active", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-is_active", "name", "id"],
            },
        ),
        migrations.CreateModel(
            name="PlantLayoutArea",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("reparto_code", models.CharField(blank=True, db_index=True, default="", max_length=120)),
                ("color", models.CharField(default="#2563EB", max_length=7)),
                ("notes", models.CharField(blank=True, default="", max_length=255)),
                ("x_percent", models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ("y_percent", models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ("width_percent", models.DecimalField(decimal_places=2, default=10, max_digits=6)),
                ("height_percent", models.DecimalField(decimal_places=2, default=10, max_digits=6)),
                ("sort_order", models.PositiveIntegerField(default=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("layout", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="areas", to="assets.plantlayout")),
            ],
            options={
                "ordering": ["sort_order", "name", "id"],
            },
        ),
        migrations.CreateModel(
            name="PlantLayoutMarker",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(blank=True, default="", max_length=120)),
                ("x_percent", models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ("y_percent", models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ("is_visible", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("asset", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="plant_layout_markers", to="assets.asset")),
                ("layout", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="markers", to="assets.plantlayout")),
            ],
            options={
                "ordering": ["sort_order", "asset__name", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="plantlayoutmarker",
            constraint=models.UniqueConstraint(fields=("layout", "asset"), name="uniq_plant_layout_marker_layout_asset"),
        ),
        migrations.RunPython(seed_plant_layout_sidebar_button, unseed_plant_layout_sidebar_button),
    ]
