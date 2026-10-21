"""Mansioni di rischio proposte per le mansioni lavorative, con conferma HSE.

Il portale **propone** (regole sotto, leggibili e modificabili); la proposta non
vale per DPI, visite e schede di sicurezza finché HSE non la conferma: solo la
conferma scrive ``CompetenzaSkm.mansioni_rischio``. Regole in ordine: vince la
prima che trova una mansione di rischio esistente nel catalogo.
"""
from __future__ import annotations

from django.db import transaction

from ..models import CompetenzaSkm, Mansione, RuoloOperativo

UFFICIO = "ADDETTO UFFICI"
MACCHINE = "ADDETTO MACCHINE UTENSILI"

# (parola nel nome della mansione, mansione di rischio)
PER_NOME = [
    ("ritocch", "ADDETTO RITOCCHI"),
    ("magazzino", "ADDETTO MAGAZZINO"),
    ("pulizie", "ADDETTO PULIZIE"),
    ("manutenzione", "ADDETTO MANUTENZIONE"),
    ("liquidi penetranti", "ADDETTO LIQUIDI PENETRANTI"),
    ("prova pressione", "ADDETTO PROVA PRESSIONE"),
    ("verniciatura", "ADDETTO VERNICIATURA"),
    ("lavaggio", "ADDETTO LAVAGGIO"),
]
# (area, mansione di rischio)
PER_AREA = {
    "CN5": MACCHINE, "CN5G": MACCHINE, "CNC": MACCHINE, "ALC": MACCHINE, "TNF": MACCHINE,
    "TORNI": MACCHINE, "TRADIZIONALE": MACCHINE, "RETTIFICA": MACCHINE, "PRESETTING": MACCHINE,
    "AGGIUSTAGGIO": "ADDETTO AGGIUSTAGGIO", "MONTAGGIO": "ADDETTO AGGIUSTAGGIO",
    "MARCATURA": "ADDETTO AGGIUSTAGGIO", "MASCHERATURA": "ADDETTO AGGIUSTAGGIO", "SALA TAGLIO": "ADDETTO AGGIUSTAGGIO",
    "VERNICIATURA": "ADDETTO VERNICIATURA", "LAVAGGIO": "ADDETTO LAVAGGIO", "LAVAGGIO CONDOTTI": "ADDETTO LAVAGGIO",
    "PROVA PRESSIONE": "ADDETTO PROVA PRESSIONE", "CONTROLLO QUALITA'": "ADDETTO CONTROLLO",
    "CLG": "ADDETTO CONTROLLO", "LIQUIDI PENETRANTI": "ADDETTO LIQUIDI PENETRANTI", "LOGISTICA": "ADDETTO LOGISTICA",
}
# Ruoli indiretti che lavorano comunque in reparto (movimentazione fisica).
INDIRETTI_IN_REPARTO = {"LOGO": "ADDETTO LOGISTICA"}


def _catalogo() -> dict[str, Mansione]:
    return {m.nome.strip().casefold(): m for m in Mansione.objects.filter(is_active=True)}


def proposta(mansione: CompetenzaSkm, catalogo: dict | None = None) -> Mansione | None:
    """La mansione di rischio che il portale propone, o None."""
    catalogo = catalogo if catalogo is not None else _catalogo()

    def trova(nome):
        return catalogo.get((nome or "").casefold())

    nome = (mansione.nome or "").casefold()
    for parola, rischio in PER_NOME:
        if parola in nome and trova(rischio):
            return trova(rischio)
    ruoli = list(mansione.ruoli.all())
    for r in ruoli:
        if r.sigla in INDIRETTI_IN_REPARTO and trova(INDIRETTI_IN_REPARTO[r.sigla]):
            return trova(INDIRETTI_IN_REPARTO[r.sigla])
    if ruoli and all(r.classe == RuoloOperativo.CLASSE_INDIRETTO for r in ruoli):
        return trova(UFFICIO)
    if mansione.tipo == CompetenzaSkm.TIPO_MACCHINA and trova(MACCHINE):
        return trova(MACCHINE)
    area = (mansione.area.nome if mansione.area_id else "").upper()
    return trova(PER_AREA.get(area, ""))


@transaction.atomic
def proponi(*, solo_senza=True) -> int:
    """Scrive le proposte sulle mansioni attive senza mansione di rischio confermata."""
    catalogo = _catalogo()
    n = 0
    qs = (CompetenzaSkm.objects.filter(tipo__in=(CompetenzaSkm.TIPO_MACCHINA, CompetenzaSkm.TIPO_PROCESSO),
                                       attiva=True)
          .select_related("area").prefetch_related("ruoli", "mansioni_rischio", "mansioni_rischio_proposte"))
    for m in qs:
        if solo_senza and (m.mansioni_rischio.exists() or m.mansioni_rischio_proposte.exists()):
            continue
        r = proposta(m, catalogo)
        if r is not None:
            m.mansioni_rischio_proposte.set([r])
            n += 1
    return n


def da_confermare():
    """Mansioni con una proposta in attesa (per la pagina HSE)."""
    return (CompetenzaSkm.objects.filter(attiva=True, mansioni_rischio_proposte__isnull=False)
            .select_related("area", "area__reparto").prefetch_related("ruoli", "mansioni_rischio",
                                                                       "mansioni_rischio_proposte")
            .distinct().order_by("area__reparto__nome", "area__nome", "display"))


@transaction.atomic
def conferma(mansione: CompetenzaSkm, rischi_ids) -> list[str]:
    """HSE conferma (o corregge) le mansioni di rischio: valgono da ora; la proposta si chiude."""
    scelte = list(Mansione.objects.filter(pk__in=list(rischi_ids), is_active=True))
    if not scelte:
        raise ValueError("Scegli almeno una mansione di rischio.")
    mansione.mansioni_rischio.add(*scelte)
    mansione.mansioni_rischio_proposte.clear()
    return [m.nome for m in scelte]


@transaction.atomic
def scarta(mansione: CompetenzaSkm) -> None:
    """La proposta non va bene e non se ne fa niente: si toglie senza confermare nulla."""
    mansione.mansioni_rischio_proposte.clear()
