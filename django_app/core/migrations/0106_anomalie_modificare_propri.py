"""Anomalie: Ingegneria e Controllo qualità modificano solo i propri OP (02/11/2026).

Con «modificare: tutti» chiunque avesse uno dei due ruoli poteva cambiare le
decisioni di ogni OP. Ora modificano gli OP di cui sono capocommessa/CAR (regole
CC/CAR del modulo) o dove hanno aperto loro le anomalie; aprire segnalazioni su
tutti gli OP resta («creare»). «Qualità» resta su «tutti», il Caporeparto sul
suo team. Si cambia solo la casella ancora su «tutti».
"""
from django.db import migrations

RUOLI = ("ruolo-ufficio-tecnico", "ruolo-controllo-qualita")


def restringi(apps, schema_editor):
    celle = apps.get_model("core", "RuoloPermessoModulo")
    cambiate = celle.objects.filter(
        ruolo__code__in=RUOLI, modulo="anomalie", azione="modificare", consentito=True, ambito="tutti",
    ).update(ambito="propri")
    if cambiate:
        from core.permessi.cache import invalida_permessi

        invalida_permessi()


class Migration(migrations.Migration):
    dependencies = [("core", "0105_ruolo_base_solo_senza_ruoli")]

    operations = [migrations.RunPython(restringi, migrations.RunPython.noop)]
