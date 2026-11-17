"""Ticket: la mail al richiedente parte solo alla chiusura, non a ogni cambio di stato.

Alla regola ``tickets-cambio-stato-email-richiedente`` si aggiunge la condizione
«stato è uguale a CHIUSO» e si aggiornano oggetto e nome. Se la condizione c'è
già non tocca niente; se la regola non esiste lo dice e passa oltre.
"""
from django.db import migrations

REGOLA = "tickets-cambio-stato-email-richiedente"
OGGETTO_VECCHIO = "TICKET [{numero_ticket}] Stato aggiornato: {stato}"
OGGETTO_NUOVO = "TICKET [{numero_ticket}] Chiuso"


def applica(apps, schema_editor):
    AutomationRule = apps.get_model("automazioni", "AutomationRule")
    AutomationCondition = apps.get_model("automazioni", "AutomationCondition")
    AutomationAction = apps.get_model("automazioni", "AutomationAction")
    rule = AutomationRule.objects.filter(code=REGOLA).first()
    if rule is None:
        print(f"\n  [automazioni.0043] Mail ticket solo alla chiusura NON applicata: «{REGOLA}» non presente.")
        return
    if AutomationCondition.objects.filter(rule=rule, field_name="stato", operator="equals").exists():
        print("\n  [automazioni.0043] Mail ticket solo alla chiusura: condizione già presente.")
        return
    ultimo = AutomationCondition.objects.filter(rule=rule).order_by("-order").values_list("order", flat=True).first()
    AutomationCondition.objects.create(
        rule=rule, order=(ultimo or 0) + 1, field_name="stato", operator="equals",
        expected_value="CHIUSO", value_type="string", compare_with_old=False, is_enabled=True,
    )
    rule.name = "Chiusura ticket - email richiedente"
    rule.description = "Notifica il richiedente quando il ticket viene chiuso."
    rule.save(update_fields=["name", "description"])
    for azione in AutomationAction.objects.filter(rule=rule, action_type="send_email"):
        config = dict(azione.config_json or {})
        if config.get("subject_template") == OGGETTO_VECCHIO:
            config["subject_template"] = OGGETTO_NUOVO
            azione.config_json = config
            azione.save(update_fields=["config_json"])
    print("\n  [automazioni.0043] Mail ticket solo alla chiusura applicata.")


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0042_etichette_condizioni_italiano"),
    ]

    operations = [
        migrations.RunPython(applica, migrations.RunPython.noop),
    ]
