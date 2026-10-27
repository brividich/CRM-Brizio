"""Assenze: le Impostazioni hanno un'azione loro nella matrice dei ruoli.

Prima le apriva «Chiudere / gestire» insieme a tutta l'amministrazione del modulo
(``assenze.assenze.manage`` e ``legacy.assenze.admin_assenze``): non si poteva
dare la gestione delle assenze senza dare anche le Impostazioni. Ora le accende
solo l'azione propria «impostazioni» (vedi ``assenze/registro_permessi.py``).

Per non togliere l'accesso a nessuno, ogni ruolo che ha una cella «gestire»
sulle assenze riceve la stessa cella su «impostazioni»: poi si spegne dalla
matrice dove non serve.
"""
from django.db import migrations

MODULO = "assenze"
DA = "gestire"
A = "impostazioni"
NOTA = "[CORE_0096] copiata da gestire"


def avanti(apps, schema_editor):
    Cella = apps.get_model("core", "RuoloPermessoModulo")
    gia = set(Cella.objects.filter(modulo=MODULO, azione=A).values_list("ruolo_id", flat=True))
    for cella in Cella.objects.filter(modulo=MODULO, azione=DA).exclude(ruolo_id__in=gia):
        Cella.objects.create(
            ruolo_id=cella.ruolo_id, modulo=MODULO, azione=A,
            ambito=cella.ambito, consentito=cella.consentito, note=NOTA,
        )


def indietro(apps, schema_editor):
    apps.get_model("core", "RuoloPermessoModulo").objects.filter(modulo=MODULO, azione=A, note=NOTA).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0095_postazione_asset")]
    operations = [migrations.RunPython(avanti, indietro)]
