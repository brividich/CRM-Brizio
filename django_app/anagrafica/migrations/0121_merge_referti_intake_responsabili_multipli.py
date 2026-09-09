"""Ricongiunge i due rami 0117 di anagrafica.

Due sessioni parallele hanno numerato entrambe la propria migration `0117`:
`0117_refertointakeconfig_giorni_tolleranza_associazione_and_more` (tolleranza di
associazione dei referti alle visite esistenti, dal ramo referti) e
`0117_traininglesson_docente_ente_and_more`, da cui poi discendono 0118, 0119 e
0120. Mergiando i due rami il grafo si e' ritrovato con due foglie e Django si
rifiuta di applicarlo finche' non gliene si dichiara una sola.

Questa migration non fa nulla: dichiara soltanto che i due rami confluiscono qui.
Nessuna operazione, nessun cambio di schema — le due migration originali restano
quelle che modificano il database, e sono indipendenti fra loro (una tocca
`RefertoIntakeConfig`, l'altra le lezioni di formazione e i responsabili di
reparto/area).
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0117_refertointakeconfig_giorni_tolleranza_associazione_and_more"),
        ("anagrafica", "0120_responsabili_multipli_reparto_area"),
    ]

    operations = []
