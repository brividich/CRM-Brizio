from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_notifica_auditlog"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserExtraInfo",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_user_id", models.IntegerField(db_index=True, unique=True)),
                ("caporeparto", models.CharField(blank=True, default="", max_length=200)),
                ("macchina", models.CharField(blank=True, default="", help_text="Macchina di utilizzo principale", max_length=200)),
                ("telefono", models.CharField(blank=True, default="", max_length=50)),
                ("cellulare", models.CharField(blank=True, default="", max_length=50)),
                ("note", models.TextField(blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
