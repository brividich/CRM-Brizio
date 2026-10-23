"""Chi può aprire una pagina: l'elenco delle persone, non dei ruoli.

Per ogni persona attiva si chiede al resolver unico (``core.acl_resolver``) la
stessa decisione che prende il middleware, quindi l'esito coincide con quello
reale (amministratore, eccezione sulla persona, ruolo del portale, compat legacy).
Per i ruoli del portale si dice anche da dove arrivano: a mano, dall'organigramma
(con il ruolo d'organigramma e la tipologia: principale, secondario, ad interim)
o il ruolo base.

Calcolo su richiesta (una decisione per persona), solo per gli amministratori.
"""
from __future__ import annotations

LIVELLI = {
    "superuser_bypass": "superuser",
    "legacy_admin_bypass": "amministratore",
    "user_override": "eccezione sulla persona",
    "group_grant": "ruolo del portale",
    "role_grant": "ruolo storico",
    "legacy_compat": "regole storiche",
}


def chi_puo_aprire(permission_code: str) -> dict:
    from core.acl_resolver import resolve_permission_decision
    from core.legacy_models import UtenteLegacy
    from core.models import AccessGroupMembership, PermissionDefinition
    from core.permessi.organigramma import provenienze_per_utenti
    from core.permessi.scadenze import q_appartenenze_valide

    permesso = PermissionDefinition.objects.filter(code=permission_code).first()
    if permesso is None:
        return {"permesso": None, "persone": [], "negati": 0}
    utenti = list(UtenteLegacy.objects.filter(attivo=True).order_by("nome"))
    ids = [u.id for u in utenti]
    da_org = provenienze_per_utenti(ids)
    a_mano = set(AccessGroupMembership.objects.filter(q_appartenenze_valide(), legacy_user_id__in=ids)
                 .values_list("legacy_user_id", "group_id"))
    persone, negati = [], 0
    for u in utenti:
        d = resolve_permission_decision(permission_code=permesso.code, legacy_user=u, permission=permesso)
        if not d.allowed:
            negati += 1
            continue
        motivo = LIVELLI.get(d.level, d.level or "")
        provenienza = ""
        if d.group_grant:
            gid = int(d.group_grant.get("group_id") or 0)
            motivo = f"ruolo «{d.group_grant.get('group_label', '')}»"
            if (u.id, gid) in a_mano:
                provenienza = "a mano"
            elif gid in da_org.get(u.id, {}):
                provenienza = "organigramma: " + ", ".join(sorted(da_org[u.id][gid]))
            else:
                provenienza = "ruolo base"
        persone.append({"utente": u, "motivo": motivo, "provenienza": provenienza})
    return {"permesso": permesso, "persone": persone, "negati": negati}
