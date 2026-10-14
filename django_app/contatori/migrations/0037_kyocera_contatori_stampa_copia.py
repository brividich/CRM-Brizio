"""Kyocera: contatori contrattuali = stampa + copia, per colore e formato.

La tabella 1347.42.3.1.6.1 e' indicizzata <colore>.<funzione>.<formato>:
colore 1 = tutti, 2 = B/N, 3 = colore; funzione 1 = stampa, 2 = copia;
formato 1 = A3, 3 = A4. La 0023 la leggeva come <funzione=totale>.<colore>.<formato>:
"A4/A3 BN" erano in realta' tutte le stampe (anche a colori) e "A4/A3 colore"
tutte le copie. Verificato sul walk della TASKalfa 5054ci UT confrontato con il
registro Copylab di settembre 2026 (scarti di pochi giorni di utilizzo).

Ogni contatore diventa la somma di due OID ("stampa+copia", solo GET).
I totali 1347.42.3.1.1.1.1.{1,2} sono stampe e copie, non B/N e colore.
Le letture gia' salvate non vengono toccate: vanno corrette a mano.
"""
from django.core.validators import RegexValidator
from django.db import migrations, models

T = "1.3.6.1.4.1.1347.42.3.1.6.1"
VECCHI = {
    "a4_bn": f"{T}.1.1.3",
    "a3_bn": f"{T}.1.1.1",
    "a4_col": f"{T}.1.2.3",
    "a3_col": f"{T}.1.2.1",
}
NUOVI = {
    "a4_bn": ("A4 BN Kyocera (stampa+copia)", f"{T}.2.1.3+{T}.2.2.3"),
    "a3_bn": ("A3 BN Kyocera (stampa+copia)", f"{T}.2.1.1+{T}.2.2.1"),
    "a4_col": ("A4 colore Kyocera (stampa+copia)", f"{T}.3.1.3+{T}.3.2.3"),
    "a3_col": ("A3 colore Kyocera (stampa+copia)", f"{T}.3.1.1+{T}.3.2.1"),
}
TOTALI = {
    "1.3.6.1.4.1.1347.42.3.1.1.1.1.1": ("Totale B/N", "Totale stampe"),
    "1.3.6.1.4.1.1347.42.3.1.1.1.1.2": ("Totale colore", "Totale copie"),
}
FONTE = ("walk TASKalfa 5054ci UT confrontato con registro Copylab 09/2026: "
         "tabella <colore>.<funzione>.<formato>, B/N e colore = stampa + copia")
FONTE_0023 = ("lettura TASKalfa 5054ci/3554ci (2026-10-05): per formato, somma coincidente "
              "con i totali B/N e colore")

VALIDATOR = RegexValidator(
    regex=r"^\d+(?:\.\d+)+(?:\+\d+(?:\.\d+)+)*$",
    message="Inserisci un OID numerico puntato (es. 1.3.6.1.2.1.1.3.0) "
            "oppure piu' OID uniti da + da sommare (solo modalita GET).",
)


def _applica(apps, mappa, totali_idx, fonte):
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")
    Probe = apps.get_model("contatori", "SondaSNMP")
    kyocera = apps.get_model("contatori", "ProfiloSNMP").objects.filter(slug="kyocera").first()
    if kyocera is None:
        return
    for chiave, (nome, oid) in mappa.items():
        colonna = Column.objects.filter(profilo=kyocera, contatore_mfc=chiave).first()
        if colonna is None:
            continue
        Column.objects.filter(pk=colonna.pk).update(nome=nome, oid=oid, modalita="GET", fonte=fonte)
        Probe.objects.filter(profilo_colonna=colonna).update(nome=nome, oid=oid, modalita="GET")
    for oid, nomi in TOTALI.items():
        nome = nomi[totali_idx]
        Column.objects.filter(profilo=kyocera, oid=oid).update(nome=nome)
        Probe.objects.filter(profilo_colonna__profilo=kyocera, oid=oid).update(nome=nome)


def forwards(apps, schema_editor):
    _applica(apps, NUOVI, 1, FONTE)


def backwards(apps, schema_editor):
    vecchi = {
        "a4_bn": ("A4 BN Kyocera", VECCHI["a4_bn"]),
        "a3_bn": ("A3 BN Kyocera", VECCHI["a3_bn"]),
        "a4_col": ("A4 colore Kyocera", VECCHI["a4_col"]),
        "a3_col": ("A3 colore Kyocera", VECCHI["a3_col"]),
    }
    _applica(apps, vecchi, 0, FONTE_0023)


class Migration(migrations.Migration):
    dependencies = [("contatori", "0036_acl_collega_asset")]

    operations = [
        migrations.AlterField(
            model_name="colonnaprofilosnmp", name="oid",
            field=models.CharField(max_length=255, validators=[VALIDATOR]),
        ),
        migrations.AlterField(
            model_name="sondasnmp", name="oid",
            field=models.CharField(max_length=255, validators=[VALIDATOR]),
        ),
        migrations.RunPython(forwards, backwards),
    ]
