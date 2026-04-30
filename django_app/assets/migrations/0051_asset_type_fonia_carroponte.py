from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0050_seed_device_list_sidebar_button"),
    ]

    operations = [
        migrations.AlterField(
            model_name="asset",
            name="asset_type",
            field=models.CharField(
                choices=[
                    ("PC", "PC"),
                    ("NOTEBOOK", "Portatile"),
                    ("SERVER", "Server"),
                    ("VM", "Macchina virtuale"),
                    ("FIREWALL", "Firewall"),
                    ("STAMPANTE", "Stampante"),
                    ("HW", "Dispositivo"),
                    ("FONIA", "Fonia"),
                    ("CNC", "CNC"),
                    ("WORK_MACHINE", "Macchina di lavoro"),
                    ("CARROPONTE", "Carroponte"),
                    ("CCTV", "Videosorveglianza"),
                    ("OTHER", "Altro"),
                ],
                default="OTHER",
                max_length=20,
            ),
        ),
    ]
