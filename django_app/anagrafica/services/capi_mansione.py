"""Capo del reparto e dell'area decisi da una mansione (26-27/10/2026).

Un criterio solo per tutti, quello del file MEGA SKILL MATRIX v8 («ogni
reparto ha esattamente un record RESPONSABILE=Y»): ogni reparto ha la sua
«Responsabilità del reparto» e ogni area con un ruolo responsabile proprio la
sua «Responsabilità dell'area» (le 31 unità del file sono le aree del
portale). Le mansioni si generano dal ruolo responsabile (``struttura_v8``);
il capo è **chi ha quella mansione assegnata** nel Mansionario
(``AbilitazioneMacchina`` in lista e attiva). Area senza ruolo responsabile, o
senza nessuno sulla mansione: vale il capo del reparto. Più persone sulla
stessa mansione sono tutte capo: approva quello scelto come capo (il campo
del reparto o dell'area), altrimenti il primo per id; gli altri sono co-capo.

Mansione e campi sono **sempre collegati** (28/10/2026), a regola accesa o
spenta: chi ha la «Responsabilità» diventa il capo del reparto o dell'area
(``Reparto.caporeparto_legacy_id``, ``AreaAziendale.responsabile_legacy_id``,
co-capi in ``responsabili``) e da lì il «Caporeparto» delle schede e
``RepartoCapoMapping`` (assenze, automazioni); il capo scelto in Impostazioni
assegna o toglie la «Responsabilità» (:func:`imposta_capo`). A regola spenta un
capo scelto a mano senza nessuno sulla mansione resta finché non gli si toglie
la mansione. Il passaggio dalla pagina «Reparti, aree e capi» accende la regola
unica (``capo_team``) per tutti i moduli.
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


def mansioni_responsabilita_aree() -> dict[int, int]:
    """``area_id`` → id della sua «Responsabilità dell'area» attiva."""
    from ..models_skillmatrix import CompetenzaSkm

    return dict(
        CompetenzaSkm.objects.filter(responsabilita_area__isnull=False, attiva=True)
        .values_list("responsabilita_area_id", "pk")
    )


def mansione_reparto(reparto, responsabilita: dict[int, int] | None = None) -> int | None:
    """Id della mansione che decide il capo del reparto."""
    if reparto is None:
        return None
    responsabilita = responsabilita if responsabilita is not None else mansioni_responsabilita()
    return responsabilita.get(reparto.pk)


def titolari(mansione_ids, *, in_forza: set[int] | None = None,
             esclusi: set[int] | None = None) -> dict[int, list[int]]:
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
        if esclusi and int(legacy_id) in esclusi:
            continue
        out.setdefault(int(mid), set()).add(int(legacy_id))
    return {mid: sorted(p) for mid, p in out.items()}


def tolti(mansione_ids) -> dict[int, set[int]]:
    """``mansione_id`` → persone che l'avevano e non l'hanno più (tolte dalla lista o sospese)."""
    from django.db.models import Q

    from ..models_skillmatrix import AbilitazioneMacchina

    ids = {int(m) for m in mansione_ids if m}
    out: dict[int, set[int]] = {}
    if not ids:
        return {}
    for mid, legacy_id in AbilitazioneMacchina.objects.filter(competenza_id__in=ids).filter(
        Q(in_lista=False) | ~Q(stato=AbilitazioneMacchina.STATO_ATTIVA)
    ).values_list("competenza_id", "legacy_anagrafica_id"):
        out.setdefault(int(mid), set()).add(int(legacy_id))
    return out


def _prima(lista: list[int], scelto) -> list[int]:
    """Il capo scelto (campo del reparto o dell'area) in testa, se ha la mansione."""
    if scelto and scelto in lista:
        return [scelto] + [x for x in lista if x != scelto]
    return lista


def titolari_struttura(reparti, aree, *, in_forza: set[int] | None = None, esclusi: set[int] | None = None):
    """(``reparto_id`` → titolari, ``area_id`` → titolari) secondo le mansioni di responsabilità.

    In testa il capo scelto, se ha la mansione: è lui che approva, gli altri sono co-capo.
    """
    reparti, aree = list(reparti), list(aree)
    responsabilita = mansioni_responsabilita()
    resp_aree = mansioni_responsabilita_aree()
    per_reparto = {r.pk: mansione_reparto(r, responsabilita) for r in reparti}
    per_area = {a.pk: resp_aree[a.pk] for a in aree if a.pk in resp_aree}
    tit = titolari(set(per_reparto.values()) | set(per_area.values()), in_forza=in_forza, esclusi=esclusi)
    return (
        {r.pk: _prima(tit.get(per_reparto[r.pk], []), r.caporeparto_legacy_id) for r in reparti if per_reparto[r.pk]},
        {a.pk: _prima(tit.get(per_area[a.pk], []), a.responsabile_legacy_id) for a in aree if a.pk in per_area},
    )


def e_mansione_capo(mansione_id) -> bool:
    """La mansione decide un capo (serve ai segnali per non ricalcolare a vuoto)."""
    from django.db.models import Q

    from ..models_skillmatrix import CompetenzaSkm

    if not mansione_id:
        return False
    return CompetenzaSkm.objects.filter(
        Q(responsabilita_reparto__isnull=False) | Q(responsabilita_area__isnull=False), pk=mansione_id,
    ).exists()


def aree_senza_ruolo() -> list:
    """Aree attive con un nome proprio e senza ruolo responsabile: seguono il reparto."""
    from ..models import AreaAziendale
    from .struttura_v8 import area_coincide_col_reparto

    return [a for a in AreaAziendale.objects.filter(is_active=True, reparto__isnull=False,
                                                     ruolo_responsabile__isnull=True)
            .select_related("reparto").order_by("reparto__nome", "nome")
            if not area_coincide_col_reparto(a)]


@transaction.atomic
def ruolo_del_reparto_alle_aree(area_ids=None) -> int:
    """Le aree senza ruolo responsabile prendono quello del loro reparto (es. CAR).

    È la regola del file della Qualità per le aree di produzione: ognuna ha la
    sua responsabilità, di solito del caporeparto. Il salvataggio genera la mansione.
    """
    scelte = set(area_ids) if area_ids is not None else None
    fatte = 0
    for a in aree_senza_ruolo():
        if scelte is not None and a.pk not in scelte:
            continue
        if a.reparto.ruolo_responsabile_id:
            a.ruolo_responsabile_id = a.reparto.ruolo_responsabile_id
            a.save(update_fields=["ruolo_responsabile"])
            fatte += 1
    return fatte


# ── Passaggio dai capi scelti a mano ─────────────────────────────────────────

@dataclass
class Proposta:
    """Cosa fa il passaggio e cosa va deciso prima."""
    assegnazioni: list[dict] = field(default_factory=list)  # mansione → persona (capo di oggi)
    senza_mansione: list = field(default_factory=list)      # reparti senza «Responsabilità» (niente ruolo responsabile)
    aree_da_decidere: list = field(default_factory=list)    # responsabile diverso dal capo, area senza ruolo responsabile

    @property
    def bloccata(self) -> bool:
        return bool(self.senza_mansione)


def proposta() -> Proposta:
    from ..models import AreaAziendale, Reparto
    from ..models_skillmatrix import CompetenzaSkm
    from . import capo_team
    from .struttura_v8 import area_coincide_col_reparto

    in_forza = set(capo_team.mappa_capi(usa_mansioni=False))
    reparti = list(Reparto.objects.filter(is_active=True).prefetch_related("responsabili").order_by("nome"))
    aree = list(AreaAziendale.objects.filter(is_active=True).select_related("reparto")
                .prefetch_related("responsabili").order_by("nome"))
    responsabilita = mansioni_responsabilita()
    resp_aree = mansioni_responsabilita_aree()
    mansioni = {m.pk: m for m in CompetenzaSkm.objects.filter(
        pk__in=set(responsabilita.values()) | set(resp_aree.values()))}
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
        mid = resp_aree.get(a.pk)
        if mid:
            for persona in persone:
                if persona not in tit_area.get(a.pk, []):
                    _aggiungi(p, a.nome, mansioni.get(mid), persona)
        elif (a.reparto is not None and not area_coincide_col_reparto(a)
              and set(persone) - {a.reparto.caporeparto_legacy_id}):
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
        raise ValueError("Prima scegli il ruolo responsabile per: " + ", ".join(r.nome for r in p.senza_mansione))
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

def _cessati() -> set[int]:
    from django.utils import timezone

    from ..models import DipendenteAnagraficaAziendale

    return set(DipendenteAnagraficaAziendale.objects.filter(
        data_cessazione__lt=timezone.localdate()).values_list("legacy_anagrafica_id", flat=True))


def _voluti(attuale, altri_attuali: list[int], tit: list[int] | None, via: set[int], regola: bool):
    """(capo, co-capi) di un reparto o di un'area con la sua «Responsabilità».

    ``tit``: titolari, il capo scelto in testa (None = l'unità non ha la
    mansione); ``via``: chi aveva la mansione e l'ha persa.
    """
    if tit is None:
        return (None, []) if regola else (attuale, list(altri_attuali))
    if regola:
        return (tit[0], tit[1:]) if tit else (None, [])
    # Regola spenta: comanda la mansione, ma chi è stato scelto a mano e non
    # l'ha mai persa non sparisce: senza titolari resta capo, altrimenti
    # passa fra i co-capi (salvando il reparto in Impostazioni riceve la mansione).
    restano = [x for x in [attuale, *altri_attuali] if x and x not in via]
    if not tit:
        return (restano[0] if attuale in restano else None), [x for x in restano if x != attuale]
    capo = tit[0]
    return capo, [x for x in dict.fromkeys([*tit[1:], *restano]) if x != capo]


def allinea_derivati(*, mappa=None, simula: bool = False) -> dict:
    """Riscrive capo e co-capi di reparti e aree da chi ha la «Responsabilità», poi schede e mapping.

    Sempre, a regola accesa o spenta (vedi la docstring del modulo). Usa
    ``update()``: nessun segnale, nessun ricalcolo a catena. ``simula``: non
    scrive, ritorna in ``"dettaglio"`` cosa cambierebbe.
    """
    from ..models import AreaAziendale, Reparto
    from . import capo_team

    regola = capo_team.regola_unica_attiva()
    if regola:
        mappa = mappa if mappa is not None else capo_team.mappa_capi()
        tit_rep, tit_area = titolari_struttura(Reparto.objects.all(), AreaAziendale.objects.all(),
                                               in_forza=set(mappa))
    else:
        tit_rep, tit_area = titolari_struttura(Reparto.objects.all(), AreaAziendale.objects.all(),
                                               esclusi=_cessati())
    mansioni = {**{("r", k): v for k, v in mansioni_responsabilita().items()},
                **{("a", k): v for k, v in mansioni_responsabilita_aree().items()}}
    via = tolti(mansioni.values())
    cambi = {"reparti": 0, "aree": 0, "schede": 0, "mapping": 0, "dettaglio": []}
    toccati_rep, toccate_aree = [], []
    for tipo, modello, campo, titolari_unita, toccate in (
        ("r", Reparto, "caporeparto_legacy_id", tit_rep, toccati_rep),
        ("a", AreaAziendale, "responsabile_legacy_id", tit_area, toccate_aree),
    ):
        for u in modello.objects.prefetch_related("responsabili"):
            attuale = getattr(u, campo)
            altri_attuali = sorted(d.pk for d in u.responsabili.all())
            capo, altri = _voluti(attuale, altri_attuali, titolari_unita.get(u.pk),
                                  via.get(mansioni.get((tipo, u.pk)), set()), regola)
            if capo == attuale and sorted(altri) == altri_attuali:
                continue
            toccate.append(u)
            cambi["reparti" if tipo == "r" else "aree"] += 1
            cambi["dettaglio"].append({"tipo": "reparto" if tipo == "r" else "area", "nome": u.nome,
                                       "capo": (attuale, capo), "co_capi": (altri_attuali, sorted(altri))})
            if simula:
                continue
            if capo != attuale:
                modello.objects.filter(pk=u.pk).update(**{campo: capo})
                setattr(u, campo, capo)
            if sorted(altri) != altri_attuali:
                u.responsabili.set(altri)
    if simula:
        return cambi
    if regola:
        cambi["schede"] = capo_team.riallinea_tutte_le_schede(mappa=mappa)
        cambi["mapping"] = allinea_mapping([r for r in Reparto.objects.all() if r.is_active])
    else:
        cambi["schede"], cambi["mapping"] = _copie_a_valle(toccati_rep, toccate_aree)
    if toccati_rep or toccate_aree:
        capo_team.invalida_cache()
    return cambi


def _copie_a_valle(reparti, aree) -> tuple[int, int]:
    """A regola spenta: «Caporeparto» delle schede e ``RepartoCapoMapping`` dei soli reparti e aree cambiati."""
    from ..views.struttura import _sync_reparto_capo_mapping
    from .reparto_canonico import riallinea_capo_schede

    schede = 0
    for r in reparti:
        schede += riallinea_capo_schede(reparto=r)
        _sync_reparto_capo_mapping(r)
    for a in aree:
        schede += riallinea_capo_schede(area=a)
    return schede, len(reparti)


@transaction.atomic
def imposta_capo(unita, *, capo, altri=(), user=None) -> dict:
    """Capo e co-capi scelti in Impostazioni per un ``Reparto`` o un'``AreaAziendale``.

    Se l'unità ha la sua «Responsabilità», la mansione segue la scelta: la
    ricevono il capo e i co-capi, la perde chi non c'è più. Poi il campo del
    capo, i co-capi e, a valle, schede e mapping delle assenze.
    """
    from ..models import Reparto
    from ..models_skillmatrix import AbilitazioneMacchina, CompetenzaSkm
    from . import capo_team, mansionario_struttura

    e_reparto = isinstance(unita, Reparto)
    campo = "caporeparto_legacy_id" if e_reparto else "responsabile_legacy_id"
    capo = int(capo) if capo else None
    altri = [int(x) for x in dict.fromkeys(altri) if x and int(x) != capo]
    voluti = [x for x in [capo, *altri] if x]
    mid = (mansioni_responsabilita() if e_reparto else mansioni_responsabilita_aree()).get(unita.pk)
    esito = {"assegnate": 0, "tolte": 0}
    if mid:
        mansione = CompetenzaSkm.objects.get(pk=mid)
        for ab in AbilitazioneMacchina.objects.filter(competenza_id=mid, in_lista=True).exclude(
            legacy_anagrafica_id__in=voluti
        ):
            mansionario_struttura.togli(ab)
            esito["tolte"] += 1
        hanno = set(AbilitazioneMacchina.objects.filter(
            competenza_id=mid, in_lista=True, stato=AbilitazioneMacchina.STATO_ATTIVA,
        ).values_list("legacy_anagrafica_id", flat=True))
        for pid in voluti:
            if pid not in hanno:
                mansionario_struttura.assegna(mansione, legacy_anagrafica_id=pid, livello=LIVELLO_PASSAGGIO, user=user)
                esito["assegnate"] += 1
    type(unita).objects.filter(pk=unita.pk).update(**{campo: capo})
    setattr(unita, campo, capo)
    unita.responsabili.set(altri)
    capo_team.invalida_cache()
    if capo_team.regola_unica_attiva():
        transaction.on_commit(lambda: allinea_derivati())
    else:
        _copie_a_valle([unita] if e_reparto else [], [] if e_reparto else [unita])
    return esito


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
