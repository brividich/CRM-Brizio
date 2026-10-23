"""Struttura → scheda macchina: chi è abilitato a lavorare su un asset.

Riquadro «Operatori abilitati» della scheda asset. Fonte unica: la skill matrix
(``AbilitazioneMacchina`` sull'asset), le mansioni lavorative legate alla
macchina (``CompetenzaSkm.asset``) e le soglie di copertura AS/EN 9100 sull'asset.

I numeri (operativi, in addestramento, copertura) li vede chi apre la scheda; i
nomi con il livello solo chi può leggere la skill matrix.
"""
from __future__ import annotations

from ..models import AbilitazioneMacchina, CompetenzaSkm, SkillMatrixConfig, SogliaCopertura, ordinale_livello


def puo_vedere_nomi(request) -> bool:
    """Nomi e livelli: amministrazione anagrafica, dati HR o lettura skill matrix."""
    from ..acl_bootstrap import PERM_SKM_VIEW
    from ..views import _check_hr_permission, _check_skm_permission, _is_anagrafica_admin
    return (_is_anagrafica_admin(request) or _check_hr_permission(request)
            or _check_skm_permission(request, PERM_SKM_VIEW))


def operatori(asset, *, con_nomi: bool) -> dict | None:
    """Abilitati sull'asset, mansioni della macchina e copertura. ``None`` se non c'è niente."""
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    from .skillmatrix_copertura import valuta_soglia

    abil = list(AbilitazioneMacchina.objects.filter(asset=asset, in_lista=True).select_related("competenza"))
    mansioni = list(CompetenzaSkm.objects.filter(asset=asset).order_by("display"))
    soglie = [valuta_soglia(s) for s in SogliaCopertura.objects.filter(asset=asset, attiva=True).order_by("ordine", "nome")]
    if not (abil or mansioni or soglie):
        return None
    soglia = SkillMatrixConfig.get_instance().soglia_operativa_ordinale
    nomi = {}
    if con_nomi and abil:
        nomi = {int(r["id"]): naming.nome_completo(r.get("nome"), r.get("cognome"))
                for r in fetch_anagrafica_rows(ids=[a.legacy_anagrafica_id for a in abil])}
    persone = []
    for a in abil:
        semaforo = ("sospesa" if a.stato == AbilitazioneMacchina.STATO_SOSPESA
                    else "operativa" if a.is_operativa(soglia) else "addestramento")
        persone.append({
            "legacy_id": a.legacy_anagrafica_id,
            "nome": nomi.get(a.legacy_anagrafica_id) or f"#{a.legacy_anagrafica_id}",
            "livello": a.livello, "livello_label": a.get_livello_display(),
            "semaforo": semaforo, "prossima_revisione": a.prossima_revisione,
        })
    persone.sort(key=lambda p: (p["semaforo"] != "operativa", -ordinale_livello(p["livello"]), p["nome"].casefold()))
    conta = {k: sum(1 for p in persone if p["semaforo"] == k) for k in ("operativa", "addestramento", "sospesa")}
    return {
        "persone": persone if con_nomi else [],
        "con_nomi": con_nomi,
        "n_operativi": conta["operativa"], "n_addestramento": conta["addestramento"], "n_sospesi": conta["sospesa"],
        "mansioni": mansioni,
        "soglie": soglie,
        "scoperta": any(s["coperta"] is False for s in soglie),
        # Uomo solo: una sola persona operativa sulla macchina.
        "uomo_solo": conta["operativa"] == 1,
    }
