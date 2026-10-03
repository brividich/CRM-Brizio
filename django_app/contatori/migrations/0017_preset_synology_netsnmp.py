"""Preset Synology e Linux/Net-SNMP verificati sul walk di un RS2423RP+ (DSM 7.4).

Ogni OID e' presente nel walk del 2026-10-02. Le enumerazioni di stato seguono
la Synology MIB Guide: 1 = normale. Gli spazi volume/RAID sono confrontati con
hrStorage (/volume1: stesso totale in byte).
"""
from decimal import Decimal

from django.db import migrations

FONTE_SYNO = "walk Synology RS2423RP+ DSM 7.4-90080 (2026-10-02)"
FONTE_NETSNMP = "walk net-snmp di Synology DSM 7.4 (2026-10-02)"
D = Decimal

# Valori comuni a qualunque agente net-snmp (HOST-RESOURCES-MIB, UCD-SNMP-MIB).
NETSNMP_COLUMNS = [
    {"nome": "Carico CPU medio", "oid": "1.3.6.1.2.1.25.3.3.1.2", "modalita": "WALK",
     "aggregazione": "MEDIA", "unita": "%", "soglia_warning_max": D("85"), "soglia_critica_max": D("95")},
    {"nome": "RAM totale", "oid": "1.3.6.1.4.1.2021.4.5.0", "unita": "MiB", "fattore": D("0.000977")},
    # memSysAvail (MemAvailable): coincide con hrStorage "Available memory".
    # memAvailReal (.6) e' solo la RAM libera, senza cache: sottostima.
    {"nome": "RAM disponibile", "oid": "1.3.6.1.4.1.2021.4.27.0", "unita": "MiB", "fattore": D("0.000977")},
    # sysUpTime misura l'agente SNMP (si azzera al riavvio del servizio);
    # hrSystemUptime misura il sistema.
    {"nome": "Uptime sistema", "oid": "1.3.6.1.2.1.25.1.1.0", "tipo_valore": "TIMETICKS", "unita": "s"},
]

SYNOLOGY_COLUMNS = [
    {"nome": "Modello", "oid": "1.3.6.1.4.1.6574.1.5.1.0", "tipo_valore": "TESTO"},
    {"nome": "Seriale", "oid": "1.3.6.1.4.1.6574.1.5.2.0", "tipo_valore": "TESTO"},
    {"nome": "Versione DSM", "oid": "1.3.6.1.4.1.6574.1.5.3.0", "tipo_valore": "TESTO"},
    # 1 normale, 2 guasto.
    {"nome": "Stato sistema", "oid": "1.3.6.1.4.1.6574.1.1.0", "soglia_critica_max": D("1")},
    {"nome": "Temperatura sistema", "oid": "1.3.6.1.4.1.6574.1.2.0", "unita": "°C",
     "soglia_warning_max": D("55"), "soglia_critica_max": D("65")},
    {"nome": "Alimentazione", "oid": "1.3.6.1.4.1.6574.1.3.0", "soglia_critica_max": D("1")},
    {"nome": "Ventola sistema", "oid": "1.3.6.1.4.1.6574.1.4.1.0", "soglia_critica_max": D("1")},
    {"nome": "Ventola CPU", "oid": "1.3.6.1.4.1.6574.1.4.2.0", "soglia_critica_max": D("1")},
    # 1 aggiornamento disponibile, 2 nessuno: informativo.
    {"nome": "Aggiornamento DSM disponibile", "oid": "1.3.6.1.4.1.6574.1.5.4.0"},
    # diskStatus: 1 normale, 2 inizializzato, 3 non inizializzato,
    # 4 partizione di sistema guasta, 5 guasto. Il massimo e' il disco peggiore.
    {"nome": "Stato peggiore dischi", "oid": "1.3.6.1.4.1.6574.2.1.1.5", "modalita": "WALK",
     "aggregazione": "MASSIMO", "soglia_warning_max": D("1"), "soglia_critica_max": D("3")},
    # diskHealthStatus: 1 normale, 2 attenzione, 3 critico, 4 in guasto.
    {"nome": "Salute peggiore dischi", "oid": "1.3.6.1.4.1.6574.2.1.1.13", "modalita": "WALK",
     "aggregazione": "MASSIMO", "soglia_warning_max": D("1"), "soglia_critica_max": D("2")},
    {"nome": "Temperatura massima dischi", "oid": "1.3.6.1.4.1.6574.2.1.1.6", "modalita": "WALK",
     "aggregazione": "MASSIMO", "unita": "°C", "soglia_warning_max": D("50"), "soglia_critica_max": D("60")},
    # raidStatus: 1 normale, 2-10 operazioni in corso (riparazione, sync...),
    # 11 degradato, 12 guasto.
    {"nome": "Stato peggiore volumi/RAID", "oid": "1.3.6.1.4.1.6574.3.1.1.3", "modalita": "WALK",
     "aggregazione": "MASSIMO", "soglia_warning_max": D("1"), "soglia_critica_max": D("10")},
]


def _upsert(Column, profile, specs, start, fonte):
    for order, spec in enumerate(specs, start):
        spec = dict(spec)
        oid = spec.pop("oid")
        defaults = {
            "tipo_valore": "NUMERO", "modalita": "GET", "aggregazione": "PRIMO",
            "unita": "", "fattore": D("1"), "verificata": True, "fonte": fonte,
            "ordine": order, "attiva": True,
            **spec,
        }
        Column.objects.update_or_create(profilo=profile, oid=oid, defaults=defaults)


def forwards(apps, schema_editor):
    Profile = apps.get_model("contatori", "ProfiloSNMP")
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")

    synology = Profile.objects.filter(slug="synology").first()
    if synology is not None:
        # DSM espone sysObjectID net-snmp (1.3.6.1.4.1.8072.3.2.10): il modello
        # Synology e' il segnale affidabile per il riconoscimento.
        synology.oid_riconoscimento = "1.3.6.1.4.1.6574.1.5.1.0"
        synology.save(update_fields=["oid_riconoscimento"])
        _upsert(Column, synology, SYNOLOGY_COLUMNS, 20, FONTE_SYNO)
        _upsert(Column, synology, NETSNMP_COLUMNS, 50, FONTE_NETSNMP)

    netsnmp = Profile.objects.filter(slug="net-snmp").first()
    if netsnmp is not None:
        _upsert(Column, netsnmp, NETSNMP_COLUMNS, 20, FONTE_NETSNMP)


def backwards(apps, schema_editor):
    Profile = apps.get_model("contatori", "ProfiloSNMP")
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")
    Column.objects.filter(fonte__in=[FONTE_SYNO, FONTE_NETSNMP]).delete()
    Profile.objects.filter(slug="synology").update(oid_riconoscimento="")


class Migration(migrations.Migration):
    dependencies = [("contatori", "0016_profili_riconoscimento_soglie_verifica")]
    operations = [migrations.RunPython(forwards, backwards)]
