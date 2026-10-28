"""«Assets» diviso in quattro moduli della matrice ruoli (27/10/2026).

Inventario (``assets``), Manutenzione (``assets_manutenzione``), Ordini di lavoro
(``assets_odl``), Verifiche e scadenze (``assets_verifiche``): ognuno con le sue
azioni e il suo ambito «Propri / del team / Tutti».

Ogni ruolo riceve sui tre moduli nuovi le stesse celle che ha oggi su «assets»
(stesso ambito, stesso consentito/negato, stessa nota): al deploy nessuno guadagna
né perde accessi. Le Impostazioni restano all'inventario. I permessi di pagina non
cambiano: le celle uguali accendono gli stessi permessi.
"""
from django.db import migrations

SOTTOMODULI = ("assets_manutenzione", "assets_odl", "assets_verifiche")


def avanti(apps, schema_editor):
    Cella = apps.get_model("core", "RuoloPermessoModulo")
    esistenti = set(Cella.objects.filter(modulo__in=SOTTOMODULI).values_list("ruolo_id", "modulo", "azione"))
    nuove = []
    for cella in Cella.objects.filter(modulo="assets").exclude(azione="impostazioni"):
        for sotto in SOTTOMODULI:
            if (cella.ruolo_id, sotto, cella.azione) in esistenti:
                continue
            nuove.append(Cella(
                ruolo_id=cella.ruolo_id, modulo=sotto, azione=cella.azione,
                ambito=cella.ambito, consentito=cella.consentito, note=cella.note,
            ))
    # Una riga per volta: su SQL Server l'INSERT a lotti rompe i savepoint delle migrazioni.
    for cella in nuove:
        cella.save()


def indietro(apps, schema_editor):
    apps.get_model("core", "RuoloPermessoModulo").objects.filter(modulo__in=SOTTOMODULI).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0098_impostazioni_solo_pagina_impostazioni")]
    operations = [migrations.RunPython(avanti, indietro)]
