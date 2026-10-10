"""Backfill della chiave stabile degli adempimenti di cambio mansione.

``chiave`` = «TIPO:riferimento» (0 per gli adempimenti generici). Se la stessa
assegnazione ha più righe con la stessa chiave (piani rigenerati dopo la
rinomina di un corso o di una visita), resta viva solo la più recente: le
altre passano ``attivo=False`` — e, se ancora aperte, «non più dovute» — prima
che la 0141 crei l'indice unique filtrato.

Reverse: nessuna operazione sui dati; si ferma se esistono adempimenti senza
assegnazione (nati dall'annullamento soft), che lo schema precedente non può
rappresentare.
"""
from django.db import migrations


def avanti(apps, schema_editor):
    Adempimento = apps.get_model("anagrafica", "AdempimentoCambioMansione")
    viste: set[tuple[int, str]] = set()
    righe = (
        Adempimento.objects
        .filter(assegnazione__isnull=False)
        .order_by("assegnazione_id", "-created_at", "-pk")
        .only("pk", "assegnazione_id", "tipo", "riferimento_id", "stato")
    )
    for riga in righe.iterator(chunk_size=500):
        chiave = f"{riga.tipo}:{riga.riferimento_id or 0}"
        campi = {"chiave": chiave}
        if (riga.assegnazione_id, chiave) in viste:
            campi["attivo"] = False
            if riga.stato == "APERTO":
                campi["stato"] = "NON_PIU_DOVUTO"
                campi["chiusura_nota"] = "Duplicato riassorbito dalla migrazione 0140"
        else:
            viste.add((riga.assegnazione_id, chiave))
        Adempimento.objects.filter(pk=riga.pk).update(**campi)


def indietro(apps, schema_editor):
    Adempimento = apps.get_model("anagrafica", "AdempimentoCambioMansione")
    orfani = Adempimento.objects.filter(assegnazione__isnull=True).count()
    if orfani:
        raise RuntimeError(
            f"{orfani} adempimenti di spostamenti annullati non hanno assegnazione: "
            "lo schema precedente (CASCADE, NOT NULL) non li può rappresentare. "
            "Esportarli o eliminarli consapevolmente prima del rollback."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0139_mansioni_rischio"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
