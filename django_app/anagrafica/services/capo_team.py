"""Capo e team di una persona: una regola sola, mista reparto/area + organigramma.

Decisione del 16/10/2026: il ruolo dice il **livello** (chi sta sopra chi, con
``RuoloOperativo.riporta_a``), il reparto o l'area dice il **perimetro** (su chi).
Le eccezioni indicate a mano vincono. Il capo si cerca in quest'ordine:

1. **eccezione sulla persona** (``DipendenteAnagraficaAziendale.capo_eccezione_legacy_id``);
2. **responsabile dell'area aziendale** indicato a mano;
3. **caporeparto del reparto** indicato a mano;
4. **organigramma**: chi ricopre un ruolo sopra quello della persona e lavora
   nella stessa area, poi nello stesso reparto, poi chi non ha reparto (ruolo
   trasversale); se nessuno, si sale di livello — chi guida un altro reparto
   non è mai il capo; in cima, se l'ultimo livello ha una persona sola, è lei.

Nessuno è capo di sé stesso: un passo che indicherebbe la persona stessa si
salta. Il **team** è l'inverso: le persone di cui sei il capo, e a cascata i
loro team.

Gli id sono ``anagrafica_dipendenti.id`` (``legacy_anagrafica_id``), non
``utenti.id``. Questa fase legge e basta: i moduli continuano a usare le loro
regole finché il passaggio non viene fatto (pagina «Coerenza capi»).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q
from django.utils import timezone

ORIGINE_PERSONA = "persona"
ORIGINE_AREA = "area"
ORIGINE_REPARTO = "reparto"
ORIGINE_ORGANIGRAMMA = "organigramma"

ORIGINE_LABEL = {
    ORIGINE_PERSONA: "Eccezione sulla persona",
    ORIGINE_AREA: "Responsabile dell'area",
    ORIGINE_REPARTO: "Caporeparto del reparto",
    ORIGINE_ORGANIGRAMMA: "Organigramma (ruolo sopra, stesso perimetro)",
    "": "Nessun capo trovato",
}


@dataclass
class Capo:
    legacy_id: int | None
    origine: str = ""
    # Altri candidati allo stesso passo dell'organigramma: la scelta è
    # deterministica (id più basso) ma va segnalata, non nascosta.
    alternative: list[int] = field(default_factory=list)

    @property
    def origine_label(self) -> str:
        return ORIGINE_LABEL.get(self.origine, self.origine)


@dataclass
class _Persona:
    legacy_id: int
    area_id: int | None
    reparto_id: int | None
    ruoli: set[int]
    eccezione: int | None


def _carica(oggi):
    """Persone in forza con area, reparto, ruoli in essere ed eccezione."""
    from core.legacy_anagrafica import fetch_anagrafica_rows

    from ..models import AreaAziendale, DipendenteAnagraficaAziendale, DipendenteRuoloOperativo, Reparto
    from .reparto_canonico import build_reparto_canonico_map, resolve_reparto_for_row

    righe = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo") and r.get("id")]
    ids = [int(r["id"]) for r in righe]
    reparti = {r.id: r for r in Reparto.objects.filter(is_active=True)}
    per_nome = {r.nome.strip().casefold(): r for r in reparti.values()}
    canonico = build_reparto_canonico_map(ids)
    schede = {
        az.legacy_anagrafica_id: az
        for az in DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=ids)
    }
    ruoli: dict[int, set[int]] = {}
    for legacy_id, ruolo_id in DipendenteRuoloOperativo.objects.filter(
        Q(data_fine__isnull=True) | Q(data_fine__gte=oggi),
        ruolo__is_active=True,
        legacy_anagrafica_id__in=ids,
    ).values_list("legacy_anagrafica_id", "ruolo_id"):
        ruoli.setdefault(int(legacy_id), set()).add(int(ruolo_id))

    persone: dict[int, _Persona] = {}
    for riga in righe:
        legacy_id = int(riga["id"])
        az = schede.get(legacy_id)
        if az is not None and az.data_cessazione and az.data_cessazione < oggi:
            continue
        rep = resolve_reparto_for_row(riga, canonico_map=canonico, reparto_by_name=per_nome)
        persone[legacy_id] = _Persona(
            legacy_id=legacy_id,
            area_id=az.area_aziendale_id if az is not None else None,
            reparto_id=rep.id if rep is not None else None,
            ruoli=ruoli.get(legacy_id, set()),
            eccezione=getattr(az, "capo_eccezione_legacy_id", None) if az is not None else None,
        )
    aree = {a.id: a for a in AreaAziendale.objects.filter(is_active=True)}
    return persone, aree, reparti


def _padri_ruoli():
    from ..models import RuoloOperativo

    return {
        int(rid): int(padre)
        for rid, padre in RuoloOperativo.objects.filter(is_active=True).values_list("id", "riporta_a_id")
        if padre
    }


def _livelli_sopra(ruoli: set[int], padri: dict[int, int]) -> list[set[int]]:
    """Ruoli sopra quelli dati, un livello per volta (senza cicli)."""
    livelli: list[set[int]] = []
    visti = set(ruoli)
    correnti = set(ruoli)
    while True:
        sopra = {padri[r] for r in correnti if r in padri} - visti
        if not sopra:
            return livelli
        livelli.append(sopra)
        visti |= sopra
        correnti = sopra


def _scegli(candidati: list[int]) -> tuple[int, list[int]]:
    ordinati = sorted(set(candidati))
    return ordinati[0], ordinati[1:]


def _capo_organigramma(p: _Persona, persone, titolari: dict[int, set[int]], padri) -> Capo:
    if not p.ruoli:
        return Capo(None)
    in_cima: set[int] = set()
    for livello in _livelli_sopra(p.ruoli, padri):
        candidati = {pid for r in livello for pid in titolari.get(r, set())} - {p.legacy_id}
        if not candidati:
            continue
        in_cima = candidati
        # Stessa area, poi stesso reparto, poi chi non ha un reparto (ruolo
        # trasversale, es. il responsabile di produzione). Chi guida un ALTRO
        # reparto non è mai il capo: si sale invece di prenderlo.
        for stesso in (
            [c for c in candidati if p.area_id and persone[c].area_id == p.area_id],
            [c for c in candidati if p.reparto_id and persone[c].reparto_id == p.reparto_id],
            [c for c in candidati if persone[c].reparto_id is None],
        ):
            if stesso:
                capo, altri = _scegli(stesso)
                return Capo(capo, ORIGINE_ORGANIGRAMMA, altri)
    # Nessun perimetro in comune a nessun livello: vale la persona del livello
    # più alto, se è una sola (es. il direttore inquadrato in un reparto).
    if len(in_cima) == 1:
        return Capo(next(iter(in_cima)), ORIGINE_ORGANIGRAMMA)
    return Capo(None)


def mappa_capi(oggi=None) -> dict[int, Capo]:
    """``legacy_anagrafica_id`` → :class:`Capo`, per tutte le persone in forza."""
    oggi = oggi or timezone.localdate()
    persone, aree, reparti = _carica(oggi)
    padri = _padri_ruoli()
    titolari: dict[int, set[int]] = {}
    for p in persone.values():
        for r in p.ruoli:
            titolari.setdefault(r, set()).add(p.legacy_id)

    risultato: dict[int, Capo] = {}
    for p in persone.values():
        area = aree.get(p.area_id) if p.area_id else None
        reparto = reparti.get(p.reparto_id) if p.reparto_id else None
        manuali = (
            (ORIGINE_PERSONA, p.eccezione),
            (ORIGINE_AREA, area.responsabile_legacy_id if area is not None else None),
            (ORIGINE_REPARTO, reparto.caporeparto_legacy_id if reparto is not None else None),
        )
        capo = None
        for origine, candidato in manuali:
            if candidato and int(candidato) != p.legacy_id:
                capo = Capo(int(candidato), origine)
                break
        risultato[p.legacy_id] = capo or _capo_organigramma(p, persone, titolari, padri)
    return risultato


def capo_di(legacy_id: int, *, mappa: dict[int, Capo] | None = None) -> Capo:
    mappa = mappa if mappa is not None else mappa_capi()
    return mappa.get(int(legacy_id), Capo(None))


def team_di(legacy_id: int, *, mappa: dict[int, Capo] | None = None, solo_diretti: bool = False) -> set[int]:
    """Le persone di cui ``legacy_id`` è il capo, e a cascata i loro team."""
    mappa = mappa if mappa is not None else mappa_capi()
    figli: dict[int, set[int]] = {}
    for persona, capo in mappa.items():
        if capo.legacy_id:
            figli.setdefault(capo.legacy_id, set()).add(persona)
    diretti = figli.get(int(legacy_id), set())
    if solo_diretti:
        return set(diretti)
    team: set[int] = set()
    da_visitare = list(diretti)
    while da_visitare:
        corrente = da_visitare.pop()
        if corrente in team or corrente == int(legacy_id):
            continue
        team.add(corrente)
        da_visitare.extend(figli.get(corrente, ()))
    return team


# ── Passaggio (fase 2b): interruttore, cache e funzioni per i moduli ──────────

CONFIG_ATTIVA = "capi.regola_unica_attiva"
_CACHE_VERSIONE = "capi:mappa:versione"
_CACHE_TTL = 120


def regola_unica_attiva() -> bool:
    """Interruttore del passaggio: spento, ogni modulo usa la regola di prima."""
    try:
        from core.models import SiteConfig

        return str(SiteConfig.get(CONFIG_ATTIVA, "") or "").strip().lower() in {"1", "true", "on", "si", "sì"}
    except Exception:
        return False


def imposta_regola_unica(attiva: bool) -> None:
    from core.models import SiteConfig

    SiteConfig.objects.update_or_create(
        chiave=CONFIG_ATTIVA,
        defaults={"valore": "1" if attiva else "0",
                  "descrizione": "Capo e team dalla regola unica (anagrafica.services.capo_team)"},
    )
    invalida_cache()


def _versione() -> int:
    from django.core.cache import cache

    try:
        v = cache.get(_CACHE_VERSIONE)
        if v is None:
            v = 1
            cache.set(_CACHE_VERSIONE, v, None)
        return int(v)
    except Exception:
        return 1


def invalida_cache() -> None:
    """Dopo una modifica a schede, reparti, aree, ruoli o assegnazioni."""
    from django.core.cache import cache

    try:
        cache.set(_CACHE_VERSIONE, _versione() + 1, None)
    except Exception:
        pass
    try:
        from core.permessi.team import invalida_cache_team

        invalida_cache_team()
    except Exception:
        pass


def mappa_capi_in_cache() -> dict[int, int | None]:
    """``legacy_anagrafica_id`` → id del capo, letta dalla cache (120 s)."""
    from django.core.cache import cache

    chiave = f"capi:mappa:v{_versione()}"
    try:
        cached = cache.get(chiave)
    except Exception:
        cached = None
    if cached is not None:
        return {int(k): v for k, v in cached.items()}
    mappa = {pid: c.legacy_id for pid, c in mappa_capi().items()}
    try:
        cache.set(chiave, mappa, _CACHE_TTL)
    except Exception:
        pass
    return mappa


def capo_effettivo(legacy_id) -> int | None:
    """Capo della persona con la regola unica (None se non trovato)."""
    try:
        return mappa_capi_in_cache().get(int(legacy_id))
    except (TypeError, ValueError):
        return None


def team_anagrafica(legacy_id, *, solo_diretti: bool = False) -> set[int]:
    """Team della persona con la regola unica, come ``legacy_anagrafica_id``."""
    try:
        capo = int(legacy_id)
    except (TypeError, ValueError):
        return set()
    mappa = mappa_capi_in_cache()
    figli: dict[int, set[int]] = {}
    for persona, c in mappa.items():
        if c:
            figli.setdefault(int(c), set()).add(persona)
    diretti = figli.get(capo, set())
    if solo_diretti:
        return set(diretti)
    team: set[int] = set()
    da_visitare = list(diretti)
    while da_visitare:
        corrente = da_visitare.pop()
        if corrente in team or corrente == capo:
            continue
        team.add(corrente)
        da_visitare.extend(figli.get(corrente, ()))
    return team


def riallinea_tutte_le_schede() -> int:
    """Scrive il capo della regola unica nel «Caporeparto» di ogni scheda.

    Scheda dipendente e digest mattutino leggono quella copia. Si usa quando la
    regola è accesa (all'accensione e dopo ogni modifica che la cambia).
    """
    from ..models import DipendenteAnagraficaAziendale

    mappa = {pid: c.legacy_id for pid, c in mappa_capi().items()}
    cambiate = 0
    for pk, legacy_id, attuale in DipendenteAnagraficaAziendale.objects.filter(
        legacy_anagrafica_id__in=list(mappa)
    ).values_list("pk", "legacy_anagrafica_id", "caporeparto_legacy_id"):
        nuovo = mappa.get(int(legacy_id))
        if attuale != nuovo:
            DipendenteAnagraficaAziendale.objects.filter(pk=pk).update(caporeparto_legacy_id=nuovo)
            cambiate += 1
    return cambiate
