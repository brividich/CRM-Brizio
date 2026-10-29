"""Mail ad assenza@ per le richieste con «Salta approvazione»: una sola, destinatari per autore.

Prima: la regola di inserimento con salta approvazione porta lo stato a 0 con un
UPDATE, il trigger SQL lo accoda come modifica e scatta anche «Avviso inserimento
dopo approvazione» → assenza@ (e il caporeparto in CC) ricevevano due mail.

Dopo:
- «Avviso inserimento dopo approvazione» parte solo se ``salta_approvazione`` è falso;
- la mail di «Inserimento con salta approvazione» va ad assenza@ con il
  caporeparto in CC, tranne quando l'ha inserita il caporeparto
  (``inserito_dal_capo``: profilo CAR o autore = capo del dipendente): allora
  solo ad assenza@.

Fail-closed: se le regole non hanno la forma attesa non tocca niente e lo dice.
"""
from copy import deepcopy

from django.db import transaction
from django.db.models import Max

from .models import AutomationRule as _Rule, AutomationAction as _Action, AutomationCondition as _Condition

SKIP_RULE = "assenze-pa-skip-approvazione-avviso-inserimento"
APPROVED_RULE = "assenze-pa-approvata-avviso-inserimento"
CAPO_PLACEHOLDER = "{capo_email}"
GROUP_FIELD = "inserito_da_gruppo"
CAPO_FIELD = "inserito_dal_capo"
RUN_IF_CAR = {"field_name": CAPO_FIELD, "operator": "is_true", "expected_value": "", "value_type": "bool"}


def _escludi_salta_approvazione(rule, AutomationCondition):
    conditions = rule.conditions.all()
    if conditions.filter(field_name="salta_approvazione", is_enabled=True).exists():
        return "già presente"
    order = (conditions.aggregate(m=Max("order"))["m"] or 0) + 1
    AutomationCondition.objects.create(
        rule=rule, order=order, field_name="salta_approvazione", operator="is_false",
        expected_value="", value_type="bool", compare_with_old=False, is_enabled=True,
    )
    return "aggiunta"


def _dividi_mail_per_autore(rule, AutomationAction):
    actions = list(rule.actions.order_by("order", "pk"))
    if any(CAPO_FIELD == ((a.config_json or {}).get("run_if") or {}).get("field_name") for a in actions):
        return "già divisa"
    divise = [a for a in actions if GROUP_FIELD == ((a.config_json or {}).get("run_if") or {}).get("field_name")]
    if divise:
        # Divisa dalla 0031 sul solo profilo CAR: passa al criterio «autore = capo».
        for a in divise:
            config = deepcopy(a.config_json)
            config["run_if"] = {**RUN_IF_CAR, **({"negate": True} if config["run_if"].get("negate") else {})}
            AutomationAction.objects.filter(pk=a.pk).update(config_json=config)
        return "criterio aggiornato"
    mails = [
        a for a in actions
        if a.is_enabled and a.action_type == "send_email"
        and CAPO_PLACEHOLDER in str((a.config_json or {}).get("cc") or "")
    ]
    if not mails:
        # Produzione: la mail andava solo ad assenza@ (CC vuoto), quindi la 0031 si
        # fermava qui e il caporeparto non era mai avvisato. Se la mail è una sola,
        # il caporeparto si aggiunge nella variante «inserita da ufficio assenze».
        mails = [a for a in actions if a.is_enabled and a.action_type == "send_email"]
    if len(mails) != 1 or (mails[0].config_json or {}).get("run_if"):
        raise ValueError("Mail di inserimento non univoca (o già condizionata): regola già personalizzata.")
    mail = mails[0]

    base = deepcopy(mail.config_json)
    solo_assenze = deepcopy(base)
    cc_rimasti = [p.strip() for p in str(base.get("cc") or "").split(",") if p.strip() and p.strip() != CAPO_PLACEHOLDER]
    solo_assenze["cc"] = ", ".join(cc_rimasti)
    if CAPO_PLACEHOLDER not in str(base.get("cc") or ""):
        base["cc"] = ", ".join([*cc_rimasti, CAPO_PLACEHOLDER])
    solo_assenze["run_if"] = dict(RUN_IF_CAR)
    base["run_if"] = {**RUN_IF_CAR, "negate": True}

    # Fa spazio subito dopo la mail originale per la variante «solo assenza@».
    for a in actions:
        if a.order > mail.order:
            AutomationAction.objects.filter(pk=a.pk).update(order=a.order + 1)
    AutomationAction.objects.filter(pk=mail.pk).update(
        config_json=base,
        description=(mail.description or "Avviso inserimento") + " — inserita da ufficio assenze: anche al caporeparto",
    )
    AutomationAction.objects.create(
        rule=rule, order=mail.order + 1, action_type="send_email", is_enabled=True, config_json=solo_assenze,
        description=(mail.description or "Avviso inserimento") + " — inserita dal caporeparto: solo assenza@",
    )
    return "divisa"


@transaction.atomic
def applica(*, models=None):
    """``models`` permette a una data migration di passare le classi storiche
    (AutomationRule, AutomationAction, AutomationCondition)."""
    AutomationRule, AutomationAction, AutomationCondition = models or (_Rule, _Action, _Condition)
    rules = {r.code: r for r in AutomationRule.objects.select_for_update().filter(code__in=[SKIP_RULE, APPROVED_RULE])}
    if SKIP_RULE not in rules or APPROVED_RULE not in rules:
        raise ValueError("Le due regole PA import di assenza@ non sono entrambe presenti.")
    for code, operation in ((SKIP_RULE, "insert"), (APPROVED_RULE, "update")):
        rule = rules[code]
        if (rule.source_code, rule.operation_type) != ("assenze", operation):
            raise ValueError(f"Regola {code}: sorgente/operazione diversa dall'atteso.")
    if not rules[SKIP_RULE].conditions.filter(field_name="salta_approvazione", operator="is_true", is_enabled=True).exists():
        raise ValueError("La regola di inserimento non filtra più su salta_approvazione: verificare nel designer.")
    return {
        "mail_inserimento": _dividi_mail_per_autore(rules[SKIP_RULE], AutomationAction),
        "condizione_dopo_approvazione": _escludi_salta_approvazione(rules[APPROVED_RULE], AutomationCondition),
    }


@transaction.atomic
def togli_doppione(*, models=None):
    """Solo la condizione che evita la seconda mail («Approvazione …») ad assenza@.

    Serve dove ``applica`` si è fermata perché la mail di inserimento non aveva il
    caporeparto in CC (regola personalizzata): lì la seconda mail è rimasta.
    """
    AutomationRule, _, AutomationCondition = models or (_Rule, _Action, _Condition)
    rules = {r.code: r for r in AutomationRule.objects.select_for_update().filter(code__in=[SKIP_RULE, APPROVED_RULE])}
    if SKIP_RULE not in rules or APPROVED_RULE not in rules:
        raise ValueError("Le due regole PA import di assenza@ non sono entrambe presenti.")
    if not rules[SKIP_RULE].conditions.filter(field_name="salta_approvazione", operator="is_true", is_enabled=True).exists():
        raise ValueError("La regola di inserimento non filtra più su salta_approvazione: verificare nel designer.")
    approvata = rules[APPROVED_RULE]
    if (approvata.source_code, approvata.operation_type) != ("assenze", "update"):
        raise ValueError(f"Regola {APPROVED_RULE}: sorgente/operazione diversa dall'atteso.")
    return {"condizione_dopo_approvazione": _escludi_salta_approvazione(approvata, AutomationCondition)}
