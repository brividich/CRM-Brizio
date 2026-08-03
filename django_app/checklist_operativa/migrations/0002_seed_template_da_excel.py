"""Data migration: seed delle mansioni template dal file CHECK CHIUSURA.xlsx.

Importa il testo delle 22 mansioni storiche (colonna MANSIONE) come
ChecklistTaskTemplate, senza responsabile assegnato: l'assegnazione reale si
fa dalla pagina Configurazione (puo' differire dall'addetto storico del file
per motivi organizzativi). Idempotente: get_or_create per ordine.
"""
from django.db import migrations

# (ordine, descrizione, addetto_storico_da_file)
_MANSIONI = [
    (1, "Spegnere Area Sala Collaudo - Sala Metrologica", "Ammannati"),
    (2, "Avvisare Vigilanza.", "Giani"),
    (3, "Macchine da caffe' e fontanelle chiudere acqua.", "Boschi"),
    (4, "Pc reparto assicurarsi che siano spenti.", "Boschi"),
    (5, "Oliare tutti i pezzi e strumenti di controllo.", "Boschi"),
    (6, "Compressore, Essiccatore, interruttore generale OFF.", "Boschi"),
    (7, "Spegnere caldaia e climatizzatori mensa", "Boschi"),
    (8, "Verifica Generali Fraccaro + bruciatore mensa", "Boschi"),
    (9, "Pc reparto assicurarsi che siano spenti.", "Dei"),
    (10, "Oliare tutti i pezzi e strumenti di controllo.", "Dei"),
    (11, "Spegnere impianto Mitsubishi CN5", "Dei"),
    (12, "Pc reparto assicurarsi che siano spenti.", "Santucci"),
    (13, "Oliare tutti i pezzi e strumenti di controllo.", "Santucci"),
    (14, "Assicurarsi che i muletti siano scollegati dalla rete + PLE", "Manutenzione"),
    (15, "Spegnere evaporatore", "Manutenzione"),
    (16, "Spegnere riscaldamento bagno donne Rep. Torni", "Manutenzione"),
    (17, "Disattivare riscaldamento/condizionatori Ufficio Amministrazione/Tecnico/CQI", "Manutenzione"),
    (18, "Programmare Fraccaro con piano ferie per il loro spegnimento", "Manutenzione"),
    (19, "Disattivare apertura cancello.", "Manutenzione"),
    (20, "Spegnere clima bagno Uff. Amm.", "Manutenzione"),
    (21, "Spegnere ventilatore ricircolo aria Uff. Amm.", "Manutenzione"),
    (22, "Distacco Fan coil ufficio tecnico C1", "Girardi"),
]


def forwards(apps, schema_editor):
    ChecklistTaskTemplate = apps.get_model("checklist_operativa", "ChecklistTaskTemplate")
    for ordine, descrizione, addetto_storico in _MANSIONI:
        ChecklistTaskTemplate.objects.get_or_create(
            ordine=ordine,
            defaults={
                "descrizione": descrizione,
                "attivo": True,
                "note": f"Assegnatario storico (da file CHECK CHIUSURA.xlsx): {addetto_storico}",
            },
        )


def backwards(apps, schema_editor):
    ChecklistTaskTemplate = apps.get_model("checklist_operativa", "ChecklistTaskTemplate")
    ChecklistTaskTemplate.objects.filter(
        note__startswith="Assegnatario storico (da file CHECK CHIUSURA.xlsx):"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("checklist_operativa", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
