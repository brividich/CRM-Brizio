"""«Le mie azioni» diventa «Le mie attività KICK-OFF» nella barra del modulo.

Nel KICK-OFF si parla di attività, non di azioni. Il nome porta «KICK-OFF»
perché «Le mie attività» è già la pagina del portale che raccoglie tutti i
moduli. Cambia solo l'etichetta rimasta al valore di origine: una voce
rinominata a mano dall'amministratore non viene toccata.
"""
from django.db import migrations

CODE = "tasks-sub-mie-azioni"
PRIMA = "Le mie azioni"
DOPO = "Le mie attività KICK-OFF"


def rinomina(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=CODE, label=PRIMA).update(label=DOPO)


def ripristina(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=CODE, label=DOPO).update(label=PRIMA)


class Migration(migrations.Migration):
    dependencies = [("core", "0115_postazione_inattivita_2_ore")]
    operations = [migrations.RunPython(rinomina, ripristina)]
