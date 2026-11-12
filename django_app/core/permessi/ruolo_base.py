"""Il ruolo base «Operatore» vale solo per chi non ha altri ruoli (30/10/2026).

Prima ogni persona aveva sempre anche Operatore: dove la colonna del suo ruolo
taceva, decideva Operatore. Ora chi ha un ruolo prende soltanto la sua colonna,
quindi le caselle che servono a tutti (proprie assenze, notizie, schede di
sicurezza...) devono stare anche nelle colonne degli altri ruoli.

:func:`completa_dal_ruolo_base` le copia: per ogni ruolo, solo nelle caselle
vuote e solo i «si'» di Operatore; i permessi di pagina concessi a Operatore che
il ruolo non decide gia'. Non tocca niente di quello che il ruolo dice da se'.
Si usa una volta al passaggio (migrazione core 0105) e su ogni ruolo nuovo, poi
la colonna del ruolo si cambia a mano.
"""
from __future__ import annotations

from core.permessi.motore import PRESET_BASE
from core.permessi.registro import AZIONI_LETTURA

__all__ = ["NOTA_DAL_BASE", "PRESET_BASE", "completa_dal_ruolo_base"]

NOTA_DAL_BASE = "dal ruolo base"


def completa_dal_ruolo_base(ruoli=None, *, gruppi=None, celle=None, grant=None, dry_run: bool = False) -> list[dict]:
    """Copia i «si'» di Operatore nelle caselle vuote dei ruoli; ritorna cosa ha copiato.

    ``ruoli``: AccessGroup (o id) da completare; ``None`` = tutti i ruoli che non
    sono ne' il base ne' amministratori. ``gruppi``/``celle``/``grant`` sono i
    model (anche storici, da una migrazione).
    """
    if gruppi is None or celle is None or grant is None:
        from core.models import AccessGroup, GroupPermissionGrant, RuoloPermessoModulo

        gruppi, celle, grant = AccessGroup, RuoloPermessoModulo, GroupPermissionGrant
    base = gruppi.objects.filter(preset=PRESET_BASE).order_by("-is_active", "id").first()
    if base is None:
        return []
    bersagli = gruppi.objects.exclude(id=base.id).filter(amministratore=False)
    if ruoli is not None:
        bersagli = bersagli.filter(id__in=[getattr(r, "id", r) for r in ruoli])

    celle_base = list(celle.objects.filter(ruolo_id=base.id, consentito=True).values_list("modulo", "azione", "ambito"))
    pagine_base = list(grant.objects.filter(group_id=base.id, enabled=True).values_list("permission_id", "note"))
    esiti = []
    for ruolo in bersagli.order_by("-priority", "id"):
        presenti = set(celle.objects.filter(ruolo_id=ruolo.id).values_list("modulo", "azione"))
        nuove = [
            (modulo, azione, ambito)
            for modulo, azione, ambito in celle_base
            if (modulo, azione) not in presenti
            # «Vede tutto» si esprime gia' su vedere/esportare con «tutti»: un «propri» lo restringerebbe.
            and not (ruolo.vede_tutto and azione in AZIONI_LETTURA)
        ]
        decise = set(grant.objects.filter(group_id=ruolo.id).values_list("permission_id", flat=True))
        pagine = [(code, note) for code, note in pagine_base if code not in decise]
        if not dry_run:
            celle.objects.bulk_create([
                celle(ruolo_id=ruolo.id, modulo=m, azione=a, ambito=amb, consentito=True, note=NOTA_DAL_BASE)
                for m, a, amb in nuove
            ])
            # Il grant tiene la nota d'origine: quelli della matrice li riallinea «Sincronizza».
            grant.objects.bulk_create([
                grant(group_id=ruolo.id, permission_id=code, enabled=True, note=note or NOTA_DAL_BASE)
                for code, note in pagine
            ])
        if nuove or pagine:
            esiti.append({"ruolo": ruolo.label, "celle": [f"{m} · {a}" for m, a, _amb in nuove],
                          "pagine": [code for code, _note in pagine]})
    return esiti
