from decimal import Decimal

from django.db import migrations


PRINTER_TOTAL = {
    "nome": "Totale impressioni (Printer-MIB)",
    "oid": "1.3.6.1.2.1.43.10.2.1.4",
    "modalita": "WALK",
    "aggregazione": "MASSIMO",
    "unita": "impressioni",
}

NETWORK_COLUMNS = [
    {
        "nome": "Traffico ricevuto interfacce", "oid": "1.3.6.1.2.1.2.2.1.10",
        "modalita": "WALK", "aggregazione": "SOMMA", "unita": "byte",
    },
    {
        "nome": "Traffico trasmesso interfacce", "oid": "1.3.6.1.2.1.2.2.1.16",
        "modalita": "WALK", "aggregazione": "SOMMA", "unita": "byte",
    },
]

SERVER_COLUMNS = [
    {"nome": "Processi attivi", "oid": "1.3.6.1.2.1.25.1.6.0", "unita": "processi"},
    {"nome": "Utenti attivi", "oid": "1.3.6.1.2.1.25.1.5.0", "unita": "utenti"},
]

UPS_COLUMNS = [
    {"nome": "Stato batteria", "oid": "1.3.6.1.2.1.33.1.2.1.0"},
    {"nome": "Secondi su batteria", "oid": "1.3.6.1.2.1.33.1.2.2.0", "unita": "s"},
    {"nome": "Autonomia stimata", "oid": "1.3.6.1.2.1.33.1.2.3.0", "unita": "min"},
    {"nome": "Carica residua", "oid": "1.3.6.1.2.1.33.1.2.4.0", "unita": "%"},
]


PROFILES = [
    # Stampanti/MFC: PEN IANA + Printer-MIB standard. Solo Canon ha qui la
    # mappa contrattuale a quattro contatori gia verificata dal progetto.
    ("canon-ir-adv", "Canon iR-ADV", "Canon", "STAMPANTE", "1602", r"Canon.*iR[- ]?ADV", "v1"),
    ("kyocera", "Kyocera MFP e stampanti", "Kyocera", "STAMPANTE", "1347", r"Kyocera|ECOSYS|TASKalfa", "v2c"),
    ("hp-printer", "HP LaserJet / PageWide", "HP", "STAMPANTE", "11", r"HP|LaserJet|PageWide", "v2c"),
    ("ricoh-printer", "Ricoh MFP e stampanti", "Ricoh", "STAMPANTE", "367", r"Ricoh|Aficio|IM C", "v2c"),
    ("xerox-printer", "Xerox MFP e stampanti", "Xerox", "STAMPANTE", "253", r"Xerox", "v2c"),
    ("brother-printer", "Brother MFC e stampanti", "Brother", "STAMPANTE", "2435", r"Brother", "v2c"),
    ("lexmark-printer", "Lexmark MFP e stampanti", "Lexmark", "STAMPANTE", "641", r"Lexmark", "v2c"),
    ("epson-printer", "Epson stampanti", "Epson", "STAMPANTE", "1248", r"Epson", "v2c"),
    ("sharp-printer", "Sharp MFP", "Sharp", "STAMPANTE", "1536", r"Sharp", "v2c"),
    ("konica-minolta", "Konica Minolta bizhub", "Konica Minolta", "STAMPANTE", "18334", r"Konica|bizhub", "v2c"),
    ("toshiba-printer", "Toshiba e-STUDIO", "Toshiba", "STAMPANTE", "186", r"Toshiba|e-STUDIO", "v2c"),
    ("oki-printer", "OKI stampanti", "OKI", "STAMPANTE", "2001", r"OKI", "v2c"),
    ("samsung-printer", "Samsung stampanti", "Samsung", "STAMPANTE", "236", r"Samsung", "v2c"),
    ("zebra-printer", "Zebra etichette", "Zebra", "STAMPANTE", "10642", r"Zebra", "v2c"),

    # Firewall e sicurezza.
    ("fortinet", "FortiGate / Fortinet", "Fortinet", "FIREWALL", "12356", r"FortiGate|Fortinet", "v2c"),
    ("palo-alto", "Palo Alto Networks", "Palo Alto Networks", "FIREWALL", "25461", r"Palo Alto|PAN-OS", "v2c"),
    ("sophos", "Sophos Firewall", "Sophos", "FIREWALL", "2604", r"Sophos", "v2c"),
    ("check-point", "Check Point", "Check Point", "FIREWALL", "2620", r"Check Point|Gaia", "v2c"),
    ("sonicwall", "SonicWall", "SonicWall", "FIREWALL", "8741", r"SonicWall", "v2c"),

    # Switch, router e Wi-Fi.
    ("cisco", "Cisco IOS / Catalyst / Meraki", "Cisco", "RETE", "9", r"Cisco|IOS|Catalyst|Meraki", "v2c"),
    ("juniper", "Juniper Networks", "Juniper", "RETE", "2636", r"Juniper|JUNOS", "v2c"),
    ("mikrotik", "MikroTik RouterOS", "MikroTik", "RETE", "14988", r"MikroTik|RouterOS", "v2c"),
    ("ubiquiti", "Ubiquiti UniFi / Edge", "Ubiquiti", "RETE", "41112", r"Ubiquiti|UniFi|Edge", "v2c"),
    ("hpe-aruba", "HPE Aruba", "HPE Aruba", "RETE", "11", r"Aruba|ProCurve", "v2c"),

    # Server, sistemi operativi e hypervisor.
    ("dell-server", "Dell PowerEdge / iDRAC", "Dell", "SERVER", "674", r"Dell|PowerEdge|iDRAC", "v2c"),
    ("hpe-server", "HPE ProLiant / iLO", "HPE", "SERVER", "232", r"ProLiant|iLO|Compaq", "v2c"),
    ("lenovo-server", "Lenovo ThinkSystem", "Lenovo", "SERVER", "19046", r"Lenovo|ThinkSystem", "v2c"),
    ("supermicro-server", "Supermicro", "Supermicro", "SERVER", "10876", r"Supermicro", "v2c"),
    ("vmware", "VMware ESXi / vCenter", "VMware", "SERVER", "6876", r"VMware|ESXi", "v2c"),
    ("microsoft", "Microsoft Windows Server", "Microsoft", "SERVER", "311", r"Windows", "v2c"),
    ("net-snmp", "Linux / Net-SNMP", "Net-SNMP", "SERVER", "8072", r"Linux|Net-SNMP", "v2c"),

    # NAS/storage.
    ("synology", "Synology DSM", "Synology", "STORAGE", "6574", r"Synology|DSM", "v2c"),
    ("qnap", "QNAP QTS / QuTS", "QNAP", "STORAGE", "24681", r"QNAP|QTS|QuTS", "v2c"),
    ("netapp", "NetApp ONTAP", "NetApp", "STORAGE", "789", r"NetApp|ONTAP", "v2c"),

    # UPS/alimentazione.
    ("apc-ups", "APC UPS", "APC / Schneider Electric", "UPS", "318", r"APC|Schneider", "v2c"),
    ("eaton-ups", "Eaton UPS", "Eaton", "UPS", "534", r"Eaton", "v2c"),
    ("vertiv-ups", "Vertiv / Liebert UPS", "Vertiv / Liebert", "UPS", "476", r"Vertiv|Liebert", "v2c"),
]


def seed_profiles(apps, schema_editor):
    Profile = apps.get_model("contatori", "ProfiloSNMP")
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")
    for slug, name, vendor, category, pen, pattern, version in PROFILES:
        profile, _ = Profile.objects.update_or_create(
            slug=slug,
            defaults={
                "nome": name,
                "produttore": vendor,
                "categoria": category,
                "famiglia_modelli": name,
                "descrizione": "Profilo iniziale basato su identificazione PEN IANA e MIB standard.",
                "sys_object_id_prefix": f"1.3.6.1.4.1.{pen}",
                "sys_descr_pattern": pattern,
                "versione": version,
                "porta": 161,
                "timeout": 5,
                "precaricato": True,
                "attivo": True,
            },
        )
        if category == "STAMPANTE":
            columns = [PRINTER_TOTAL]
        elif category in {"FIREWALL", "RETE"}:
            columns = NETWORK_COLUMNS
        elif category == "SERVER":
            columns = SERVER_COLUMNS
        elif category == "UPS":
            columns = UPS_COLUMNS
        else:
            columns = []
        for order, spec in enumerate(columns, 10):
            Column.objects.update_or_create(
                profilo=profile, oid=spec["oid"],
                defaults={
                    "nome": spec["nome"],
                    "tipo_valore": "NUMERO",
                    "modalita": spec.get("modalita", "GET"),
                    "aggregazione": spec.get("aggregazione", "PRIMO"),
                    "unita": spec.get("unita", ""),
                    "fattore": Decimal("1"),
                    "ordine": order,
                    "attiva": True,
                },
            )

    canon = Profile.objects.get(slug="canon-ir-adv")
    for order, (key, label, number) in enumerate((
        ("a4_bn", "A4 BN Canon", 113),
        ("a3_bn", "A3 BN Canon", 112),
        ("a4_col", "A4 colore Canon", 123),
        ("a3_col", "A3 colore Canon", 122),
    ), 1):
        Column.objects.update_or_create(
            profilo=canon,
            oid=f"1.3.6.1.4.1.1602.1.11.1.3.1.4.{number}",
            defaults={
                "nome": label, "tipo_valore": "NUMERO", "modalita": "GET",
                "aggregazione": "PRIMO", "unita": "copie",
                "fattore": Decimal("1"), "contatore_mfc": key,
                "ordine": order, "attiva": True,
            },
        )

    Machine = apps.get_model("contatori", "Macchina")
    Machine.objects.filter(modello__in=[
        "iR-ADV C5535i", "iR-ADV DX C5840i", "iR-ADV DX C3822i",
    ], profilo_snmp__isnull=True).update(profilo_snmp=canon)


def unseed_profiles(apps, schema_editor):
    Profile = apps.get_model("contatori", "ProfiloSNMP")
    Profile.objects.filter(precaricato=True).delete()


class Migration(migrations.Migration):
    dependencies = [("contatori", "0008_profilosnmp_dispositivosnmp_timeout_and_more")]
    operations = [migrations.RunPython(seed_profiles, unseed_profiles)]
