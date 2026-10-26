"""Capo del reparto e dell'area decisi da una mansione (26/10/2026).

Un criterio solo per tutti: ogni reparto ha la **mansione del capo** (vuota =
la sua «Responsabilità del reparto»), ogni area può averne una propria (vuota =
segue il reparto). Il capo è **chi ha quella mansione assegnata** nel
Mansionario (``AbilitazioneMacchina`` in lista e attiva); se sono più persone
sono tutte capo, la prima per id approva e le altre si segnalano.

Il passaggio dai capi scelti a mano si fa una volta sola dalla pagina
«Reparti, aree e capi»: la proposta assegna la mansione a chi oggi è capo,
poi la regola unica (``capo_team``) resta accesa e i campi di prima
(``Reparto.caporeparto_legacy_id``, ``AreaAziendale.responsabile_legacy_id``,
il «Caporeparto» delle schede e ``RepartoCapoMapping``) diventano copie
derivate, riallineate a ogni modifica da ``segnali_capi``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import DatabaseError, transaction

LIVELLO_PASSAGGIO = "U"  # Autonomo: la responsabilità si assegna, non si valuta qui


def mansioni_responsabilita() -> dict[int, int]:
    """``reparto_id`` → id della sua «Responsabilità del reparto» attiva."""
    from ..models_skillmatrix import CompetenzaSkm

    return dict(
        CompetenzaSkm.objects.filter(responsabilita_reparto__isnull=False, attiva=True)
        .values_list("responsabilita_reparto_id", "pk")
    )


def mansione_reparto(reparto, responsabilita: dict[int, int] | None = None) -> int | None:
    """Id della mansione che decide il capo del reparto."""
    if reparto is None:
        return None
    if reparto.mansione_capo_id:
        return reparto.mansione_capo_id
    responsabilita = responsabilita if responsabilita is not None else mansioni_responsabilita()
    return responsabilita.get(reparto.pk)


def titolari(mansione_ids, *, in_forza: set[int] | None = None) -> dict[int, list[int]]:
    """``mansione_id`` → persone che l'hanno assegnata (in lista, attiva), ordinate per id."""
    from ..models_skillmatrix import AbilitazioneMacchina

    ids = {int(m) for m in mansione_ids if m}
    out: dict[int, set[int]] = {}
    if not ids:
        return {}
    for mid, legacy_id in AbilitazioneMacchina.objects.filter(
        competenza_id__in=ids, in_lista=True, stato=AbilitazioneMacchina.STATO_ATTIVA,
    ).values_list("competenza_id", "legacy_anagrafica_id"):
        if in_forza is not None and int(legacy_id) not in in_forza:
            continue
        out.setdefault(int(mid), set()).add(int(legacy_id))
    return {mid: sorted(p) for mid, p in out.items()}


def titolari_struttura(reparti, aree, *, in_forza: set[int] | None = None):
    """(``reparto_id`` → titolari, ``area_id`` → titolari) secondo le mansioni del capo."""
    responsabilita = mansioni_responsabilita()
    per_reparto = {r.pk: mansione_reparto(r, responsabilita) for r in reparti}
    per_area = {a.pk: a.mansione_capo_id for a in aree if a.mansione_capo_id}
    tit = titolari(set(per_reparto.values()) | set(per_area.values()), in_forza=in_forza)
    return (
        {rid: tit.get(mid, []) for rid, mid in per_reparto.items() if mid},
        {aid: tit.get(mid, []) for aid, mid in per_area.items()},
    )


def e_mansione_capo(mansione_id) -> bool:
    """La mansione decide un capo (serve ai segnali per non ricalcolare a vuoto)."""
    from ..models import AreaAziendale, Reparto
    from ..models_skillmatrix import CompetenzaSkm

    if not mansione_id:
        return False
    return (
        CompetenzaSkm.objects.filter(pk=mansione_id, responsabilita_reparto__isnull=False).exists()
        or Reparto.objects.filter(mansione_capo_id=mansione_id).exists()
        or AreaAziendale.objects.filter(mansione_capo_id=mansione_id).exists()
    )


# ── Passaggio dai capi scelti a mano ─────────────────────────────────────────

@dataclass
class Proposta:
    """Cosa fa il passaggio e cosa va deciso prima."""
    assegnazioni: list[dict] = field(default_factory=list)  # mansione → persona (capo di oggi)
    senza_mansione: list = field(default_factory=list)      # reparti senza mansione del capo
    aree_da_decidere: list = field(default_factory=list)    # responsabile diverso dal capo e niente mansione

    @property
    def bloccata(self) -> bool:
        return bool(self.senza_mansione)


def proposta() -> Proposta:
    from ..models import AreaAziendale, Reparto
    from ..models_skillmatrix import CompetenzaSkm
    from . import capo_team

    in_forza = set(capo_team.mappa_capi(usa_mansioni=False))
    reparti = list(Reparto.objects.filter(is_active=True).prefetch_related("responsabili").order_by("nome"))
    aree = list(AreaAziendale.objects.filter(is_active=True).select_related("reparto")
                .prefetch_related("responsabili").order_by("nome"))
    responsabilita = mansioni_responsabilita()
    mansioni = {m.pk: m for m in CompetenzaSkm.objects.filter(
        pk__in={mansione_reparto(r, responsabilita) for r in reparti} | {a.mansione_capo_id for a in aree})}
    tit_rep, tit_area = titolari_struttura(reparti, aree, in_forza=in_forza)
    p = Proposta()
    for r in reparti:
        mid = mansione_reparto(r, responsabilita)
        if not mid:
            p.senza_mansione.append(r)
            continue
        # Il capo scelto a mano e gli «altri responsabili» (co-capi) del reparto.
        for persona in [r.caporeparto_legacy_id] + [d.pk for d in r.responsabili.all()]:
            if persona and persona in in_forza and persona not in tit_rep.get(r.pk, []):
                _aggiungi(p, r.nome, mansioni.get(mid), persona)
    for a in aree:
        persone = [a.responsabile_legacy_id] + [d.pk for d in a.responsabili.all()]
        persone = [x for x in persone if x and x in in_forza]
        if not persone:
            continue
        if a.mansione_capo_id:
            for persona in persone:
                if persona not in tit_area.get(a.pk, []):
                    _aggiungi(p, a.nome, mansioni.get(a.mansione_capo_id), persona)
        elif a.reparto is not None and set(persone) - {a.reparto.caporeparto_legacy_id}:
            p.aree_da_decidere.append(a)
    return p


def _aggiungi(p: Proposta, dove: str, mansione, legacy_id: int) -> None:
    if not any(x["mansione"] == mansione and x["legacy_id"] == legacy_id for x in p.assegnazioni):
        p.assegnazioni.append({"dove": dove, "mansione": mansione, "legacy_id": legacy_id})


@transaction.atomic
def applica_passaggio(*, user=None) -> dict:
    """Assegna le mansioni proposte, accende la regola unica e riallinea le copie."""
    from . import capo_team, mansionario_struttura

    p = proposta()
    if p.bloccata:
        raise ValueError("Prima scegli la mansione del capo per: " + ", ".join(r.nome for r in p.senza_mansione))
    fatte = 0
    for a in p.assegnazioni:
        if a["mansione"] is None:
            continue
        mansionario_struttura.assegna(a["mansione"], legacy_anagrafica_id=a["legacy_id"],
                                      livello=LIVELLO_PASSAGGIO, user=user)
        fatte += 1
    capo_team.imposta_regola_unica(True)
    esito = allinea_derivati()
    esito["assegnazioni"] = fatte
    return esito


# ── Copie derivate ──────────────────────────────────────────────────────────

def allinea_derivati(*, mappa=None) -> dict:
    """Con la regola accesa riscrive capo di reparti, aree, schede e ``RepartoCapoMapping``.

    Usa ``update()``: nessun segnale, nessun ricalcolo a catena.
    """
    from ..models import AreaAziendale, Reparto
    from . import capo_team

    if not capo_team.regola_unica_attiva():
        return {}
    mappa = mappa if mappa is not None else capo_team.mappa_capi()
    in_forza = set(mappa)
    reparti = list(Reparto.objects.all())
    aree = list(AreaAziendale.objects.all())
    tit_rep, tit_area = titolari_struttura(reparti, aree, in_forza=in_forza)
    cambi = {"reparti": 0, "aree": 0, "schede": 0, "mapping": 0}
    for r in reparti:
        capo = (tit_rep.get(r.pk) or [None])[0]
        if r.caporeparto_legacy_id != capo:
            Reparto.objects.filter(pk=r.pk).update(caporeparto_legacy_id=capo)
            r.caporeparto_legacy_id = capo
            cambi["reparti"] += 1
    for a in aree:
        resp = (tit_area.get(a.pk) or [None])[0]
        if a.responsabile_legacy_id != resp:
            AreaAziendale.objects.filter(pk=a.pk).update(responsabile_legacy_id=resp)
            cambi["aree"] += 1
    cambi["schede"] = capo_team.riallinea_tutte_le_schede(mappa=mappa)
    cambi["mapping"] = allinea_mapping([r for r in reparti if r.is_active])
    return cambi


def valore_mapping(legacy_anagrafica_id) -> str:
    """Il capo come lo vuole ``RepartoCapoMapping`` (email dell'account, o nome).

    ``caporeparto_legacy_id`` è un id di ``anagrafica_dipendenti``, non di
    ``utenti``: il ponte è ``anagrafica_dipendenti.utente_id``. Prima del
    26/10/2026 l'id veniva cercato direttamente fra gli utenti, e il mapping
    finiva sulla persona che per caso aveva lo stesso numero.
    """
    from core.caporeparto_utils import canonical_caporeparto_value
    from core.legacy_models import AnagraficaDipendente

    if not legacy_anagrafica_id:
        return ""
    try:
        dip = AnagraficaDipendente.objects.filter(pk=int(legacy_anagrafica_id)).values("utente_id", "email").first()
    except (TypeError, ValueError, DatabaseError):
        dip = None
    if not dip:
        return ""
    if dip.get("utente_id"):
        valore = canonical_caporeparto_value(legacy_user_id=dip["utente_id"])
        if valore:
            return valore
    return str(dip.get("email") or "").strip().lower()


def allinea_mapping(reparti) -> int:
    """``RepartoCapoMapping`` (assenze, automazioni) = un rigo per reparto attivo col suo capo."""
    from core.models import RepartoCapoMapping

    voluti: dict[str, tuple[str, str]] = {}
    for r in reparti:
        nome = (r.nome or "").strip()
        if nome and r.caporeparto_legacy_id:
            capo = valore_mapping(r.caporeparto_legacy_id)
            if capo:
                voluti[nome.casefold()] = (nome, capo)
    cambi = 0
    esistenti = list(RepartoCapoMapping.objects.all())
    for m in esistenti:
        atteso = voluti.get((m.reparto or "").strip().casefold())
        if atteso is None or m.caporeparto != atteso[1] or not m.is_active:
            m.delete()
            cambi += 1
    rimasti = {(m.reparto or "").strip().casefold() for m in RepartoCapoMapping.objects.all()}
    for chiave, (nome, capo) in voluti.items():
        if chiave not in rimasti:
            RepartoCapoMapping.objects.create(reparto=nome, caporeparto=capo, is_active=True)
            cambi += 1
    return cambi
