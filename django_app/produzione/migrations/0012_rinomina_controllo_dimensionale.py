from django.db import migrations

VECCHIO, NUOVO = "Ordini di produzione", "Controllo dimensionale"


def rinomina(apps, schema_editor):
    """Il modulo si chiama «Controllo dimensionale»: voce di menu e nomi dei permessi già creati (i bootstrap non
    toccano le etichette esistenti). Una voce di menu rinominata a mano resta com'è."""
    NavigationItem = apps.get_model("core", "NavigationItem")
    PermissionDefinition = apps.get_model("core", "PermissionDefinition")
    NavigationItem.objects.filter(code="produzione_op", label=VECCHIO).update(label=NUOVO)
    for p in PermissionDefinition.objects.filter(module="produzione", label__startswith=VECCHIO):
        p.label = NUOVO + p.label[len(VECCHIO):]
        p.save(update_fields=["label"])


class Migration(migrations.Migration):

    dependencies = [("produzione", "0011_finestra_ordine"), ("core", "0094_permesso_le_mie_assenze")]

    operations = [migrations.RunPython(rinomina, migrations.RunPython.noop)]
