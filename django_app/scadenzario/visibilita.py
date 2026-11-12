"""Chi vede cosa nello scadenzario generale (``/scadenze``).

Ogni voce dello scadenzario ha un percorso di chiavi dal generale al
particolare: ``fonte`` → ``fonte|tipo`` → ``fonte|tipo|elemento`` (es.
``hr`` → ``hr|qualifica`` → ``hr|qualifica|patentino-carrellista``).

Su ogni chiave il pannello «Gestione scadenzario» può dire:

- **attiva**: sì / no / come la voce superiore. Una voce spenta non compare a
  nessuno (si riaccende dal pannello).
- **modalità**: «chi ha il permesso del modulo, più le regole» (predefinita)
  oppure «solo chi è nelle regole».
- **regole**: ruoli del portale, ruoli aziendali (organigramma) e persone
  aggiunte a mano che vedono la voce e tutto ciò che sta sotto. Ogni regola ha un
  **ambito**: «tutti» (ogni scadenza della voce), «propri» (quelle legate alla
  persona) o «team» (anche quelle delle persone del suo team). Una scadenza senza
  una persona determinabile passa solo con «tutti».

Decisione per una voce e una persona:

1. voce spenta → non compare;
2. modalità «modulo»: compare se il modulo gliela mostra già **oppure** una regola
   la concede;
3. modalità «solo regole»: compare se una regola la concede (gli amministratori
   del pannello la vedono comunque).

Le voci concesse da una regola a chi nel modulo non le vedrebbe si leggono con la
raccolta «di sistema» delle fonti (``dashboard.scadenze_providers.collect_sistema``).
In caso di errore nella configurazione non si allarga nulla: restano le voci
che il modulo già mostra.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

SEP = "|"
CHIAVE_PANNELLO = "__pannello__"  # regole su questa chiave = chi gestisce il pannello


def slug(testo) -> str:
    t = unicodedata.normalize("NFKD", str(testo or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:120]


def chiavi_di(source: str, kind: str = "", elemento: str = "") -> list[str]:
    """Percorso di chiavi dal generale al particolare."""
    chiavi = [source]
    if kind:
        chiavi.append(f"{source}{SEP}{kind}")
        if elemento:
            chiavi.append(f"{source}{SEP}{kind}{SEP}{slug(elemento) or elemento}")
    return chiavi


def chiavi_voce(item) -> list[str]:
    return chiavi_di(item.source, item.kind, getattr(item, "elemento", "") or "")


def antenati(chiave: str) -> list[str]:
    parti = chiave.split(SEP)
    return [SEP.join(parti[: i + 1]) for i in range(len(parti))]


# ---------------------------------------------------------------------------
# Identità della persona (ruoli del portale, ruoli aziendali, utenti.id)
# ---------------------------------------------------------------------------

@dataclass
class Identita:
    legacy_user_id: int | None = None
    ruoli_portale: frozenset[int] = frozenset()
    ruoli_aziendali: frozenset[int] = frozenset()
    amministratore: bool = False
    _team: frozenset[int] | None = field(default=None, repr=False)

    @property
    def team(self) -> frozenset[int]:
        """``utenti.id`` del team, letti una sola volta per richiesta."""
        if self._team is None:
            from core.permessi.team import team_di

            self._team = team_di(self.legacy_user_id)
        return self._team


def ruoli_aziendali_di(legacy_user_id: int | None) -> frozenset[int]:
    """Ruoli d'organigramma (``RuoloOperativo``) ricoperti oggi dalla persona."""
    if not legacy_user_id:
        return frozenset()
    try:
        from core.legacy_models import AnagraficaDipendente
        from core.permessi.team import _assegnazioni_attive

        anagrafiche = list(AnagraficaDipendente.objects.filter(utente_id=int(legacy_user_id)).values_list("id", flat=True))
        if not anagrafiche:
            return frozenset()
        return frozenset(
            int(r) for r in _assegnazioni_attive().filter(legacy_anagrafica_id__in=anagrafiche).values_list("ruolo_id", flat=True)
        )
    except Exception:
        logger.warning("scadenzario: ruoli aziendali non leggibili per %s", legacy_user_id, exc_info=True)
        return frozenset()


def identita_di(soggetto) -> Identita:
    """Identità da request o User, memorizzata sull'utente per la richiesta."""
    from core.permessi.motore import _soggetto, contesto_per

    user, _request = _soggetto(soggetto)
    if user is None or not getattr(user, "is_authenticated", False):
        return Identita()
    cached = getattr(user, "_scadenzario_identita", None)
    if cached is not None:
        return cached
    ctx = contesto_per(soggetto)
    ident = Identita(
        legacy_user_id=ctx.legacy_user_id,
        ruoli_portale=frozenset(r.id for r in ctx.ruoli),
        ruoli_aziendali=ruoli_aziendali_di(ctx.legacy_user_id),
        amministratore=bool(ctx.superuser or ctx.amministratore),
    )
    try:
        user._scadenzario_identita = ident
    except AttributeError:
        pass
    return ident


# ---------------------------------------------------------------------------
# Configurazione (impostazioni + regole), letta una volta per richiesta
# ---------------------------------------------------------------------------

@dataclass
class Configurazione:
    voci: dict[str, object] = field(default_factory=dict)        # chiave → VoceConfig
    regole: dict[str, list] = field(default_factory=dict)        # chiave → [RegolaVisibilita]

    @classmethod
    def carica(cls) -> "Configurazione":
        from .models import RegolaVisibilita, VoceConfig

        conf = cls()
        try:
            conf.voci = {v.chiave: v for v in VoceConfig.objects.all()}
            for r in RegolaVisibilita.objects.all():
                conf.regole.setdefault(r.chiave, []).append(r)
        except Exception:
            logger.warning("scadenzario: configurazione non leggibile", exc_info=True)
            return cls()
        return conf

    @property
    def vuota(self) -> bool:
        return not self.voci and not self.regole

    def attiva(self, chiavi: list[str]) -> bool:
        """La voce più particolare con un valore decide; predefinito: attiva."""
        for chiave in reversed(chiavi):
            v = self.voci.get(chiave)
            if v is not None and v.attiva is not None:
                return bool(v.attiva)
        return True

    def modalita(self, chiavi: list[str]) -> str:
        from .models import VoceConfig

        for chiave in reversed(chiavi):
            v = self.voci.get(chiave)
            if v is not None and v.modalita:
                return v.modalita
        return VoceConfig.MODALITA_MODULO

    def regole_su(self, chiavi: list[str]) -> list:
        esito = []
        for chiave in chiavi:
            esito.extend(self.regole.get(chiave, ()))
        return esito

    def concede(self, ident: Identita, chiavi: list[str], *, gestione: bool = False,
                proprietari: frozenset[int] | None = None, ignora_ambito: bool = False) -> bool:
        """Una regola concede la voce alla persona?

        ``proprietari``: ``utenti.id`` della singola scadenza. Senza, la domanda è
        sull'intera voce e contano solo le regole con ambito «tutti». ``ignora_ambito``:
        basta una regola qualsiasi («vede almeno qualcosa qui sotto?»).
        """
        from .models import RegolaVisibilita

        for r in self.regole_su(chiavi):
            if gestione and r.livello != RegolaVisibilita.LIVELLO_GESTISCE:
                continue
            if regola_vale_per(r, ident) and (ignora_ambito or ambito_copre(r, ident, proprietari)):
                return True
        return False

    def ha_ambiti_limitati(self, ident: Identita) -> bool:
        """La persona ha almeno una regola «propri» o «team»: servono i proprietari."""
        from .models import RegolaVisibilita

        return any(
            r.ambito != RegolaVisibilita.AMBITO_TUTTI and regola_vale_per(r, ident)
            for regole in self.regole.values() for r in regole
        )

    def fonti_concesse(self, ident: Identita) -> set[str]:
        """Fonti in cui almeno una regola concede qualcosa alla persona."""
        fonti = set()
        for chiave, regole in self.regole.items():
            if chiave == CHIAVE_PANNELLO:
                continue
            if any(regola_vale_per(r, ident) for r in regole):
                fonti.add(chiave.split(SEP)[0])
        return fonti


def regola_vale_per(regola, ident: Identita) -> bool:
    if regola.ruolo_portale_id:
        return int(regola.ruolo_portale_id) in ident.ruoli_portale
    if regola.ruolo_aziendale_id:
        return int(regola.ruolo_aziendale_id) in ident.ruoli_aziendali
    return bool(regola.persona_legacy_id and ident.legacy_user_id
                and int(regola.persona_legacy_id) == int(ident.legacy_user_id))


def ambito_copre(regola, ident: Identita, proprietari: frozenset[int] | None) -> bool:
    """Stessa logica di ``core.permessi.puo_fare``: senza proprietario, solo «tutti»."""
    from .models import RegolaVisibilita

    if regola.ambito == RegolaVisibilita.AMBITO_TUTTI:
        return True
    if not proprietari or not ident.legacy_user_id:
        return False
    if int(ident.legacy_user_id) in proprietari:
        return True
    return regola.ambito == RegolaVisibilita.AMBITO_TEAM and bool(proprietari & ident.team)


# ---------------------------------------------------------------------------
# A chi è legata una scadenza (per gli ambiti «propri» e «team»)
# ---------------------------------------------------------------------------

def _legacy_da_utenti(user_ids) -> dict[int, int]:
    """{id utente Django: utenti.id}."""
    ids = {int(u) for u in user_ids if u}
    if not ids:
        return {}
    from core.models import Profile

    return {int(u): int(leg) for u, leg in Profile.objects.filter(user_id__in=ids).values_list("user_id", "legacy_user_id") if leg}


def _legacy_da_anagrafiche(anagrafica_ids) -> dict[int, int]:
    """{id anagrafica: utenti.id}."""
    ids = {int(a) for a in anagrafica_ids if a}
    if not ids:
        return {}
    from core.legacy_models import AnagraficaDipendente

    return {int(a): int(u) for a, u in AnagraficaDipendente.objects.filter(id__in=ids).values_list("id", "utente_id") if u}


def _legacy_da_asset(asset_ids) -> dict[int, frozenset[int]]:
    """{id asset: utenti.id}: la persona assegnata o i capi del reparto (come i permessi degli asset)."""
    ids = {int(a) for a in asset_ids if a}
    if not ids:
        return {}
    from assets.models import Asset
    from assets.registro_permessi import proprietario_asset

    esito, gia = {}, {}
    for asset in Asset.objects.filter(pk__in=ids):
        chiave = (asset.assigned_legacy_user_id, asset.assignment_to, asset.asset_type, asset.reparto, asset.assignment_reparto)
        if chiave not in gia:
            valore = proprietario_asset(asset)
            if isinstance(valore, (set, frozenset, list, tuple)):
                gia[chiave] = frozenset(int(v) for v in valore if v)
            else:
                gia[chiave] = frozenset({int(valore)}) if valore else frozenset()
        esito[asset.pk] = gia[chiave]
    return esito


def proprietari_voci(voci) -> dict[int, frozenset[int]]:
    """{id(voce): utenti.id delle persone a cui è legata}.

    Dagli ``extra`` delle fonti: ``legacy_user_id`` (utenti.id), ``legacy_id`` (id
    anagrafica), ``utente_id``/``responsabile_id`` (utente Django), ``asset_id``. Una
    conversione che fallisce lascia la voce senza proprietario: passa solo con «tutti».
    """
    def _leggi(funzione, chiavi_extra):
        valori = {(v.extra or {}).get(k) for v in voci for k in chiavi_extra}
        try:
            return funzione(valori)
        except Exception:
            logger.warning("scadenzario: proprietari non leggibili (%s)", chiavi_extra, exc_info=True)
            return {}

    da_utenti = _leggi(_legacy_da_utenti, ("utente_id", "responsabile_id"))
    da_anagrafiche = _leggi(_legacy_da_anagrafiche, ("legacy_id",))
    da_asset = _leggi(_legacy_da_asset, ("asset_id",))
    esito = {}
    for v in voci:
        extra = v.extra or {}
        persone = set(da_asset.get(extra.get("asset_id"), ()))
        persone.update(da_utenti.get(extra.get(k)) for k in ("utente_id", "responsabile_id"))
        persone.add(da_anagrafiche.get(extra.get("legacy_id")))
        persone.add(extra.get("legacy_user_id"))
        esito[id(v)] = frozenset(int(p) for p in persone if p)
    return esito


def configurazione_di(soggetto) -> Configurazione:
    from core.permessi.motore import _soggetto

    user, _ = _soggetto(soggetto)
    cached = getattr(user, "_scadenzario_conf", None) if user is not None else None
    if cached is not None:
        return cached
    conf = Configurazione.carica()
    if user is not None:
        try:
            user._scadenzario_conf = conf
        except AttributeError:
            pass
    return conf


def puo_gestire_pannello(soggetto) -> bool:
    ident = identita_di(soggetto)
    if ident.amministratore:
        return True
    return configurazione_di(soggetto).concede(ident, [CHIAVE_PANNELLO])


# ---------------------------------------------------------------------------
# Applicazione alle voci dello scadenzario
# ---------------------------------------------------------------------------

def _id_voce(item) -> tuple:
    return (item.source, item.kind, item.titolo, item.soggetto, item.data_scadenza, item.url)


def applica(request, voci_modulo: list, *, raccogli_sistema, sources: set[str] | None = None) -> list:
    """Voci finali per la persona.

    ``voci_modulo``: le voci che i moduli le mostrano già con i loro permessi.
    ``raccogli_sistema(fonti)``: raccolta senza permessi delle fonti indicate, per
    aggiungere le voci concesse dalle regole.
    """
    try:
        conf = configurazione_di(request)
        if conf.vuota:
            return voci_modulo
        ident = identita_di(request)
        from .models import VoceConfig

        # I proprietari servono (e si leggono) solo a chi ha una regola «propri» o «team».
        limitati = conf.ha_ambiti_limitati(ident)
        proprietari = proprietari_voci(voci_modulo) if limitati else {}
        esito, visti = [], set()
        for item in voci_modulo:
            chiavi = chiavi_voce(item)
            if not conf.attiva(chiavi):
                continue
            if (conf.modalita(chiavi) == VoceConfig.MODALITA_REGOLE and not ident.amministratore
                    and not conf.concede(ident, chiavi, proprietari=proprietari.get(id(item)))):
                continue
            esito.append(item)
            visti.add(_id_voce(item))

        fonti = conf.fonti_concesse(ident)
        if sources is not None:
            fonti &= set(sources)
        if fonti:
            di_sistema = raccogli_sistema(fonti)
            proprietari = proprietari_voci(di_sistema) if limitati else {}
            for item in di_sistema:
                if _id_voce(item) in visti:
                    continue
                chiavi = chiavi_voce(item)
                if conf.attiva(chiavi) and conf.concede(ident, chiavi, proprietari=proprietari.get(id(item))):
                    esito.append(item)
                    visti.add(_id_voce(item))
        esito.sort(key=lambda it: (it.giorni is None, it.giorni if it.giorni is not None else 0))
        return esito
    except Exception:
        logger.exception("scadenzario: regole di visibilità non applicabili, restano le voci del modulo")
        return voci_modulo
