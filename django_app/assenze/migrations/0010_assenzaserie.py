from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assenze", "0009_outlook_capo"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssenzaSerie",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("assenza_id", models.IntegerField(unique=True)),
                ("capofila_id", models.IntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Giorno di un permesso ripetuto",
                "verbose_name_plural": "Giorni dei permessi ripetuti",
                "ordering": ["capofila_id", "assenza_id"],
            },
        ),
    ]
