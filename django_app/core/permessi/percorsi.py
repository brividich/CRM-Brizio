"""Dal percorso di una pagina ai permessi che la governano.

Per la ricerca nella matrice dei ruoli: si scrive il percorso (quello che segue
l'indirizzo del portale) e si trovano le righe «pagina per pagina» da guardare.
La pagina esatta passa dalle stesse funzioni del runtime (gate delle API e
``resolve_canonical_target``), così il permesso indicato è quello che il portale
controlla davvero. Sola lettura.
"""
from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlsplit

# hub.azienda.it/pagina: indirizzo incollato senza https://
_HOST_RE = re.compile(r"^[^/\s]+\.[^/\s]+(?=/)")


def normalizza_percorso(testo: str) -> str:
    """Toglie indirizzo del sito, query e spazi: resta il percorso, con la «/» iniziale."""
    valore = str(testo or "").strip()
    if not valore:
        return ""
    if "://" in valore:
        valore = urlsplit(valore).path
    else:
        valore = _HOST_RE.sub("", valore).split("?", 1)[0].split("#", 1)[0]
    return "/" + valore.lstrip("/")


@lru_cache(maxsize=1)
def _rotte() -> tuple:
    from core.route_probe import iter_route_samples

    return tuple(iter_route_samples())


def trova_permessi_percorso(testo: str) -> list[dict]:
    """Righe per un percorso: prima la pagina esatta, poi quelle che lo contengono.

    Ogni riga: percorso, rotta, code ("" se nessun permesso), label, modulo,
    modulo_nome ("" se il permesso non sta in nessun modulo della matrice),
    esatta, comune (pagina aperta a tutti gli utenti, senza controllo di ruolo).
    """
    from core.acl import normalize_acl_path
    from core.acl_v2 import _find_canonical_binding, resolve_route_name
    from core.middleware import is_acl_exempt_path, is_acl_shared_path, resolve_acl_gate_target_path
    from core.models import RoutePermissionBinding
    from core.permessi.registro import moduli_registrati
    from core.permessi.sync import codici_per_modulo

    percorso = normalizza_percorso(testo)
    if not percorso:
        return []
    specs = moduli_registrati()
    modulo_di = {code: chiave for chiave, codes in codici_per_modulo().items() for code in codes}
    bindings = list(
        RoutePermissionBinding.objects.filter(is_active=True).select_related("permission").order_by("priority", "id")
    )

    def binding_di(percorso_pagina: str, rotta: str = ""):
        bersaglio = resolve_acl_gate_target_path(percorso_pagina)
        # Un'API col suo gate vale come la pagina del gate, rotta compresa.
        nome = resolve_route_name(bersaglio) if bersaglio != percorso_pagina or not rotta else rotta
        return _find_canonical_binding(route_name=nome, path_norm=bersaglio, bindings=bindings)[0], nome

    def riga(percorso_pagina: str, rotta: str, binding, *, esatta: bool) -> dict:
        permesso = binding.permission if binding is not None else None
        code = permesso.code if permesso is not None else ""
        modulo = modulo_di.get(code, "")
        spec = specs.get(modulo)
        return {
            "percorso": percorso_pagina,
            "rotta": rotta,
            "code": code,
            "label": (permesso.label if permesso is not None else "") or code,
            "modulo": modulo,
            "modulo_nome": spec.nome if spec is not None else "",
            "esatta": esatta,
            "comune": bool(is_acl_shared_path(percorso_pagina) or is_acl_exempt_path(percorso_pagina)),
        }

    righe: list[dict] = []
    percorso_norm = normalize_acl_path(percorso)
    binding, nome = binding_di(percorso_norm)
    if nome or binding is not None:
        righe.append(riga(percorso_norm, nome, binding, esatta=True))

    cercato = percorso.strip("/").lower()
    visti = {percorso_norm}
    if len(cercato) >= 2:
        for rotta in _rotte():
            if cercato not in rotta.route.lower() or rotta.name.startswith("admin:"):
                continue
            mostrato = normalize_acl_path("/" + rotta.route)
            if mostrato in visti:
                continue
            visti.add(mostrato)
            binding, _nome = binding_di(normalize_acl_path(rotta.path), rotta.name)
            righe.append(riga(mostrato, rotta.name, binding, esatta=False))
    righe.sort(key=lambda r: (not r["esatta"], r["percorso"]))
    return righe
