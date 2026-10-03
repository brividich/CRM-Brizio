"""Etichette dei codici di stato per i preset verificati e soglia RAID Synology.

Enumerazioni: Synology MIB Guide (DSM 7) e HOST-RESOURCES-MIB (RFC 2790).
raidStatus va oltre 12 (13 = data scrubbing, ...): un massimo > 10 "critico"
darebbe falsi allarmi a ogni verifica periodica, quindi resta solo "attenzione".
"""
from django.db import migrations

NORMALE_GUASTO = "1=Normale, 2=Guasto"
ETICHETTE = {
    "1.3.6.1.4.1.6574.1.1.0": NORMALE_GUASTO,
    "1.3.6.1.4.1.6574.1.3.0": NORMALE_GUASTO,
    "1.3.6.1.4.1.6574.1.4.1.0": NORMALE_GUASTO,
    "1.3.6.1.4.1.6574.1.4.2.0": NORMALE_GUASTO,
    "1.3.6.1.4.1.6574.1.5.4.0": "1=Disponibile, 2=Nessuno, 3=Verifica in corso, 4=Non raggiungibile, 5=Altro",
    "1.3.6.1.4.1.6574.2.1.1.5": ("1=Normale, 2=Inizializzato, 3=Non inizializzato, "
                                 "4=Partizione di sistema guasta, 5=Guasto"),
    "1.3.6.1.4.1.6574.2.1.1.13": "1=Normale, 2=Attenzione, 3=Critico, 4=In guasto",
    "1.3.6.1.4.1.6574.3.1.1.3": (
        "1=Normale, 2=In riparazione, 3=Migrazione, 4=Espansione, 5=Eliminazione, 6=Creazione, "
        "7=Sincronizzazione, 8=Verifica parità, 9=Assemblaggio, 10=Annullamento, 11=Degradato, "
        "12=Guasto, 13=Verifica dati (scrubbing)"),
    "1.3.6.1.2.1.25.3.2.1.5.1": "1=Sconosciuto, 2=In funzione, 3=Attenzione, 4=Test, 5=Fermo",
}
RAID_STATUS = "1.3.6.1.4.1.6574.3.1.1.3"


def forwards(apps, schema_editor):
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")
    Probe = apps.get_model("contatori", "SondaSNMP")
    for oid, etichette in ETICHETTE.items():
        Column.objects.filter(oid=oid, verificata=True).update(etichette=etichette)
        # Le sonde gia' generate dal profilo ricevono le etichette se non personalizzate.
        Probe.objects.filter(oid=oid, profilo_colonna__isnull=False, etichette="").update(etichette=etichette)
    Column.objects.filter(oid=RAID_STATUS, verificata=True).update(soglia_critica_max=None)
    Probe.objects.filter(oid=RAID_STATUS, profilo_colonna__isnull=False).update(soglia_critica_max=None)


def backwards(apps, schema_editor):
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")
    Column.objects.filter(oid__in=list(ETICHETTE)).update(etichette="")


class Migration(migrations.Migration):
    dependencies = [("contatori", "0020_etichette_valori")]
    operations = [migrations.RunPython(forwards, backwards)]
