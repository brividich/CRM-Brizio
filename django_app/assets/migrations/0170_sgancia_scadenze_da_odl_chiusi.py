"""Manutenzioni aperte rimaste agganciate a un OdL chiuso o annullato: tornano da pianificare.

Prima la chiusura di un OdL con manutenzioni non registrate le lasciava collegate
all'intervento chiuso: restavano dovute ma non si potevano piu' mettere in un altro
OdL ne' comparivano fra le «da pianificare». La chiusura ora le sgancia; qui si
sistemano quelle gia' bloccate. Solo dati, nessuna modifica di schema.
"""

from django.db import migrations


def sgancia(apps, schema_editor):
    MaintenanceOccurrence = apps.get_model("assets", "MaintenanceOccurrence")
    MaintenanceOccurrence.objects.filter(
        status="OPEN", work_order__status__in=["DONE", "CANCELED"]
    ).update(work_order=None, execution_day=None)


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0169_scadenze_spostate_nei_piani"),
    ]

    operations = [
        migrations.RunPython(sgancia, migrations.RunPython.noop),
    ]
