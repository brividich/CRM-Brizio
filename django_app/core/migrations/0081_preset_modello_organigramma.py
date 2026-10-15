"""Preset dei ruoli al modello «permessi dall'organigramma» (15/10/2026).

Posizioni (Direzione, Qualità, IT, Manutenzione, Ingegneria, Amministrazione,
Caporeparto, Controllo qualità), incarichi (Gestione personale, Gestione
formazione, Preposto, RLS, Addetto emergenze, Referente 27001, Auditor), RSPP
esterno, ruolo base Operatore. Tocca solo nomi e celle ancora uguali ai preset:
quello che e' stato cambiato a mano resta.
"""
from django.db import migrations


def riallinea(apps, schema_editor):
    from core.permessi.preset import riallinea_preset_modello

    riallinea_preset_modello(
        gruppi=apps.get_model("core", "AccessGroup"),
        celle=apps.get_model("core", "RuoloPermessoModulo"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0080_bacheca_self_help"),
        # Il riallineamento spegne i preset ritirati solo se nessun ruolo d'organigramma li concede.
        ("anagrafica", "0174_ruolo_profili_permessi"),
    ]

    operations = [
        migrations.RunPython(riallinea, migrations.RunPython.noop),
    ]
