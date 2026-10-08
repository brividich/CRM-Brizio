"""Seed del glossario: ~85 termini in «bozza» (fonte=seed), da validare in Qualità.

Idempotente: un termine già presente (stesso termine e categoria) non viene
toccato; una variante la cui chiave esiste già viene saltata. Reverse: elimina
solo i termini seed ancora in bozza (quelli già validati o modificati restano).
"""

from django.db import migrations


def _chiave(testo):
    from glossario_tecnico.chiave import normalizza_chiave

    return normalizza_chiave(testo)


def seed(apps, schema_editor):
    from glossario_tecnico.seed_data import TERMINI

    Termine = apps.get_model("glossario_tecnico", "Termine")
    Variante = apps.get_model("glossario_tecnico", "Variante")
    chiavi = set(Variante.objects.values_list("chiave", flat=True))
    for dati in TERMINI:
        termine, creato = Termine.objects.get_or_create(
            termine=dati["termine"], categoria=dati["categoria"],
            defaults={
                "termine_en": dati["termine_en"], "definizione": dati["definizione"],
                "simbolo": dati["simbolo"], "esempio_disegno": dati["esempio_disegno"],
                "norma_rif": dati["norma_rif"], "note_interne": dati["note_interne"],
                "stato": "bozza", "fonte": "seed",
            },
        )
        if not creato:
            continue
        for tipo, testo, lingua in dati["varianti"]:
            chiave = _chiave(testo)
            if not chiave or chiave in chiavi:
                continue
            Variante.objects.create(termine=termine, testo=testo, tipo=tipo, lingua=lingua or "", chiave=chiave)
            chiavi.add(chiave)


def unseed(apps, schema_editor):
    Termine = apps.get_model("glossario_tecnico", "Termine")
    Termine.objects.filter(fonte="seed", stato="bozza").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("glossario_tecnico", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
