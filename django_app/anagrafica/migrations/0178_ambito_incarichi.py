"""Ambito «Incarichi» per l'organigramma (modello dei permessi del 15/10/2026).

Gli incarichi che si sommano alla posizione della persona e non stanno negli
organigrammi 45001 o 27001: gestione del personale, gestione della formazione,
auditor interni, docenti. Non alimenta il «Ruolo aziendale» della scheda.
Nessun ruolo viene creato o classificato: li crea e li assegna una persona.
"""
from django.db import migrations

NOME = "Incarichi"


def semina(apps, schema_editor):
    AmbitoRuolo = apps.get_model("anagrafica", "AmbitoRuolo")
    AmbitoRuolo.objects.get_or_create(
        nome=NOME,
        defaults={
            "icona": "📌",
            "colore": "#b45309",
            "ordine": 50,
            "alimenta_scheda": False,
            "descrizione": (
                "Incarichi che si aggiungono alla posizione: gestione del personale, gestione della "
                "formazione, auditor interni, docenti. Collegati ai ruoli del portale danno i permessi "
                "dell'incarico."
            ),
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0177_ruolo_profili_permessi"),
    ]

    operations = [
        migrations.RunPython(semina, migrations.RunPython.noop),
    ]
