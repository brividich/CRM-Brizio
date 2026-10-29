"""Timbri: «copiare» e «scaricare» diventano azioni proprie della matrice dei ruoli.

Prima copia e download dipendevano da «esportare» del modulo, senza ambito.
Ogni cella «esportare» di timbri viene copiata su «copiare» e «scaricare» con
lo stesso esito e lo stesso ambito, cosi' i ruoli con una cella esplicita non cambiano.
Eccezione voluta: i ruoli «vede tutto» ricevevano «esportare» d'ufficio, ma
copia e download di firme e timbri non sono consultazione e non li ricevono
piu' (si concedono a mano). Poi si restringe ruolo per ruolo (Impostazioni
timbri › Permessi o matrice dei ruoli). Le celle gia' presenti non si toccano.
"""
from django.db import migrations

AZIONI = ("copiare", "scaricare")
NOTA = "[TIMBRI_0007] da «esportare»"


def avanti(apps, schema_editor):
    Cella = apps.get_model("core", "RuoloPermessoModulo")
    for azione in AZIONI:
        gia = set(Cella.objects.filter(modulo="timbri", azione=azione).values_list("ruolo_id", flat=True))
        for cella in Cella.objects.filter(modulo="timbri", azione="esportare"):
            if cella.ruolo_id in gia:
                continue
            Cella.objects.create(
                ruolo_id=cella.ruolo_id, modulo="timbri", azione=azione,
                ambito=cella.ambito, consentito=cella.consentito, note=NOTA,
            )


def indietro(apps, schema_editor):
    Cella = apps.get_model("core", "RuoloPermessoModulo")
    Cella.objects.filter(modulo="timbri", azione__in=AZIONI, note=NOTA).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("timbri", "0006_registrotimbro_abilitazione_processo_and_more"),
        ("core", "0102_impostazioni_tutte_le_pagine"),
    ]
    operations = [migrations.RunPython(avanti, indietro)]
