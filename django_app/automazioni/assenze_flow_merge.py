"""Explicit, reversible merge of the two audited absence approval flows."""
from copy import deepcopy

from django.db import transaction
from .models import AutomationRule, AutomationAction, AutomationCondition

LEGACY = "assenze-pa-richiesta-approvazione-caporeparto"
BRANCHED = "au-assenze-unico-branch-per-tipo"
MERGED = "assenze-approvazione-unificata"
MARKER = "merge-assenze-20260930"


def _config(node):
    return node.get("config_json") or node


def _condition_key(condition):
    return tuple(getattr(condition, k) for k in
                 ("field_name", "operator", "expected_value", "value_type", "compare_with_old"))


def combined_config(legacy, branched):
    """Keep routing/messages from the branched flow and state changes from legacy.

    Reject unknown shapes rather than guessing how to merge business behavior.
    All arguments are dictionaries; originals are never modified.
    """
    root = deepcopy(branched)
    state_actions = {}
    for decision in ("approved_actions", "rejected_actions"):
        actions = legacy.get(decision, [])
        allowed = {"update_trigger_record", "split_assenza_giornaliera", "write_log", "send_email"}
        if not actions or any(a.get("action_type") not in allowed for a in actions):
            raise ValueError("Azioni legacy non riconosciute: conversione interrotta.")
        state_actions[decision] = [deepcopy(a) for a in actions if a["action_type"] != "send_email"]
        if not any(a["action_type"] == "update_trigger_record" for a in state_actions[decision]):
            raise ValueError("Manca l'aggiornamento dello stato nel flusso legacy.")

    def visit(node):
        cfg = _config(node)
        kind = node.get("action_type")
        if kind == "branch":
            if not {"then_actions", "else_actions"}.issubset(cfg) or {"if_true_actions", "if_false_actions"}.intersection(cfg):
                raise ValueError("Schema del ramo non riconosciuto.")
            for key in ("then_actions", "else_actions"):
                for child in cfg.get(key, []):
                    visit(child)
        elif kind == "send_approval":
            for key in ("approved_actions", "rejected_actions"):
                children = cfg.get(key, [])
                if len(children) == 1 and children[0].get("action_type") == "send_approval":
                    visit(children[0])
                elif children and all(a.get("action_type") == "send_email" for a in children):
                    cfg[key] = deepcopy(state_actions[key]) + children
                else:
                    raise ValueError("Ramo approvativo inatteso: conversione interrotta.")
        else:
            raise ValueError("Nodo del flusso ramificato non riconosciuto.")

    visit({"action_type": "branch", "config_json": root})
    # The final 'other absence type' branch becomes the original simple workflow.
    cursor = root
    while True:
        if cursor.get("condition_field") != "tipo_assenza" or cursor.get("condition_operator") != "equals":
            raise ValueError("Catena dei tipi di assenza non riconosciuta.")
        children = cursor.get("else_actions", [])
        if not children:
            cursor["else_actions"] = [{"action_type": "send_approval", "config_json": deepcopy(legacy),
                                       "description": "Altri tipi: approvazione del caporeparto"}]
            return root
        if len(children) != 1 or children[0].get("action_type") != "branch":
            raise ValueError("Fallback già personalizzato: conversione interrotta.")
        cursor = _config(children[0])


@transaction.atomic
def merge_flows(*, apply=False):
    rules = {r.code: r for r in AutomationRule.objects.select_for_update().filter(code__in=[LEGACY, BRANCHED, MERGED])}
    if LEGACY not in rules or BRANCHED not in rules:
        raise ValueError("Le due regole censite non sono entrambe presenti.")
    old, branch = rules[LEGACY], rules[BRANCHED]
    if MERGED in rules:
        merged = rules[MERGED]
        if merged.import_flow_name == MARKER and not old.is_active and not branch.is_active:
            return {"created": False, "rule_id": merged.pk}
        raise ValueError("Codice unificato già presente o regole originali riattivate: verificare nel designer.")
    for rule in (old, branch):
        if not rule.is_active or rule.is_draft or (rule.source_code, rule.operation_type, rule.trigger_scope) != ("assenze", "insert", "all_inserts"):
            raise ValueError("Stato o trigger delle regole diverso dall'audit: conversione interrotta.")
        if rule.exclusion_group or rule.watched_field:
            raise ValueError("Regole già personalizzate con gruppo/campo osservato.")
    old_actions = list(old.actions.filter(is_enabled=True))
    branch_actions = list(branch.actions.filter(is_enabled=True))
    if len(old_actions) != 1 or old_actions[0].action_type != "send_approval" or len(branch_actions) != 1 or branch_actions[0].action_type != "branch":
        raise ValueError("Struttura delle azioni diversa dall'audit.")
    conditions = list(old.conditions.filter(is_enabled=True))
    keys = {_condition_key(c) for c in conditions}
    expected = {("salta_approvazione", "is_false", "", "bool", False),
                ("moderation_status", "equals", "2", "int", False),
                ("capo_email", "is_not_empty", "", "string", False)}
    if keys != expected:
        raise ValueError("Condizioni legacy diverse dall'audit: conversione interrotta.")
    if any(_condition_key(c) not in keys for c in branch.conditions.filter(is_enabled=True)):
        raise ValueError("Condizioni del flusso ramificato non compatibili con quelle legacy.")
    config = combined_config(old_actions[0].config_json, branch_actions[0].config_json)
    if not apply:
        return {"created": False, "preview": True, "conditions": len(conditions)}
    merged = AutomationRule.objects.create(code=MERGED, name="Assenze — approvazione unificata",
        description="Unione dei percorsi per tipo/durata con aggiornamento stato, suddivisione giornaliera e fallback al caporeparto. Originali conservati disattivati.",
        source_code="assenze", operation_type="insert", trigger_scope="all_inserts",
        is_active=True, is_draft=False, stop_on_first_failure=True, import_flow_name=MARKER)
    for c in conditions:
        values = {f.name: getattr(c, f.name) for f in AutomationCondition._meta.fields if f.name not in {"id", "rule"}}
        AutomationCondition.objects.create(rule=merged, **values)
    AutomationAction.objects.create(rule=merged, order=1, action_type="branch", config_json=config,
                                    description="Tipo assenza, durata, approvazione e registrazione esito")
    AutomationRule.objects.filter(pk__in=[old.pk, branch.pk]).update(is_active=False)
    return {"created": True, "rule_id": merged.pk}
