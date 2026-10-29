"""Simulatore dei permessi: confronto fra ruoli e prova di un ruolo prima di assegnarlo.

Nessuna scrittura. Le decisioni passano dalla stessa funzione del runtime
(``motore._decidi``) su un contesto costruito a mano, così la simulazione non
può dire una cosa e il portale farne un'altra.

- :func:`confronta_ruoli`: ruolo A contro ruolo B, modulo per modulo e azione per
  azione, ognuno da solo (senza ruolo base, senza organigramma).
- :func:`effetto_modifica`: la persona com'è oggi contro la persona con un ruolo
  in più e/o in meno. Si vedono solo le azioni che cambiano.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.permessi.motore import ContestoPermessi, Decisione, _decidi, _Ruolo, contesto_per


def _ruolo(g) -> _Ruolo:
    return _Ruolo(id=int(g.id), label=g.label, priority=int(g.priority or 0),
                  vede_tutto=bool(g.vede_tutto), amministratore=bool(g.amministratore))


def _carica_celle(ctx: ContestoPermessi) -> None:
    from core.models import RuoloPermessoModulo

    ctx.celle = {}
    if not ctx.ruoli:
        return
    for ruolo_id, mod, azione, consentito, ambito in RuoloPermessoModulo.objects.filter(
        ruolo_id__in=[r.id for r in ctx.ruoli]
    ).values_list("ruolo_id", "modulo", "azione", "consentito", "ambito"):
        ctx.celle[(int(ruolo_id), mod, azione)] = (bool(consentito), ambito)


def contesto_di_ruoli(gruppi, *, legacy_user_id=None, amministratore_legacy=False, superuser=False) -> ContestoPermessi:
    ruoli = sorted((_ruolo(g) for g in gruppi), key=lambda r: (-r.priority, r.label, r.id))
    ctx = ContestoPermessi(legacy_user_id=legacy_user_id, superuser=superuser,
                           amministratore=amministratore_legacy or any(r.amministratore for r in ruoli), ruoli=ruoli)
    _carica_celle(ctx)
    return ctx


def _decisioni(ctx: ContestoPermessi) -> dict[tuple[str, str], Decisione]:
    from core.permessi.registro import moduli_registrati

    return {(spec.chiave, azione): _decidi(ctx, spec.chiave, azione)
            for spec in moduli_registrati().values() for azione in spec.azioni}


def _uguali(a: Decisione, b: Decisione) -> bool:
    return (a.consentito, a.ambito if a.consentito else "") == (b.consentito, b.ambito if b.consentito else "")


@dataclass
class Confronto:
    moduli: list[dict] = field(default_factory=list)
    differenze: int = 0


def confronta_ruoli(ruolo_a, ruolo_b) -> Confronto:
    """Ruolo A contro ruolo B, ognuno da solo."""
    from core.permessi.registro import moduli_registrati

    da = _decisioni(contesto_di_ruoli([ruolo_a]))
    db = _decisioni(contesto_di_ruoli([ruolo_b]))
    out = Confronto()
    for spec in moduli_registrati().values():
        righe = []
        for azione in spec.azioni:
            a, b = da[(spec.chiave, azione)], db[(spec.chiave, azione)]
            if not a.consentito and not b.consentito:
                continue
            diverso = not _uguali(a, b)
            out.differenze += int(diverso)
            righe.append({"label": spec.etichetta_azione(azione), "a": a, "b": b, "diverso": diverso})
        if righe:
            out.moduli.append({"modulo": spec, "righe": righe, "diversi": sum(r["diverso"] for r in righe)})
    return out


def effetto_modifica(user, *, aggiungi=(), togli=()) -> list[dict]:
    """Cosa cambia per la persona aggiungendo e/o togliendo ruoli. Solo le differenze."""
    from core.legacy_utils import get_legacy_user, is_legacy_admin
    from core.models import AccessGroup
    from core.permessi.registro import moduli_registrati

    oggi = contesto_per(user)
    legacy = get_legacy_user(user)
    admin_legacy = bool(is_legacy_admin(legacy)) if legacy is not None else False
    ids = {r.id for r in oggi.ruoli}
    togli_ids = {int(x) for x in togli}
    nuovi_ids = (ids - togli_ids) | {int(x) for x in aggiungi}
    gruppi = list(AccessGroup.objects.filter(id__in=nuovi_ids, is_active=True))
    dopo = contesto_di_ruoli(gruppi, legacy_user_id=oggi.legacy_user_id, amministratore_legacy=admin_legacy,
                             superuser=oggi.superuser)
    dopo.eccezioni = dict(oggi.eccezioni)  # le eccezioni sulla persona restano anche cambiando ruolo
    prima_dec, dopo_dec = _decisioni(oggi), _decisioni(dopo)
    cambi = []
    for spec in moduli_registrati().values():
        for azione in spec.azioni:
            p, d = prima_dec[(spec.chiave, azione)], dopo_dec[(spec.chiave, azione)]
            if not _uguali(p, d):
                cambi.append({"modulo": spec, "label": spec.etichetta_azione(azione), "prima": p, "dopo": d,
                              "guadagna": d.consentito and not p.consentito, "perde": p.consentito and not d.consentito})
    return cambi
