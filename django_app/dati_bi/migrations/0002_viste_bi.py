"""Crea le viste SQL bi_* per Power BI (dati_bi.viste).

Dipende dalle ultime migrazioni delle app lette dalle viste. Una modifica
futura alle viste va in una nuova migrazione che richiama ``crea_viste``
(``CREATE OR ALTER`` su SQL Server).
"""
from django.db import migrations


def crea(apps, schema_editor):
    from dati_bi.viste import crea_viste

    crea_viste(schema_editor.connection)


def elimina(apps, schema_editor):
    from dati_bi.viste import elimina_viste

    elimina_viste(schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [
        ("dati_bi", "0001_iniziale"),
        ("assets", "0142_ricambi_acl_menu"),
        ("tickets", "0012_allegato_validazione"),
        ("dpi", "0011_magazzino_movimenti"),
        ("core", "0083_notifiche_canali_push"),
        ("anagrafica", "0185_struttura_mansionario_acl"),
    ]

    operations = [migrations.RunPython(crea, elimina)]
