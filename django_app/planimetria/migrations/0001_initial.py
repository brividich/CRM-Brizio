from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Planimetria",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("nome", models.CharField(max_length=200, verbose_name="Nome")),
                (
                    "immagine",
                    models.ImageField(
                        upload_to="planimetria/",
                        verbose_name="Immagine (PNG/JPG)",
                    ),
                ),
                (
                    "attiva",
                    models.BooleanField(
                        default=True,
                        help_text="Una sola planimetria può essere attiva alla volta.",
                        verbose_name="Planimetria attiva",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Planimetria",
                "verbose_name_plural": "Planimetrie",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Reparto",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "planimetria",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reparti",
                        to="planimetria.planimetria",
                        verbose_name="Planimetria",
                    ),
                ),
                (
                    "nome",
                    models.CharField(max_length=200, verbose_name="Nome reparto"),
                ),
                (
                    "colore",
                    models.CharField(
                        default="#3b82f6", max_length=20, verbose_name="Colore"
                    ),
                ),
                (
                    "responsabile",
                    models.CharField(
                        blank=True, max_length=200, verbose_name="Responsabile"
                    ),
                ),
                ("note", models.TextField(blank=True, verbose_name="Note")),
                (
                    "x_perc",
                    models.FloatField(default=10.0, verbose_name="X (%)"),
                ),
                (
                    "y_perc",
                    models.FloatField(default=10.0, verbose_name="Y (%)"),
                ),
                (
                    "w_perc",
                    models.FloatField(default=20.0, verbose_name="Larghezza (%)"),
                ),
                (
                    "h_perc",
                    models.FloatField(default=15.0, verbose_name="Altezza (%)"),
                ),
                ("ordine", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Reparto",
                "verbose_name_plural": "Reparti",
                "ordering": ["ordine", "nome"],
            },
        ),
        migrations.CreateModel(
            name="Macchina",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "reparto",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="macchine",
                        to="planimetria.reparto",
                        verbose_name="Reparto",
                    ),
                ),
                (
                    "nome",
                    models.CharField(max_length=200, verbose_name="Nome macchina"),
                ),
                (
                    "matricola",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="Matricola / Codice",
                    ),
                ),
                (
                    "stato",
                    models.CharField(
                        choices=[
                            ("operativa", "Operativa"),
                            ("manutenzione", "In manutenzione"),
                            ("ferma", "Ferma"),
                            ("dismessa", "Dismessa"),
                        ],
                        default="operativa",
                        max_length=20,
                        verbose_name="Stato",
                    ),
                ),
                (
                    "descrizione",
                    models.TextField(blank=True, verbose_name="Descrizione / Note"),
                ),
                ("ordine", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "Macchina",
                "verbose_name_plural": "Macchine",
                "ordering": ["ordine", "nome"],
            },
        ),
    ]
