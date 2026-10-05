"""Contatori contrattuali Kyocera (A4/A3, B/N e colore) verificati sulla flotta.

Tabella KYOCERA 1347.42.3.1.6.1.<funzione>.<colore>.<formato>: funzione 1 = totale
(2 stampa + 3 copia), colore 1 = B/N e 2 = colore, formato con i nomi della
tabella 1347.42.2.1.1.1.2.1 (1 = A3, 3 = A4). Letta il 2026-10-05 su TASKalfa
5054ci e 3554ci: A3 + A4 (+ banner) coincide al foglio con i totali B/N e colore
1347.42.3.1.1.1.1.{1,2}, che di conseguenza passano da "da confermare" a verificati.
"""
from decimal import Decimal

from django.db import migrations

FONTE = ("lettura TASKalfa 5054ci/3554ci (2026-10-05): per formato, somma coincidente "
         "con i totali B/N e colore")
FONTE_DA_CONFERMARE = (
    "dedotto da walk TASKalfa 5054ci/3554ci: coerente con la somma per funzione; "
    "confermare sul pannello contatori prima di attivare"
)
D = Decimal
TABELLA = "1.3.6.1.4.1.1347.42.3.1.6.1.1"
CONTATORI = [
    ("a4_bn", "A4 BN Kyocera", f"{TABELLA}.1.3"),
    ("a3_bn", "A3 BN Kyocera", f"{TABELLA}.1.1"),
    ("a4_col", "A4 colore Kyocera", f"{TABELLA}.2.3"),
    ("a3_col", "A3 colore Kyocera", f"{TABELLA}.2.1"),
]
TOTALI = {
    "1.3.6.1.4.1.1347.42.3.1.1.1.1.1": "Totale B/N",
    "1.3.6.1.4.1.1347.42.3.1.1.1.1.2": "Totale colore",
}


def forwards(apps, schema_editor):
    Profile = apps.get_model("contatori", "ProfiloSNMP")
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")
    Device = apps.get_model("contatori", "DispositivoSNMP")
    Probe = apps.get_model("contatori", "SondaSNMP")
    Machine = apps.get_model("contatori", "Macchina")

    kyocera = Profile.objects.filter(slug="kyocera").first()
    if kyocera is None:
        return
    columns = []
    for order, (chiave, nome, oid) in enumerate(CONTATORI, 1):
        defaults = {
            "nome": nome, "tipo_valore": "NUMERO", "modalita": "GET", "aggregazione": "PRIMO",
            "unita": "copie", "fattore": D("1"), "contatore_mfc": chiave,
            "verificata": True, "fonte": FONTE, "ordine": order, "attiva": True,
        }
        # Il profilo può già avere questa chiave MFC associata a un OID provvisorio
        # (per esempio creato dalla UI). Cerca anche per chiave, così l'upsert non
        # tenta di duplicare l'indice univoco (profilo, contatore_mfc).
        column = Column.objects.filter(profilo=kyocera, oid=oid).first()
        keyed_column = Column.objects.filter(
            profilo=kyocera, contatore_mfc=chiave,
        ).first()
        if column is None:
            column = keyed_column
        elif keyed_column is not None and keyed_column.pk != column.pk:
            # Mantiene la riga già presente per l'OID canonico e libera la chiave
            # sulla vecchia riga; i suoi dati e le sonde collegate restano intatti.
            keyed_column.contatore_mfc = ""
            keyed_column.save(update_fields=["contatore_mfc"])

        if column is None:
            column = Column.objects.create(profilo=kyocera, oid=oid, **defaults)
        else:
            Column.objects.filter(pk=column.pk).update(oid=oid, **defaults)
            column.refresh_from_db()
        columns.append(column)
    for oid, nome in TOTALI.items():
        Column.objects.filter(profilo=kyocera, oid=oid).update(
            nome=nome, verificata=True, fonte=FONTE, attiva=True)
    columns += list(Column.objects.filter(profilo=kyocera, oid__in=list(TOTALI)))

    # Le MFC Kyocera senza profilo non avevano alcuna mappa contatori.
    Machine.objects.filter(profilo_snmp__isnull=True, modello__icontains="taskalfa").update(
        profilo_snmp=kyocera)

    # Gli apparati gia' associati ricevono subito le nuove sonde, come con "Applica".
    for device in Device.objects.filter(profilo_snmp=kyocera):
        for column in columns:
            if Probe.objects.filter(dispositivo=device, oid=column.oid).exists():
                continue
            Probe.objects.create(
                dispositivo=device, oid=column.oid, nome=column.nome, profilo_colonna=column,
                tipo_valore=column.tipo_valore, modalita=column.modalita,
                aggregazione=column.aggregazione, unita=column.unita, fattore=column.fattore,
                ordine=column.ordine, attiva=True, etichette=column.etichette,
            )


def backwards(apps, schema_editor):
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")
    Probe = apps.get_model("contatori", "SondaSNMP")
    columns = Column.objects.filter(fonte=FONTE, oid__startswith=TABELLA)
    Probe.objects.filter(profilo_colonna__in=columns).delete()
    columns.delete()
    totali = Column.objects.filter(profilo__slug="kyocera", oid__in=list(TOTALI))
    Probe.objects.filter(profilo_colonna__in=totali).delete()
    for oid, nome in TOTALI.items():
        totali.filter(oid=oid).update(nome=f"{nome} (da confermare)", verificata=False,
                                      fonte=FONTE_DA_CONFERMARE, attiva=False)


class Migration(migrations.Migration):
    dependencies = [("contatori", "0022_preset_hpe_ilo_verificato")]
    operations = [migrations.RunPython(forwards, backwards)]
