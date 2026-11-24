"""Nominativi salvati in Anomalie: da «Nome Cognome» a «COGNOME NOME» (24/11/2026).

Converte, solo se corrispondono a una persona dell'anagrafica:
- gli elenchi di persone del JSON ``SiteConfig[anomalie_config_json]`` (referenti RDC,
  autorizzati, aggiunti/esclusi delle liste capi, persone di gruppi e regole);
- ``AnomaliaSchedaQualita.car_segnalati``.
Nessun cambio di schema. Il ritorno indietro non serve: i confronti del modulo non
dipendono dall'ordine di nome e cognome.
"""

import json
import logging

from django.db import migrations

logger = logging.getLogger(__name__)

CHIAVE_CONFIG = "anomalie_config_json"


def _mappa(schema_editor):
    from anomalie.nominativi import mappa_da_righe

    try:
        with schema_editor.connection.cursor() as cur:
            cur.execute("SELECT nome, cognome FROM anagrafica_dipendenti")
            return mappa_da_righe(cur.fetchall())
    except Exception:  # tabella legacy assente (sviluppo/test): niente da convertire
        logger.info("anomalie 0034: anagrafica_dipendenti non leggibile, nessuna conversione")
        return {}


def avanti(apps, schema_editor):
    from anomalie.nominativi import converti_config, converti_elenco_testo

    mappa = _mappa(schema_editor)
    if not mappa:
        return
    SiteConfig = apps.get_model("core", "SiteConfig")
    riga = SiteConfig.objects.filter(chiave=CHIAVE_CONFIG).first()
    if riga and riga.valore:
        try:
            dati = json.loads(riga.valore)
        except Exception:
            dati = None
        if isinstance(dati, dict):
            nuovi = converti_config(dati, mappa)
            if nuovi != dati:
                riga.valore = json.dumps(nuovi, ensure_ascii=False)
                riga.save(update_fields=["valore"])
    Scheda = apps.get_model("anomalie", "AnomaliaSchedaQualita")
    for scheda in Scheda.objects.exclude(car_segnalati="").only("pk", "car_segnalati").iterator():
        nuovo = converti_elenco_testo(scheda.car_segnalati, mappa)
        if nuovo != scheda.car_segnalati:
            Scheda.objects.filter(pk=scheda.pk).update(car_segnalati=nuovo)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_siteconfig"),
        ("anomalie", "0033_controllo_condiviso"),
    ]

    operations = [
        migrations.RunPython(avanti, migrations.RunPython.noop),
    ]
