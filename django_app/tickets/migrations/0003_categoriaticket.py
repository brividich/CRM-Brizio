from django.db import migrations, models


INITIAL_CATEGORIE = [
    # (tipo, codice, etichetta, ordine)
    ("IT",  "PC",          "PC / Notebook",                 10),
    ("IT",  "SERVER",      "Server",                        20),
    ("IT",  "STAMPANTE",   "Stampante / Scanner",           30),
    ("IT",  "RETE",        "Rete / Connettività",           40),
    ("IT",  "SOFTWARE",    "Software / Sistema Operativo",  50),
    ("IT",  "TELEFONIA",   "Telefonia",                     60),
    ("IT",  "ALTRO_IT",    "Altro IT",                      70),
    ("MAN", "CNC",         "Macchina CNC",                  10),
    ("MAN", "MACCHINARIO", "Macchinario generico",          20),
    ("MAN", "STRUTTURALE", "Strutturale / Edificio",        30),
    ("MAN", "GENERICA",    "Generica",                      40),
    ("MAN", "CHIAMATA",    "Intervento a chiamata",         50),
    ("MAN", "ALTRO_MAN",   "Altro Manutenzione",            60),
]


def seed_categorie(apps, schema_editor):
    CategoriaTicket = apps.get_model("tickets", "CategoriaTicket")
    for tipo, codice, etichetta, ordine in INITIAL_CATEGORIE:
        CategoriaTicket.objects.get_or_create(
            codice=codice,
            defaults={"tipo": tipo, "etichetta": etichetta, "ordine": ordine, "attivo": True},
        )


def unseed_categorie(apps, schema_editor):
    pass  # non rimuovere dati in rollback — la tabella viene droppata dal DeleteModel


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0002_private_storage"),
    ]

    operations = [
        migrations.CreateModel(
            name="CategoriaTicket",
            fields=[
                ("id",        models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("tipo",      models.CharField(choices=[("IT", "Ticket IT"), ("MAN", "Ticket Manutenzione")], db_index=True, max_length=5)),
                ("codice",    models.CharField(max_length=30, unique=True)),
                ("etichetta", models.CharField(max_length=100)),
                ("ordine",    models.PositiveIntegerField(default=0)),
                ("attivo",    models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "Categoria ticket",
                "verbose_name_plural": "Categorie ticket",
                "ordering": ["tipo", "ordine", "etichetta"],
            },
        ),
        migrations.RunPython(seed_categorie, unseed_categorie),
    ]
