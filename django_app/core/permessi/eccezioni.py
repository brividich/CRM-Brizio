"""Eccezioni sulla singola persona: togliere o restringere un'azione che i suoi ruoli concedono.

Il caso: stesso ruolo dei colleghi (spesso dall'organigramma), ma una cosa che
lei non deve vedere. Invece di inventare un ruolo apposta, si scrive
un'eccezione: «per questa persona, su questo modulo, questa azione è negata»
oppure «al massimo i propri / del team».

Le eccezioni agiscono in due punti, come i ruoli:

- sui dati e sui pulsanti, nel motore (:func:`core.permessi.motore._decidi`);
- sulle pagine: le pagine che si aprono **solo** per l'azione negata ricevono un
  diniego sulla persona (``UserPermissionGrant`` con ``NOTA_ECCEZIONE``). Una
  pagina che serve anche a un'altra azione ancora concessa resta aperta. Le
  righe con questa nota sono le sole che si creano e cancellano qui: un
  override messo a mano dalla pagina ACL non viene toccato.

Ogni modifica va in AuditLog (``modulo="permessi"``).
"""
from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)

NOTA_ECCEZIONE = "eccezione sulla persona"
AZIONE_AUDIT = "permessi_eccezione_persona"


def pagine_di(modulo: str, azione: str, *, capacita=None, per_modulo=None) -> set[str]:
    """Code di pagina che l'azione accende sul modulo (stessa regola della sincronizzazione)."""
    from core.permessi.registro import AZIONE_CAPACITA
    from core.permessi.sync import capacita_permessi, codici_per_modulo, pagine_azioni_proprie
    from core.permission_taxonomy import CAPABILITY_IGNOTO

    capacita = capacita if capacita is not None else capacita_permessi()
    per_modulo = per_modulo if per_modulo is not None else codici_per_modulo()
    proprie = pagine_azioni_proprie().get(modulo, {})
    codes = per_modulo.get(modulo, [])
    capacita_azione = AZIONE_CAPACITA.get(azione)
    if not capacita_azione:
        return {c for c in codes if proprie.get(c) == azione}
    return {c for c in codes if c not in proprie and capacita.get(c, CAPABILITY_IGNOTO) in capacita_azione}


def pagine_da_chiudere(legacy_user_id: int, *, capacita=None, per_modulo=None) -> set[str]:
    """Pagine che restano aperte alla persona solo per un'azione che un'eccezione le nega."""
    from core.permessi.motore import _decidi, eccezioni_della_persona, ruoli_della_persona
    from core.permessi.registro import modulo as modulo_registrato
    from core.permessi.simulatore import contesto_di_ruoli
    from core.permessi.sync import capacita_permessi, codici_per_modulo

    negate = [k for k, (limite, _m) in eccezioni_della_persona(legacy_user_id).items() if not limite]
    if not negate:
        return set()
    capacita = capacita if capacita is not None else capacita_permessi()
    per_modulo = per_modulo if per_modulo is not None else codici_per_modulo()
    ctx = contesto_di_ruoli(ruoli_della_persona(legacy_user_id), legacy_user_id=legacy_user_id)
    if ctx.amministratore:
        return set()
    ctx.eccezioni = eccezioni_della_persona(legacy_user_id)
    chiudere: set[str] = set()
    for chiave, azione in negate:
        spec = modulo_registrato(chiave)
        if spec is None:
            continue
        pagine = pagine_di(chiave, azione, capacita=capacita, per_modulo=per_modulo)
        for altra in spec.azioni:
            if altra != azione and _decidi(ctx, chiave, altra).consentito:
                pagine -= pagine_di(chiave, altra, capacita=capacita, per_modulo=per_modulo)
        chiudere |= pagine
    return chiudere


def sincronizza_pagine_persona(legacy_user_id: int, *, capacita=None, per_modulo=None) -> tuple[int, int]:
    """Allinea i dinieghi di pagina della persona alle sue eccezioni. Ritorna (chiuse, riaperte)."""
    from core.models import UserPermissionGrant

    voluti = pagine_da_chiudere(legacy_user_id, capacita=capacita, per_modulo=per_modulo)
    esistenti = {
        g.permission_id: g for g in UserPermissionGrant.objects.filter(legacy_user_id=int(legacy_user_id))
    }
    chiuse = riaperte = 0
    with transaction.atomic():
        for code in sorted(voluti):
            grant = esistenti.get(code)
            if grant is None:
                UserPermissionGrant.objects.create(
                    legacy_user_id=int(legacy_user_id), permission_id=code, enabled=False, note=NOTA_ECCEZIONE
                )
                chiuse += 1
            elif grant.note == NOTA_ECCEZIONE and grant.enabled:
                grant.enabled = False
                grant.save(update_fields=["enabled", "updated_at"])
                chiuse += 1
        for code, grant in esistenti.items():
            if grant.note == NOTA_ECCEZIONE and code not in voluti:
                grant.delete()
                riaperte += 1
    return chiuse, riaperte


def ha_eccezioni(legacy_user_id: int) -> bool:
    from core.models import EccezionePermessoPersona, UserPermissionGrant

    return (
        EccezionePermessoPersona.objects.filter(legacy_user_id=int(legacy_user_id)).exists()
        or UserPermissionGrant.objects.filter(legacy_user_id=int(legacy_user_id), note=NOTA_ECCEZIONE).exists()
    )


def sincronizza_tutte(*, capacita=None, per_modulo=None) -> None:
    """Dopo una sincronizzazione della matrice: le pagine delle azioni possono essere cambiate."""
    from core.models import EccezionePermessoPersona, UserPermissionGrant
    from core.permessi.sync import capacita_permessi, codici_per_modulo

    persone = set(EccezionePermessoPersona.objects.values_list("legacy_user_id", flat=True))
    persone |= set(UserPermissionGrant.objects.filter(note=NOTA_ECCEZIONE).values_list("legacy_user_id", flat=True))
    if not persone:
        return
    capacita = capacita if capacita is not None else capacita_permessi()
    per_modulo = per_modulo if per_modulo is not None else codici_per_modulo()
    for legacy_user_id in sorted(persone):
        try:
            sincronizza_pagine_persona(legacy_user_id, capacita=capacita, per_modulo=per_modulo)
        except Exception:
            logger.exception("permessi: pagine delle eccezioni non allineate per %s", legacy_user_id)


def descrizione_limite(limite: str) -> str:
    from core.permessi.registro import AMBITI_LABEL

    return "negato" if not limite else f"al massimo «{AMBITI_LABEL.get(limite, limite)}»"


def salva(request, persona, modulo: str, azione: str, limite: str, motivo: str) -> str:
    """Crea o aggiorna l'eccezione. Ritorna il messaggio per l'utente; ValueError se i dati non vanno."""
    from core.audit import log_action
    from core.models import EccezionePermessoPersona
    from core.permessi.cache import invalida_permessi
    from core.permessi.registro import AMBITO_PROPRI, AMBITO_TEAM
    from core.permessi.registro import modulo as modulo_registrato

    spec = modulo_registrato(modulo)
    if spec is None or azione not in spec.azioni:
        raise ValueError("Scegli un modulo e un'azione dall'elenco.")
    if limite not in {"", AMBITO_PROPRI, AMBITO_TEAM}:
        raise ValueError("Esito non valido.")
    motivo = str(motivo or "").strip()[:255]
    if not motivo:
        raise ValueError("Scrivi il motivo: resta nel registro e serve al riesame degli accessi.")
    autore = request.user.get_full_name() or request.user.get_username()
    eccezione = EccezionePermessoPersona.objects.filter(
        legacy_user_id=persona.id, modulo=spec.chiave, azione=azione
    ).first()
    prima = None if eccezione is None else descrizione_limite(eccezione.ambito_massimo)
    if eccezione is None:
        eccezione = EccezionePermessoPersona(legacy_user_id=persona.id, modulo=spec.chiave, azione=azione)
    eccezione.ambito_massimo = limite
    eccezione.motivo = motivo
    eccezione.creata_da = autore[:150]
    eccezione.save()
    chiuse, riaperte = sincronizza_pagine_persona(persona.id)
    invalida_permessi()
    etichetta = f"{spec.nome} · {spec.etichetta_azione(azione)}"
    log_action(
        request, AZIONE_AUDIT, "permessi",
        {"persona": persona.nome, "legacy_user_id": persona.id, "voce": etichetta,
         "prima": prima or "-", "dopo": descrizione_limite(limite), "motivo": motivo,
         "pagine": {"chiuse": chiuse, "riaperte": riaperte}},
        oggetto_tipo="utente", oggetto_id=str(persona.id),
    )
    return f"Eccezione salvata per {persona.nome}: {etichetta} {descrizione_limite(limite)}."


def togli(request, persona, eccezione_id: int) -> str:
    from core.audit import log_action
    from core.models import EccezionePermessoPersona
    from core.permessi.cache import invalida_permessi
    from core.permessi.registro import modulo as modulo_registrato

    eccezione = EccezionePermessoPersona.objects.filter(id=eccezione_id, legacy_user_id=persona.id).first()
    if eccezione is None:
        raise ValueError("Eccezione non trovata.")
    spec = modulo_registrato(eccezione.modulo)
    etichetta = (f"{spec.nome} · {spec.etichetta_azione(eccezione.azione)}" if spec
                 else f"{eccezione.modulo}.{eccezione.azione}")
    prima = descrizione_limite(eccezione.ambito_massimo)
    eccezione.delete()
    chiuse, riaperte = sincronizza_pagine_persona(persona.id)
    invalida_permessi()
    log_action(
        request, AZIONE_AUDIT, "permessi",
        {"persona": persona.nome, "legacy_user_id": persona.id, "voce": etichetta,
         "prima": prima, "dopo": "come il ruolo", "motivo": "",
         "pagine": {"chiuse": chiuse, "riaperte": riaperte}},
        oggetto_tipo="utente", oggetto_id=str(persona.id),
    )
    return f"Eccezione tolta: per {persona.nome} {etichetta} torna come lo concede il ruolo."


def elenco(legacy_user_id: int) -> list[dict]:
    from core.models import EccezionePermessoPersona
    from core.permessi.registro import modulo as modulo_registrato

    righe = []
    for e in EccezionePermessoPersona.objects.filter(legacy_user_id=int(legacy_user_id)):
        spec = modulo_registrato(e.modulo)
        righe.append({
            "eccezione": e,
            "modulo": spec.nome if spec else e.modulo,
            "azione": spec.etichetta_azione(e.azione) if spec else e.azione,
            "esito": descrizione_limite(e.ambito_massimo),
        })
    return righe
