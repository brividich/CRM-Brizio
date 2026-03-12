from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_siteconfig"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoginBanner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("testo", models.TextField()),
                ("tipo", models.CharField(
                    choices=[
                        ("info", "Informazione (blu)"),
                        ("warning", "Attenzione (giallo)"),
                        ("danger", "Errore / blocco (rosso)"),
                        ("success", "Successo / ok (verde)"),
                    ],
                    default="info",
                    max_length=20,
                )),
                ("ordine", models.IntegerField(default=100)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["ordine", "id"],
            },
        ),
    ]
