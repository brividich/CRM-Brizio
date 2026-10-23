"""Assemblea sindacale e Flessibilità con «Salta approvazione»: niente doppia mail ad assenza@.

Con «Salta approvazione» la regola di inserimento manda già la mail ad assenza@
e poi porta la richiesta ad approvata: quel passaggio fa scattare anche
«Assemblea sindacale approvata» e «Flessibilità approvata», che scrivono di
nuovo ad assenza@.

Dopo: in quelle due regole ogni mail che va ad assenza@ si divide in due rami.
Senza «Salta approvazione» parte com'era; con «Salta approvazione» parte agli
stessi destinatari tranne assenza@ (HR, CAR, dipendente restano avvisati). Se
assenza@ era l'unico destinatario, il primo indirizzo in CC prende il suo posto;
se non resta nessuno il ramo non viene creato.

Fail-closed per regola: una regola assente o già personalizzata resta com'è e
lo si scrive nel risultato.
"""
from copy import deepcopy

from django.db import transaction

from .models import AutomationAction as _Action, AutomationRule as _Rule

REGOLE = ("assenze-pa-assemblea-sindacale-avviso", "assenze-pa-flessibilita-avviso")
CASELLA = "assenza@"
RUN_IF_SALTA = {"field_name": "salta_approvazione", "operator": "is_true", "expected_value": "", "value_type": "bool"}


def _indirizzi(valore) -> list[str]:
    return [p.strip() for p in str(valore or "").replace(";", ",").split(",") if p.strip()]


def _senza_casella(indirizzi: list[str]) -> list[str]:
    return [a for a in indirizzi if not a.lower().startswith(CASELLA)]


def _dividi(rule, AutomationAction) -> str:
    actions = list(rule.actions.order_by("order", "pk"))
    if any(((a.config_json or {}).get("run_if") or {}).get("field_name") == "salta_approvazione" for a in actions):
        return "già divisa"
    mails = [
        a for a in actions
        if a.is_enabled and a.action_type == "send_email"
        and any(x.lower().startswith(CASELLA) for x in _indirizzi((a.config_json or {}).get("to"))
                + _indirizzi((a.config_json or {}).get("cc")))
    ]
    if not mails:
        return "nessuna mail ad assenza@"
    if any((m.config_json or {}).get("run_if") for m in mails):
        return "saltata: mail già condizionata, da sistemare nel designer"

    divise = 0
    for mail in mails:
        mail.refresh_from_db()  # l'ordine può essere slittato per la mail precedente
        base = deepcopy(mail.config_json)
        to = _senza_casella(_indirizzi(base.get("to")))
        cc = _senza_casella(_indirizzi(base.get("cc")))
        if not to and cc:
            to, cc = [cc[0]], cc[1:]
        base["run_if"] = {**RUN_IF_SALTA, "negate": True}
        AutomationAction.objects.filter(pk=mail.pk).update(config_json=base)
        if not to:
            continue
        variante = deepcopy(mail.config_json)
        variante["to"] = ", ".join(to)
        variante["cc"] = ", ".join(cc)
        variante["run_if"] = dict(RUN_IF_SALTA)
        for a in rule.actions.filter(order__gt=mail.order).order_by("-order"):
            AutomationAction.objects.filter(pk=a.pk).update(order=a.order + 1)
        AutomationAction.objects.create(
            rule=rule, order=mail.order + 1, action_type="send_email", is_enabled=True, config_json=variante,
            description=(mail.description or "Avviso") + " — con salta approvazione: senza assenza@",
        )
        divise += 1
    return f"divisa ({divise} mail)"


@transaction.atomic
def applica(*, models=None) -> dict:
    """``models`` permette a una data migration di passare le classi storiche (AutomationRule, AutomationAction)."""
    AutomationRule, AutomationAction = models or (_Rule, _Action)
    esito = {}
    regole = {r.code: r for r in AutomationRule.objects.select_for_update().filter(code__in=REGOLE)}
    for code in REGOLE:
        rule = regole.get(code)
        if rule is None:
            esito[code] = "assente"
        elif (rule.source_code, rule.operation_type) != ("assenze", "update"):
            esito[code] = "saltata: sorgente/operazione diversa dall'atteso"
        else:
            esito[code] = _dividi(rule, AutomationAction)
    return esito
