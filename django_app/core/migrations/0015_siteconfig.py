from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_navigationitem_parent_code"),
    ]

    operations = [
        migrations.CreateModel(
            name="SiteConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chiave", models.CharField(db_index=True, max_length=100, unique=True)),
                ("valore", models.TextField(blank=True, default="")),
                ("descrizione", models.CharField(blank=True, default="", max_length=300)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["chiave"],
            },
        ),
    ]
