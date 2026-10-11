"""Preset iniziali delle viste dell'elenco dipendenti (prompt 03).

Create-only e reversibile: il reverse elimina solo i preset creati qui (``preset=True``) e
mai le viste create dagli utenti. Le colonne sensibili restano visibili solo a chi ha il permesso.
"""
from django.db import migrations

PRESET = [
    ("standard", "Standard", "Vista di partenza dell'elenco.", True, ["reparto", "mansione", "email"]),
    ("iso9001", "ISO 9001", "Qualità: ruoli, qualifiche e formazione.", False,
     ["reparto", "mansione", "ruoli", "matricola", "formazione_scaduta", "formazione_in_scadenza", "timbri"]),
    ("iso45001", "ISO 45001", "Salute e sicurezza: visite e formazione obbligatoria.", False,
     ["reparto", "mansione", "ruoli", "visita_scadenza", "visita_scaduta", "formazione_scaduta", "formazione_in_scadenza"]),
    ("hr", "HR", "Rapporto di lavoro e contatti aziendali.", False,
     ["reparto", "area_aziendale", "tipologia_contratto", "livello", "assunzione", "fine_prova", "email_aziendale", "telefono_aziendale", "account"]),
    ("sicurezza", "Sicurezza", "Vista operativa per preposti e RSPP.", False,
     ["reparto", "mansione", "ruoli", "badge", "visita_scaduta", "formazione_scaduta"]),
    ("altro", "Altro", "Vista libera da personalizzare.", False, ["reparto", "mansione"]),
]


def avanti(apps, schema_editor):
    Vista = apps.get_model("anagrafica", "VistaElenco")
    for ordine, (codice, nome, descrizione, predefinita, chiavi) in enumerate(PRESET, start=1):
        Vista.objects.get_or_create(codice=codice, defaults={
            "nome": nome, "descrizione": descrizione, "predefinita": predefinita, "preset": True,
            "ordine": ordine * 10, "colonne": [{"chiave": k, "visibile": True, "larghezza": 0} for k in chiavi],
        })


def indietro(apps, schema_editor):
    Vista = apps.get_model("anagrafica", "VistaElenco")
    Vista.objects.filter(preset=True, codice__in=[p[0] for p in PRESET]).delete()


class Migration(migrations.Migration):
    dependencies = [("anagrafica", "0157_viste_elenco_dipendenti")]
    operations = [migrations.RunPython(avanti, indietro)]
