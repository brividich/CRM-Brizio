"""Preset SNMP TVT per la videosorveglianza: NVR (`tvt-nvr`) e telecamere IP (`tvt-ipc`).

TVT non pubblica una MIB privata: qui ci sono solo OID delle MIB standard
(IF-MIB, HOST-RESOURCES-MIB, UCD-SNMP-MIB di net-snmp), nessun OID privato.
Tutte le colonne nascono ``verificata=False``: si confermano sulle catture reali
(`snmp_capture`) e solo allora si marcano verificate.

- Attive: solo IF-MIB (MAC, velocita' del collegamento, errori), presente su
  praticamente ogni agent Linux. Una colonna che non risponde mette il
  dispositivo in «Attenzione», quindi niente OID incerti attivi.
- Spente (``attiva=False``) sull'NVR: HOST-RESOURCES e UCD. Si accendono dal
  catalogo profili se la cattura le mostra.
- Nessun riconoscimento automatico (prefisso sysObjectID / pattern sysDescr):
  i valori reali si vedranno nelle catture; fino ad allora il profilo si
  assegna a mano al dispositivo.
- Nessuna soglia: senza catture non si sa quali interfacce/dischi sono inutilizzati,
  e soglie a vuoto metterebbero in allarme tutte le telecamere.
"""
from decimal import Decimal

from django.db import migrations

D = Decimal
FONTE = "MIB standard (IF-MIB / HOST-RESOURCES / UCD) - da verificare su cattura TVT"
DA_KB_A_MIB = D("0.000977")

IF_MIB = [
    {"nome": "MAC", "oid": "1.3.6.1.2.1.2.2.1.6", "tipo_valore": "MAC", "modalita": "WALK",
     "aggregazione": "VALIDO"},
    {"nome": "Velocita collegamento", "oid": "1.3.6.1.2.1.2.2.1.5", "modalita": "WALK",
     "aggregazione": "MASSIMO", "unita": "Mbit/s", "fattore": D("0.000001")},
    {"nome": "Errori in ingresso", "oid": "1.3.6.1.2.1.2.2.1.14", "modalita": "WALK", "aggregazione": "SOMMA"},
    {"nome": "Errori in uscita", "oid": "1.3.6.1.2.1.2.2.1.20", "modalita": "WALK", "aggregazione": "SOMMA"},
]

NVR_RISORSE = [
    {"nome": "RAM totale", "oid": "1.3.6.1.2.1.25.2.2.0", "unita": "MiB", "fattore": DA_KB_A_MIB},
    {"nome": "Carico CPU medio", "oid": "1.3.6.1.2.1.25.3.3.1.2", "modalita": "WALK",
     "aggregazione": "MEDIA", "unita": "%"},
    {"nome": "Stato dispositivi interni", "oid": "1.3.6.1.2.1.25.3.2.1.5", "modalita": "WALK",
     "aggregazione": "MASSIMO",
     "etichette": "1=Sconosciuto, 2=In funzione, 3=Attenzione, 4=In test, 5=Guasto"},
    {"nome": "Occupazione massima dischi", "oid": "1.3.6.1.4.1.2021.9.1.9", "modalita": "WALK",
     "aggregazione": "MASSIMO", "unita": "%"},
    {"nome": "RAM disponibile", "oid": "1.3.6.1.4.1.2021.4.6.0", "unita": "MiB", "fattore": DA_KB_A_MIB},
    {"nome": "CPU inattiva", "oid": "1.3.6.1.4.1.2021.11.11.0", "unita": "%"},
]

PROFILI = {
    "tvt-nvr": {
        "nome": "TVT NVR (videoregistratore)",
        "categoria": "TVCC_NVR",
        "famiglia_modelli": "NVR TVT",
        "descrizione": "Videoregistratore di rete TVT: interfacce di rete; risorse e dischi "
                       "(HOST-RESOURCES/UCD) spenti finche' la cattura non li conferma.",
        "colonne": [(c, True) for c in IF_MIB] + [(c, False) for c in NVR_RISORSE],
    },
    "tvt-ipc": {
        "nome": "TVT telecamera IP",
        "categoria": "TVCC_CAMERA",
        "famiglia_modelli": "Telecamere IP TVT",
        "descrizione": "Telecamera IP TVT: MAC, velocita' del collegamento ed errori di rete.",
        "colonne": [(c, True) for c in IF_MIB],
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
        for ordine, (colonna, attiva) in enumerate(spec["colonne"], 1):
            colonna = dict(colonna)
            oid = colonna.pop("oid")
            # Create-only: una colonna gia' verificata o modificata dall'operatore non si tocca.
            Column.objects.get_or_create(profilo=profile, oid=oid, defaults={
                "tipo_valore": "NUMERO", "modalita": "GET", "aggregazione": "PRIMO",
                "unita": "", "fattore": D("1"), "verificata": False, "fonte": FONTE,
                "ordine": ordine * 10, "attiva": attiva,
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
