"""Collegamento automatico software dell'inventario ↔ CPE di NVD, solo quando il nome non lascia dubbi.

I CPE candidati sono quelli che compaiono nelle CVE già scaricate da NVD (``SecurityCveRecord``):
si collega solo ciò che serve a valutare CVE reali. Un prodotto dell'inventario viene collegato da
solo quando c'è **un solo** CPE candidato e il nome coincide (lettere e cifre, maiuscole ignorate):

- produttore e prodotto coincidono: «google» + «google chrome» ↔ ``google:chrome`` (il prodotto può
  ripetere il produttore) oppure «7-zip» ↔ ``7-zip:7-zip``;
- oppure il prodotto coincide esattamente con un nome di prodotto NVD che nessun altro produttore usa
  (almeno 4 caratteri): «igor pavlov» + «7-zip» ↔ ``7-zip:7-zip``.

Tutto il resto resta una **proposta** da confermare. Un collegamento automatico è marcato
``origin="auto"``; se una persona lo annulla diventa ``auto_rifiutato`` e il sistema non lo rifà.
Le decisioni delle persone (confermato, non applicabile) non vengono mai toccate.
"""
from __future__ import annotations

import re
from collections import defaultdict

from django.utils import timezone

from security.models import SecurityCveRecord, SoftwareCpeMapping, SoftwareInstallation

MIN_PRODUCT_ONLY_LEN = 4


def _n(text):
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def known_cpe_pairs():
    """Coppie (vendor, product) NVD presenti nelle CVE scaricate."""
    pairs = set()
    for configurations in SecurityCveRecord.objects.exclude(configurations=[]).values_list("configurations", flat=True):
        for c in configurations or []:
            if c.get("vendor") and c.get("product"):
                pairs.add((c["vendor"].lower(), c["product"].lower()))
    return pairs


def match(vendor, product, pairs, by_product=None):
    """(cpe_vendor, cpe_product) se il collegamento è certo, altrimenti None."""
    nv, np_ = _n(vendor), _n(product)
    if not np_:
        return None
    full = {(cv, cp) for cv, cp in pairs if _n(cv) == nv and np_ in (_n(cp), _n(cv) + _n(cp))}
    if len(full) == 1:
        return next(iter(full))
    if full:
        return None  # più CPE dello stesso produttore con lo stesso nome: decide una persona
    if by_product is None:
        by_product = _by_product(pairs)
    same_name = by_product.get(np_, set())
    if len(np_) >= MIN_PRODUCT_ONLY_LEN and len(same_name) == 1:
        return next(iter(same_name))
    return None


def _by_product(pairs):
    out = defaultdict(set)
    for cv, cp in pairs:
        out[_n(cp)].add((cv, cp))
    return out


def auto_link(pairs=None):
    """Collega i prodotti presenti nell'inventario dove il nome è certo. Ritorna quanti collegamenti nuovi."""
    pairs = known_cpe_pairs() if pairs is None else pairs
    if not pairs:
        return 0
    by_product = _by_product(pairs)
    existing = {(m.vendor, m.product): m for m in SoftwareCpeMapping.objects.all()}
    products = SoftwareInstallation.objects.filter(still_detected=True).values_list("vendor", "product").distinct()
    linked = 0
    now = timezone.now()
    for vendor, product in products:
        mapping = existing.get((vendor, product))
        if mapping and (mapping.confirmed or mapping.not_applicable or mapping.origin == SoftwareCpeMapping.ORIGIN_AUTO_REJECTED):
            continue
        found = match(vendor, product, pairs, by_product)
        if not found:
            continue
        mapping = mapping or SoftwareCpeMapping(vendor=vendor, product=product)
        mapping.cpe_vendor, mapping.cpe_product = found
        mapping.confirmed, mapping.not_applicable = True, False
        mapping.origin = SoftwareCpeMapping.ORIGIN_AUTO
        mapping.confirmed_by, mapping.confirmed_at = None, now
        mapping.save()
        linked += 1
    return linked


def proposals(vendor, product, pairs):
    """Proposte (non certe) per un prodotto: nomi che si contengono l'un l'altro."""
    np_ = _n(product)
    if not np_:
        return []
    out = [f"{cv}:{cp}" for cv, cp in pairs if (np_ in (_n(cv) + _n(cp)) or _n(cp) in np_) and len(_n(cp)) >= 3]
    return sorted(out)[:5]
