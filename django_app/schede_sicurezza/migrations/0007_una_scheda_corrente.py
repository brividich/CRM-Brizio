"""Una sola versione corrente per prodotto (audit H2).

Prima del vincolo si sistemano i dati: se un prodotto ha piu' versioni correnti resta corrente
la piu' recente per data di caricamento (a parita', id maggiore), le altre tornano storiche.
"""

from django.db import migrations, models


def una_corrente_per_prodotto(apps, schema_editor):
    SchedaSicurezza = apps.get_model("schede_sicurezza", "SchedaSicurezza")
    correnti = (SchedaSicurezza.objects.filter(is_corrente=True)
                .order_by("prodotto_id", "-data_caricamento", "-pk")
                .values_list("pk", "prodotto_id"))
    visti = set()
    da_togliere = []
    for pk, prodotto_id in correnti:
        if prodotto_id in visti:
            da_togliere.append(pk)
        else:
            visti.add(prodotto_id)
    for i in range(0, len(da_togliere), 500):  # limite parametri SQL Server
        SchedaSicurezza.objects.filter(pk__in=da_togliere[i:i + 500]).update(is_corrente=False)


class Migration(migrations.Migration):

    dependencies = [
        ('schede_sicurezza', '0006_impostazioni_etichetta_dpi'),
    ]

    operations = [
        migrations.RunPython(una_corrente_per_prodotto, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='schedasicurezza',
            constraint=models.UniqueConstraint(condition=models.Q(('is_corrente', True)), fields=('prodotto',), name='ss_una_scheda_corrente'),
        ),
    ]
