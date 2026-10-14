"""Preset SNMP TVT per la videosorveglianza: NVR (`tvt-nvr`) e telecamere IP (`tvt-ipc`).

Verificati sulle letture reali del 14/10/2026 (fixture sanificate in
``contatori/fixtures/snmp/tvt_*.snmprec``):

- NVR TD-3364H8-A3H-B (firmware 2.1.0.76943B250408): l'agent risponde solo a GET
  su OID esatti (GETNEXT vuoto, GETBULK ignorato), quindi niente WALK. Espone
  sysDescr (firmware), sysObjectID scritto come testo (modello), sysUpTime e,
  della IF-MIB, ifDescr/ifSpeed/ifOperStatus di eth0 (.1) ed eth1 (.2). Non
  espone MAC, errori, HOST-RESOURCES ne' UCD: niente dischi ne' risorse.
- Telecamere IP: agent net-snmp generico che espone solo il gruppo system e le
  statistiche SNMP. Nessuna interfaccia, MAC o risorsa: il profilo non ha
  colonne e serve come controllo di raggiungibilita' (risponde / non risponde).

Nessun riconoscimento automatico: sysDescr e sysObjectID non identificano TVT
(la telecamera dichiara l'OID generico net-snmp). Il profilo si assegna a mano.
"""
from decimal import Decimal

from django.db import migrations

D = Decimal
FONTE_NVR = "Lettura GET su NVR TVT TD-3364H8-A3H-B fw 2.1.0.76943B250408 (14/10/2026)"
STATO_IF = "1=Attiva, 2=Non attiva, 3=Test, 4=Sconosciuto, 5=Dormiente, 6=Assente, 7=Livello inferiore non attivo"

NVR = []
for indice, scheda in ((1, "eth0"), (2, "eth1")):
    NVR += [
        {"nome": f"Velocita collegamento {scheda}", "oid": f"1.3.6.1.2.1.2.2.1.5.{indice}",
         "unita": "Mbit/s", "fattore": D("0.000001")},
        # ifOperStatus: 1 = attiva; qualunque altro codice mette l'NVR in «Attenzione».
        {"nome": f"Stato {scheda}", "oid": f"1.3.6.1.2.1.2.2.1.8.{indice}",
         "etichette": STATO_IF, "soglia_warning_max": D("1")},
    ]

PROFILI = {
    "tvt-nvr": {
        "nome": "TVT NVR (videoregistratore)",
        "categoria": "TVCC_NVR",
        "famiglia_modelli": "NVR TVT",
        "descrizione": "Videoregistratore di rete TVT: velocita' e stato delle due schede di rete "
                       "(eth0, eth1). Modello e firmware si leggono da sysObjectID e sysDescr. "
                       "L'apparato non espone MAC, dischi ne' risorse.",
        "colonne": NVR,
    },
    "tvt-ipc": {
        "nome": "TVT telecamera IP",
        "categoria": "TVCC_CAMERA",
        "famiglia_modelli": "Telecamere IP TVT",
        "descrizione": "Telecamera IP TVT: solo controllo di raggiungibilita' (l'agent SNMP risponde "
                       "o no). La telecamera non espone interfacce, MAC ne' risorse.",
        "colonne": [],
    },
}


def forwards(apps, schema_editor):
    Profile = apps.get_model("contatori", "ProfiloSNMP")
    Column = apps.get_model("contatori", "ColonnaProfiloSNMP")

    for slug, spec in PROFILI.items():
        profile, _ = Profile.objects.get_or_create(slug=slug, defaults={
            "nome": spec["nome"], "produttore": "TVT", "categoria": spec["categoria"],
            "famiglia_modelli": spec["famiglia_modelli"], "descrizione": spec["descrizione"],
            "precaricato": True, "attivo": True,
        })
        for ordine, colonna in enumerate(spec["colonne"], 1):
            colonna = dict(colonna)
            oid = colonna.pop("oid")
            # Create-only: una colonna modificata dall'operatore non si tocca.
            Column.objects.get_or_create(profilo=profile, oid=oid, defaults={
                "tipo_valore": "NUMERO", "modalita": "GET", "aggregazione": "PRIMO",
                "unita": "", "fattore": D("1"), "verificata": True, "fonte": FONTE_NVR,
                "ordine": ordine * 10, "attiva": True,
                **colonna,
            })


def backwards(apps, schema_editor):
    Profile = apps.get_model("contatori", "ProfiloSNMP")
    # Solo se nessun dispositivo li usa: il profilo e' SET_NULL ma le sonde generate resterebbero orfane.
    Profile.objects.filter(slug__in=list(PROFILI), dispositivi__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("contatori", "0033_tvcc_categorie_intervalli_mac"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
