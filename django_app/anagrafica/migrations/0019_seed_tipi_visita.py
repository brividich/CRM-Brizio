"""Seed catalogo TipoVisitaMedica.

Inserisce le tipologie di visita più comuni in ambito Testo Unico 81/08.
Tutte create con ``is_active=True`` e ``obbligatoria=False``:
l'utente le abilita e collega ai ruoli operativi da admin/UI prima dell'uso.
"""

from django.db import migrations


SEED = [
    {
        "nome": "Visita medica generica art. 41",
        "descrizione": "Sorveglianza sanitaria generale ai sensi dell'art. 41 D.Lgs. 81/2008.",
        "durata_mesi": 12,
    },
    {
        "nome": "Visita per uso videoterminali",
        "descrizione": "Sorveglianza sanitaria per lavoratori addetti a videoterminali (Titolo VII).",
        "durata_mesi": 60,
    },
    {
        "nome": "Visita per movimentazione manuale carichi",
        "descrizione": "Sorveglianza per movimentazione manuale dei carichi (Titolo VI).",
        "durata_mesi": 24,
    },
    {
        "nome": "Visita per esposizione a rumore",
        "descrizione": "Sorveglianza per esposizione al rumore oltre i valori d'azione (Titolo VIII Capo II).",
        "durata_mesi": 12,
    },
    {
        "nome": "Visita per uso DPI di III categoria",
        "descrizione": "Sorveglianza per uso DPI di III categoria (es. anticaduta, autorespiratori).",
        "durata_mesi": 12,
    },
    {
        "nome": "Visita per lavori in quota",
        "descrizione": "Sorveglianza per lavori in quota con rischio di caduta dall'alto.",
        "durata_mesi": 12,
    },
]


def seed_forward(apps, schema_editor):
    TipoVisitaMedica = apps.get_model("anagrafica", "TipoVisitaMedica")
    for entry in SEED:
        TipoVisitaMedica.objects.get_or_create(
            nome=entry["nome"],
            defaults={
                "descrizione": entry["descrizione"],
                "durata_mesi": entry["durata_mesi"],
                "obbligatoria": False,
                "is_active": True,
            },
        )


def seed_reverse(apps, schema_editor):
    TipoVisitaMedica = apps.get_model("anagrafica", "TipoVisitaMedica")
    nomi = [entry["nome"] for entry in SEED]
    TipoVisitaMedica.objects.filter(nome__in=nomi).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0018_documentodipendente_visitamedica"),
    ]

    operations = [
        migrations.RunPython(seed_forward, seed_reverse),
    ]
