"""Regole «non applicabile» per la mappatura CPE: driver, runtime, language pack non hanno CVE da seguire.

Una regola dice «i software il cui nome contiene X (eventualmente solo di questo produttore) sono non
applicabili». Si applica subito e a ogni import dell'inventario, con tre limiti di sicurezza:

- non tocca mai una decisione già presa (confermato o non applicabile);
- non tocca i software per cui esiste già una CVE dal nome simile (proposta): lì decide una persona;
- un software escluso da una regola che più avanti riceve una proposta torna «da decidere» in pagina.

Eliminare la regola riapre i software che aveva escluso (``origin="regola"`` + ``na_rule``).
"""
from __future__ import annotations

import re

from django.utils import timezone

from security.models import SoftwareCpeMapping, SoftwareInstallation, SoftwareNaRule

MIN_PATTERN_LEN = 3


def normalize_pattern(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def rule_matches(rule, vendor, product):
    if rule.vendor and normalize_pattern(vendor) != rule.vendor:
        return False
    return rule.pattern in normalize_pattern(product)


def apply_rules(rules=None, pairs=None):
    """Segna non applicabili i software aperti che ricadono in una regola. Ritorna {rule_id: quanti}."""
    from security.services.cpe_auto import known_cpe_pairs, proposals

    rules = list(SoftwareNaRule.objects.all() if rules is None else rules)
    if not rules:
        return {}
    pairs = known_cpe_pairs() if pairs is None else pairs
    existing = {(m.vendor, m.product): m for m in SoftwareCpeMapping.objects.all()}
    products = SoftwareInstallation.objects.filter(still_detected=True).values_list("vendor", "product").distinct()
    applied = {}
    now = timezone.now()
    for vendor, product in products:
        mapping = existing.get((vendor, product))
        if mapping and (mapping.confirmed or mapping.not_applicable):
            continue
        rule = next((r for r in rules if rule_matches(r, vendor, product)), None)
        if rule is None or proposals(vendor, product, pairs):
            continue
        mapping = mapping or SoftwareCpeMapping(vendor=vendor, product=product)
        mapping.confirmed, mapping.not_applicable = False, True
        mapping.origin, mapping.na_rule = SoftwareCpeMapping.ORIGIN_RULE, rule
        mapping.confirmed_by, mapping.confirmed_at = None, now
        mapping.save()
        applied[rule.pk] = applied.get(rule.pk, 0) + 1
    return applied


def release_rule(rule):
    """Riapre i software esclusi dalla regola (prima di eliminarla). Ritorna quanti."""
    return SoftwareCpeMapping.objects.filter(na_rule=rule, origin=SoftwareCpeMapping.ORIGIN_RULE).update(
        not_applicable=False, origin=SoftwareCpeMapping.ORIGIN_MANUAL, na_rule=None, confirmed_at=None,
    )
