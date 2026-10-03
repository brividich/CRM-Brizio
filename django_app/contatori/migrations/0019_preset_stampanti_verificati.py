"""Preset stampanti verificati sui walk della flotta (2026-10-02).

Walk: Canon iR-ADV C5840 (x2), C3822, C5535 III (x2, fw 48.16 e 16.12),
Kyocera TASKalfa 5054ci e 3554ci, HP DesignJet T730, Zebra ZD421.
"""
from decimal import Decimal

from django.db import migrations

FONTE = ("walk flotta 2026-10-02: Canon iR-ADV C5840/C3822/C5535 III, Kyocera TASKalfa "
         "5054ci/3554ci, HP DesignJet T730, Zebra ZD421")
FONTE_CANON = "walk Canon iR-ADV C5840/C3822/C5535 III (2026-10-02), nomi letti dalla tabella contatori"
FONTE_KYOCERA_DA_CONFERMARE = (
    "dedotto da walk TASKalfa 5054ci/3554ci: coerente con la somma per funzione; "
    "confermare sul pannello contatori prima di attivare"
)
D = Decimal

# Standard HOST-RESOURCES-MIB / Printer-MIB presenti su tutte le stampanti indicate.
COMUNI = [
    {"nome": "Modello", "oid": "1.3.6.1.2.1.25.3.2.1.3.1", "tipo_valore": "TESTO"},
    # hrDeviceStatus: 2 in funzione, 3 attenzione, 4 test, 5 fermo.
    {"nome": "Stato dispositivo", "oid": "1.3.6.1.2.1.25.3.2.1.5.1",
     "soglia_warning_max": D("2"), "soglia_critica_max": D("4")},
    {"nome": "Errori rilevati", "oid": "1.3.6.1.2.1.25.3.5.1.2.1", "tipo_valore": "ERR_PRT"},
]
DISPLAY = {"nome": "Messaggio display", "oid": "1.3.6.1.2.1.43.16.5.1.2.1.1", "tipo_valore": "TESTO"}

CANON_TABELLA = "1.3.6.1.4.1.1602.1.11.1.4.1.4"
CANON = [
    {"nome": "Firmware", "oid": "1.3.6.1.4.1.1602.1.1.1.4.0", "tipo_valore": "TESTO"},
    {"nome": "Totale (Total 1)", "oid": f"{CANON_TABELLA}.101", "unita": "pagine"},
    {"nome": "Copie", "oid": f"{CANON_TABELLA}.201", "unita": "pagine"},
    {"nome": "Stampe", "oid": f"{CANON_TABELLA}.301", "unita": "pagine"},
    {"nome": "Scansioni", "oid": f"{CANON_TABELLA}.501", "unita": "pagine"},
    {"nome": "Fronte-retro", "oid": f"{CANON_TABELLA}.114", "unita": "pagine"},
]

KYOCERA_DA_CONFERMARE = [
    {"nome": "Totale B/N (da confermare)", "oid": "1.3.6.1.4.1.1347.42.3.1.1.1.1.1", "unita": "pagine"},
    {"nome": "Totale colore (da confermare)", "oid": "1.3.6.1.4.1.1347.42.3.1.1.1.1.2", "unita": "pagine"},
]

PRINTER_TOTAL = "1.3.6.1.2.1.43.10.2.1.4"


def _upsert(Column, profile, specs, start, fonte, *, verificata=True, attiva=True):
    for order, spec in enumerate(specs, start):
        spec = dict(spec)
        oid = spec.pop("oid")
        Column.objects.update_or_create(profilo=profile, oid=oid, defaults={
            "tipo_valore": "NUMERO", "modalita": "GET", "aggregazione": "PRIMO",
            "unita": "", "fattore": D("1"), "verificata": verificata, "fonte": fonte,
            "ordine": order, "attiva": attiva, **spec,
        })


def forwards(apps, schema_editor):
    Profile = apps.get_model("contatori", "ProfiloSNMP")
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")
    profili = {p.slug: p for p in Profile.objects.filter(
        slug__in=["canon-ir-adv", "kyocera", "hp-printer", "zebra-printer"])}

    for slug, profilo in profili.items():
        specs = COMUNI + ([] if slug == "zebra-printer" else [DISPLAY])
        _upsert(Column, profilo, specs, 30, FONTE)
        totale = Column.objects.filter(profilo=profilo, oid=PRINTER_TOTAL)
        if slug == "zebra-printer":
            # La ZD421 non espone la Printer-MIB dei contatori: la colonna resterebbe in errore.
            totale.update(attiva=False, verificata=False,
                          fonte="non presente sul walk Zebra ZD421 (2026-10-02)")
        else:
            totale.update(verificata=True, fonte=FONTE)

    canon = profili.get("canon-ir-adv")
    if canon is not None:
        Column.objects.filter(profilo=canon, oid__startswith="1.3.6.1.4.1.1602.1.11.1.3.1.4.").update(
            verificata=True, fonte=FONTE_CANON)
        _upsert(Column, canon, CANON, 40, FONTE_CANON)

    kyocera = profili.get("kyocera")
    if kyocera is not None:
        _upsert(Column, kyocera, KYOCERA_DA_CONFERMARE, 40, FONTE_KYOCERA_DA_CONFERMARE,
                verificata=False, attiva=False)

    hp = profili.get("hp-printer")
    if hp is not None:
        # sysObjectID HP stampanti = 1.3.6.1.4.1.11.2.3.9.x (verificato su DesignJet T730).
        # Il prefisso enterprise 11 e il pattern "HP" catturavano anche gli switch HPE/Aruba.
        hp.sys_object_id_prefix = "1.3.6.1.4.1.11.2.3.9"
        hp.sys_descr_pattern = r"LaserJet|PageWide|DesignJet|OfficeJet|ETHERNET MULTI-ENVIRONMENT"
        hp.save(update_fields=["sys_object_id_prefix", "sys_descr_pattern"])


def backwards(apps, schema_editor):
    Profile = apps.get_model("contatori", "ProfiloSNMP")
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")
    Column.objects.filter(fonte__in=[FONTE, FONTE_CANON, FONTE_KYOCERA_DA_CONFERMARE]).exclude(
        oid__startswith="1.3.6.1.4.1.1602.1.11.1.3.1.4.").exclude(oid=PRINTER_TOTAL).delete()
    Column.objects.filter(oid__startswith="1.3.6.1.4.1.1602.1.11.1.3.1.4.").update(verificata=False, fonte="")
    Column.objects.filter(oid=PRINTER_TOTAL).update(verificata=False, fonte="", attiva=True)
    Profile.objects.filter(slug="hp-printer").update(
        sys_object_id_prefix="1.3.6.1.4.1.11", sys_descr_pattern=r"HP|LaserJet|PageWide")


class Migration(migrations.Migration):
    dependencies = [("contatori", "0018_tipo_valore_errori_stampante")]
    operations = [migrations.RunPython(forwards, backwards)]
