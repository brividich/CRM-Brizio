"""Registro OFI: collegamento della voce al processo del catalogo SGI.

Aggiunge ``RegistroOFI.processo_sgi`` e lo valorizza sulle voci esistenti quando il
testo «Processo/area» indica un solo processo del catalogo (codice, nome o codice in
testa). Le voci con testo ambiguo o libero restano come sono.
"""
import django.db.models.deletion
from django.db import migrations, models


def collega_esistenti(apps, schema_editor):
    from gestione_specifiche.registro_ofi import processo_da_testo

    Processo = apps.get_model("sistema_gestione", "Processo")
    RegistroOFI = apps.get_model("gestione_specifiche", "RegistroOFI")
    processi = list(Processo.objects.only("pk", "codice", "nome"))
    if not processi:
        return
    per_testo = {}
    for pk, testo in (RegistroOFI.objects.filter(processo_sgi__isnull=True).exclude(processo="")
                      .values_list("pk", "processo")):
        trovato = processo_da_testo(testo, processi)
        if trovato is not None:
            per_testo.setdefault(trovato.pk, []).append(pk)
    for processo_id, pks in per_testo.items():
        for i in range(0, len(pks), 500):  # SQL Server: massimo 2100 parametri per query
            RegistroOFI.objects.filter(pk__in=pks[i:i + 500]).update(processo_sgi_id=processo_id)


class Migration(migrations.Migration):

    dependencies = [
        ("gestione_specifiche", "0015_registroofi_responsabile_eventi_allegati"),
        ("sistema_gestione", "0018_audit_esterni_piano_inviato"),
    ]

    operations = [
        migrations.AddField(
            model_name="registroofi",
            name="processo_sgi",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="voci_ofi", to="sistema_gestione.processo",
                verbose_name="Processo del catalogo SGI",
            ),
        ),
        migrations.RunPython(collega_esistenti, migrations.RunPython.noop),
    ]
