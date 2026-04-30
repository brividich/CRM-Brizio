from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0024_taskcategory_is_machine_work"),
    ]

    operations = [
        migrations.CreateModel(
            name="MeetingRoom",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=120, unique=True, verbose_name="Nome sala")),
                ("note", models.TextField(blank=True, default="", verbose_name="Note")),
                ("ordine", models.PositiveSmallIntegerField(default=0, verbose_name="Ordine")),
            ],
            options={
                "verbose_name": "Sala riunioni",
                "verbose_name_plural": "Sale riunioni",
                "ordering": ["ordine", "nome"],
            },
        ),
    ]
