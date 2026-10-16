"""Gli OdL nati da un ticket risultano «Da ticket» anche nello storico.

``api_crea_workorder_da_ticket`` creava l'intervento con ``ticket`` valorizzato ma
lasciava ``origin`` al default ``MANUAL``: nessun OdL ha mai avuto origine
``TICKET``. Qui si correggono quelli gia' esistenti (ticket presente e origine
ancora ``MANUAL``). Idempotente: rilanciata non trova piu' nulla da aggiornare.

Reverse: ``noop``. Dopo la migrazione non si distingue piu' un OdL backfillato da
uno creato correttamente con origine ``TICKET``: riportarli a ``MANUAL`` sarebbe
reintrodurre il dato sbagliato, quindi non si annulla.
"""

from django.db import migrations

BATCH = 500


def forwards(apps, schema_editor):
    WorkOrder = apps.get_model("assets", "WorkOrder")
    # Prima si leggono gli id (cursore chiuso), poi si aggiorna a blocchi: su SQL
    # Server un UPDATE con un cursore ancora aperto sulla stessa tabella e' fragile.
    pending = list(
        WorkOrder.objects.filter(ticket_id__isnull=False, origin="MANUAL")
        .order_by("pk")
        .values_list("pk", flat=True)
        .iterator(chunk_size=BATCH)
    )
    total = 0
    for start in range(0, len(pending), BATCH):
        total += WorkOrder.objects.filter(pk__in=pending[start:start + BATCH], origin="MANUAL").update(origin="TICKET")
    if total:
        print(f"\n  [assets 0134] OdL da ticket con origine corretta a «Da ticket»: {total}")


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0133_permessi_dismetti_elimina_asset"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
