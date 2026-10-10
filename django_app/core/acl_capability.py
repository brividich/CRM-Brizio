"""Capacita' *effettiva* di un permesso: il nome piu' cio' che governa davvero.

`core.permission_taxonomy.capability_for_code` legge il nome del permesso. Non
basta, e il catalogo reale dice perche': 184 permessi su 847 non sono legati a
una rotta singola ma a un **prefisso di URL** (``/anagrafica/dipendenti``,
``/assets/componenti``), con ``match_strategy='prefix'``. Un permesso cosi'
governa tutto il sottoalbero tranne dove esiste un binding piu' specifico —
`core.acl_v2._find_canonical_binding` sceglie prima la rotta esatta, poi fra i
prefissi il piu' lungo. Quindi ``legacy.anagrafica.anagrafica_dipendenti``, che
"suona" come una lista, copre di fatto anche ``/anagrafica/dipendenti/nuovo/``
e ``/anagrafica/dipendenti/<id>/esposizione-rischio/add/``.

Chiamarlo "lettura" e metterlo dentro il livello "Solo lettura" sarebbe un
incidente. Qui si guarda quindi cosa quel permesso governa per davvero: si
enumerano le rotte del progetto, si chiede al resolver **vero** chi le copre, e
la capacita' del permesso viene alzata alla piu' alta fra quelle delle rotte che
gli ricadono sotto. Solo alzata, mai abbassata; e un permesso che resta
illeggibile resta ``ignoto``, cioe' fuori da tutti i livelli tranne l'ultimo.

Come tutto il resto della tassonomia, non e' un confine di sicurezza: decide
quali interruttori accende un livello nella pagina Accessi, non chi passa. La
decisione ACL resta in `core.acl_resolver`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.core.cache import cache
from django.db import DatabaseError

from core.permission_taxonomy import (
    CAPABILITY_IGNOTO,
    capability_for_code,
    capability_for_name,
    strongest_capability,
)

# v2: l'indice porta anche i collegamenti permesso -> rotte. Chiave nuova perche'
# in produzione la cache e' su database: un oggetto v1 in cache non ha i campi.
CACHE_KEY = "acl_capability_index_v2"
CACHE_TTL_SECONDS = 300

STALE_MISSING_ROUTE = "rotta_inesistente"
STALE_SHADOWED = "oscurato"


@dataclass
class CapabilityIndex:
    """Capacita' per code, piu' la traccia di come ci si e' arrivati."""

    capabilities: dict[str, str] = field(default_factory=dict)
    # code -> capacita' ricavata dal solo nome del permesso.
    by_name: dict[str, str] = field(default_factory=dict)
    # code -> [(route_name, capacita')] delle rotte coperte per prefisso.
    subtree_routes: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    # Collegamenti reali: code -> rotte con nome che il resolver gli assegna
    # (binding esatto o prefisso vincente), nell'ordine dell'urlconf.
    governed_routes: dict[str, list[str]] = field(default_factory=dict)
    # Code con almeno un binding attivo, governi o no qualche rotta.
    bound_codes: set[str] = field(default_factory=set)
    # Binding attivi che non decidono nessuna rotta: puntano a un nome di rotta
    # che non esiste piu', oppure un binding piu' specifico li scavalca sempre.
    stale_bindings: list[dict] = field(default_factory=list)
    routes_total: int = 0
    routes_bound: int = 0

    def get(self, code: str, default: str = CAPABILITY_IGNOTO) -> str:
        return self.capabilities.get(code, default)

    def promoted(self) -> dict[str, tuple[str, str]]:
        """code -> (capacita' dal nome, capacita' effettiva) dove le due differiscono."""
        return {
            code: (self.by_name[code], capability)
            for code, capability in self.capabilities.items()
            if self.by_name.get(code) and self.by_name[code] != capability
        }

    def unclassified(self) -> list[str]:
        return sorted(
            code for code, capability in self.capabilities.items() if capability == CAPABILITY_IGNOTO
        )


def _named_routes():
    """Le rotte con nome del progetto, dallo stesso enumeratore del bootstrap.

    Riusare `_collect_named_routes` invece di riscrivere il walk degli urlconf
    tiene una sola definizione di "sample path", che e' esattamente cio' su cui
    i binding di prefisso vengono confrontati.
    """
    from core.management.commands.bootstrap_acl_v2 import _collect_named_routes

    return _collect_named_routes()


def build_capability_index() -> CapabilityIndex:
    """Calcola l'indice leggendo catalogo, binding e urlconf. Nessuna scrittura."""
    from core.acl_v2 import _find_canonical_binding
    from core.models import PermissionDefinition, RoutePermissionBinding

    index = CapabilityIndex()
    permissions = {
        str(row.code): str(row.module or "")
        for row in PermissionDefinition.objects.filter(is_active=True).only("code", "module")
    }
    if not permissions:
        return index

    index.by_name = {
        code: capability_for_code(code, module) for code, module in permissions.items()
    }

    bindings = list(
        RoutePermissionBinding.objects.filter(is_active=True).select_related("permission")
    )
    index.bound_codes = {str(binding.permission_id) for binding in bindings}

    routes = _named_routes() if bindings else []
    route_names = {str(row.route_name).lower() for row in routes}
    used_binding_ids: set[int] = set()
    index.routes_total = len(routes)
    for row in routes:
        binding, matched_by = _find_canonical_binding(
            route_name=row.route_name, path_norm=row.sample_path, bindings=bindings
        )
        if binding is None:
            continue
        used_binding_ids.add(int(binding.pk))
        index.routes_bound += 1
        code = str(binding.permission_id)
        index.governed_routes.setdefault(code, []).append(row.route_name)
        # Solo i match per prefisso dicono qualcosa di nuovo sulla capacita':
        # se la rotta ha un binding proprio, il permesso e' gia' classificato
        # dal suo nome.
        if matched_by != "path_pattern" or code not in permissions:
            continue
        capability = capability_for_name(row.route_name)
        if capability == CAPABILITY_IGNOTO:
            continue
        index.subtree_routes.setdefault(code, []).append((row.route_name, capability))

    for binding in bindings:
        if int(binding.pk) in used_binding_ids:
            continue
        route_name = str(binding.route_name or "").strip()
        index.stale_bindings.append(
            {
                "id": int(binding.pk),
                "permission": str(binding.permission_id),
                "target": route_name or str(binding.path_pattern or ""),
                "match": str(binding.match_strategy or ""),
                "reason": (
                    STALE_MISSING_ROUTE
                    if route_name and route_name.lower() not in route_names
                    else STALE_SHADOWED
                ),
            }
        )
    index.stale_bindings.sort(key=lambda row: (row["reason"], row["permission"], row["target"]))

    for code, from_name in index.by_name.items():
        if from_name == CAPABILITY_IGNOTO:
            # Un permesso illeggibile resta illeggibile: l'incertezza non si
            # risolve guardando le rotte, si dichiara.
            index.capabilities[code] = CAPABILITY_IGNOTO
            continue
        governed = [capability for _route, capability in index.subtree_routes.get(code, [])]
        index.capabilities[code] = strongest_capability([from_name, *governed])
    return index


def capability_index(*, use_cache: bool = True) -> CapabilityIndex:
    """Indice con cache breve: la pagina Accessi lo chiede a ogni render."""
    if not use_cache:
        return build_capability_index()
    cached = cache.get(CACHE_KEY)
    if isinstance(cached, CapabilityIndex):
        return cached
    try:
        index = build_capability_index()
    except DatabaseError:
        # Meglio nessuna classificazione che una pagina rotta: chi chiama
        # ricade sulla capacita' del solo nome.
        return CapabilityIndex()
    cache.set(CACHE_KEY, index, timeout=CACHE_TTL_SECONDS)
    return index


def invalidate_capability_index() -> None:
    cache.delete(CACHE_KEY)
