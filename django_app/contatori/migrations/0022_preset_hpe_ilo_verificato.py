"""Preset HPE ProLiant / iLO verificato su un DL360 Gen10 con iLO 5 2.72.

Il profilo nasceva con le sonde server generiche (hrSystemProcesses,
hrSystemNumUsers): l'iLO non espone HOST-RESOURCES-MIB e risponde noSuchName,
quindi ogni lettura falliva. Ogni OID qui sotto ha risposto il 2026-10-05.

Le "condition" delle MIB Compaq/HPE (CPQHLTH, CPQIDA, CPQSTDEQ, CPQSM2, CPQNIC)
condividono l'enumerazione 1 = altro/non presente, 2 = OK, 3 = degradato,
4 = guasto: oltre 2 e' attenzione, oltre 3 critico. Nelle colonne WALK il
massimo e' il componente peggiore (gli slot vuoti valgono 1 e non pesano).
"""
from decimal import Decimal

from django.db import migrations

FONTE_HPE = "walk HPE ProLiant DL360 Gen10, iLO 5 2.72 (2026-10-05)"
D = Decimal
CONDIZIONE = "1=Altro/Non presente, 2=OK, 3=Degradato, 4=Guasto"
STATO = {"soglia_warning_max": D("2"), "soglia_critica_max": D("3"), "etichette": CONDIZIONE}
GENERICHE_SERVER = ["1.3.6.1.2.1.25.1.6.0", "1.3.6.1.2.1.25.1.5.0"]

HPE_COLUMNS = [
    {"nome": "Modello", "oid": "1.3.6.1.4.1.232.2.2.4.2.0", "tipo_valore": "TESTO"},
    {"nome": "Seriale", "oid": "1.3.6.1.4.1.232.2.2.2.1.0", "tipo_valore": "TESTO"},
    {"nome": "Firmware iLO", "oid": "1.3.6.1.4.1.232.9.2.2.2.0", "tipo_valore": "TESTO"},
    # Stato complessivo calcolato dall'iLO su tutti i sottosistemi.
    {"nome": "Salute generale", "oid": "1.3.6.1.4.1.232.6.1.3.0", **STATO},
    {"nome": "Temperature", "oid": "1.3.6.1.4.1.232.6.2.6.1.0", **STATO},
    {"nome": "Ventole", "oid": "1.3.6.1.4.1.232.6.2.6.4.0", **STATO},
    {"nome": "Alimentatori", "oid": "1.3.6.1.4.1.232.6.2.9.1.0", **STATO},
    {"nome": "Memoria", "oid": "1.3.6.1.4.1.232.6.2.14.4.0", **STATO},
    {"nome": "Processori", "oid": "1.3.6.1.4.1.232.1.1.3.0", **STATO},
    {"nome": "Storage / controller", "oid": "1.3.6.1.4.1.232.3.1.3.0", **STATO},
    {"nome": "Schede di rete", "oid": "1.3.6.1.4.1.232.18.1.3.0", **STATO},
    {"nome": "Stato iLO", "oid": "1.3.6.1.4.1.232.9.1.3.0", **STATO},
    {"nome": "Batteria di sistema", "oid": "1.3.6.1.4.1.232.6.2.17.2.1.4", "modalita": "WALK",
     "aggregazione": "MASSIMO", **STATO},
    # Ogni sensore ha una propria soglia (42 °C ingresso, 110 °C chipset...):
    # il massimo assoluto e' informativo, l'allarme lo da' "Temperature".
    {"nome": "Temperatura massima sensori", "oid": "1.3.6.1.4.1.232.6.2.6.8.1.4", "modalita": "WALK",
     "aggregazione": "MASSIMO", "unita": "°C"},
    {"nome": "Consumo elettrico", "oid": "1.3.6.1.4.1.232.6.2.15.3.0", "unita": "W"},
]


def _upsert(Column, profile, specs, start, fonte):
    columns = []
    for order, spec in enumerate(specs, start):
        spec = dict(spec)
        oid = spec.pop("oid")
        defaults = {
            "tipo_valore": "NUMERO", "modalita": "GET", "aggregazione": "PRIMO",
            "unita": "", "fattore": D("1"), "verificata": True, "fonte": fonte,
            "ordine": order, "attiva": True,
            **spec,
        }
        column, _ = Column.objects.update_or_create(profilo=profile, oid=oid, defaults=defaults)
        columns.append(column)
    return columns


def forwards(apps, schema_editor):
    Profile = apps.get_model("contatori", "ProfiloSNMP")
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")
    Device = apps.get_model("contatori", "DispositivoSNMP")
    Probe = apps.get_model("contatori", "SondaSNMP")

    hpe = Profile.objects.filter(slug="hpe-server").first()
    if hpe is None:
        return
    # Le sonde generate dalle colonne generiche non hanno mai letto nulla su un
    # iLO: vanno via con le colonne (SET_NULL le trasformerebbe in manuali).
    generiche = Column.objects.filter(profilo=hpe, oid__in=GENERICHE_SERVER)
    Probe.objects.filter(profilo_colonna__in=generiche).delete()
    generiche.delete()

    columns = _upsert(Column, hpe, HPE_COLUMNS, 10, FONTE_HPE)
    # Gli apparati gia' associati al profilo ricevono subito le nuove sonde,
    # come farebbe "Applica"; le sonde manuali con lo stesso OID restano intatte.
    for device in Device.objects.filter(profilo_snmp=hpe):
        for column in columns:
            if Probe.objects.filter(dispositivo=device, oid=column.oid).exists():
                continue
            Probe.objects.create(
                dispositivo=device, oid=column.oid, nome=column.nome, profilo_colonna=column,
                tipo_valore=column.tipo_valore, modalita=column.modalita,
                aggregazione=column.aggregazione, unita=column.unita, fattore=column.fattore,
                ordine=column.ordine, attiva=True, etichette=column.etichette,
                soglia_warning_min=column.soglia_warning_min,
                soglia_warning_max=column.soglia_warning_max,
                soglia_critica_min=column.soglia_critica_min,
                soglia_critica_max=column.soglia_critica_max,
            )


def backwards(apps, schema_editor):
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")
    Probe = apps.get_model("contatori", "SondaSNMP")
    columns = Column.objects.filter(fonte=FONTE_HPE)
    Probe.objects.filter(profilo_colonna__in=columns).delete()
    columns.delete()


class Migration(migrations.Migration):
    dependencies = [("contatori", "0021_etichette_preset_verificati")]
    operations = [migrations.RunPython(forwards, backwards)]
