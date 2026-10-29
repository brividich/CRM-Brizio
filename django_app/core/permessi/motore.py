"""Il punto unico che decide «questa persona puo' fare questa azione su questo modulo?».

Precedenza, dalla piu' forte:

1. superuser Django e amministratori del portale (ruolo legacy «admin» o un
   ruolo con ``amministratore=True``): tutto, su tutti i dati;
2. i ruoli della persona in ordine di ``priority``: decide il ruolo con ordine
   piu' alto **che si esprime** su quel modulo e quell'azione. Un ruolo che non
   ha la cella in matrice tace e si passa al successivo. Un ruolo con
   ``vede_tutto`` (Direzione) si esprime su vedere/esportare di ogni modulo con
   visibilita' «tutti». A parita' d'ordine: un «no» batte un «si'», fra due «si'»
   vale la visibilita' piu' ampia;
3. nessun ruolo si esprime: negato;
4. eccezione sulla persona (``EccezionePermessoPersona``): toglie o restringe
   quello che i ruoli concedono, mai il contrario. Vale su tutti i ruoli, anche
   su quelli che arrivano dall'organigramma; non tocca superuser e amministratori.

Il ruolo base (preset «dipendente») vale per tutti gli utenti attivi anche senza
appartenenza esplicita: chi non ha ruoli vede solo i propri dati, e solo dove
il ruolo base glielo concede.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.db import DatabaseError

from core.permessi.registro import (
    AMBITO_PROPRI,
    AMBITO_TEAM,
    AMBITO_TUTTI,
    AZIONI_LETTURA,
    ambito_piu_ampio,
    modulo as modulo_registrato,
)

logger = logging.getLogger(__name__)

PRESET_BASE = "dipendente"
SITECONFIG_SISTEMA_ATTIVO = "permessi.sistema_ruoli_attivo"

FONTE_SUPERUSER = "superuser"
FONTE_AMMINISTRATORE = "amministratore"
FONTE_RUOLO = "ruolo"
FONTE_VEDE_TUTTO = "vede_tutto"
FONTE_NESSUNO = "nessuno"
FONTE_ECCEZIONE = "eccezione"


def sistema_ruoli_attivo() -> bool:
    """Interruttore generale, dalla pagina «Ruoli e permessi».

    Spento: valgono le regole storiche dei moduli (liste di utenti, ruolo
    legacy). Acceso: decidono solo i ruoli, il resto e' negato.
    """
    from django.core.cache import cache

    from core.models import SiteConfig
    from core.permessi.cache import versione_permessi

    chiave = f"permessi:attivo:v{versione_permessi()}"
    try:
        cached = cache.get(chiave)
    except Exception:
        cached = None
    if cached is not None:
        return bool(cached)
    try:
        attivo = str(SiteConfig.get(SITECONFIG_SISTEMA_ATTIVO, "0") or "0").strip() == "1"
    except Exception:
        return False
    try:
        cache.set(chiave, attivo, 60)
    except Exception:
        logger.debug("permessi: cache non scrivibile (sistema attivo)", exc_info=True)
    return attivo


def id_ruolo_base() -> int | None:
    """Id del ruolo base (preset «dipendente»), in cache."""
    from django.core.cache import cache

    from core.models import AccessGroup
    from core.permessi.cache import versione_permessi

    chiave = f"permessi:ruolo_base:v{versione_permessi()}"
    try:
        cached = cache.get(chiave)
    except Exception:
        cached = None
    if cached is not None:
        return int(cached) or None
    try:
        gruppo = AccessGroup.objects.filter(preset=PRESET_BASE, is_active=True).only("id").first()
    except DatabaseError:
        return None
    valore = int(gruppo.id) if gruppo else 0
    try:
        cache.set(chiave, valore, 300)
    except Exception:
        logger.debug("permessi: cache non scrivibile (gruppo)", exc_info=True)
    return valore or None


@dataclass
class Decisione:
    consentito: bool = False
    ambito: str = ""
    fonte: str = FONTE_NESSUNO
    ruolo: str = ""
    ruolo_id: int | None = None
    ordine: int | None = None
    motivo: str = ""

    @property
    def ambito_label(self) -> str:
        from core.permessi.registro import AMBITI_LABEL

        return AMBITI_LABEL.get(self.ambito, "")


@dataclass
class _Ruolo:
    id: int
    label: str
    priority: int
    vede_tutto: bool
    amministratore: bool


@dataclass
class ContestoPermessi:
    """Tutto cio' che serve a decidere per una persona, letto una volta."""

    legacy_user_id: int | None
    superuser: bool = False
    amministratore: bool = False
    ruoli: list[_Ruolo] = field(default_factory=list)
    celle: dict[tuple[int, str, str], tuple[bool, str]] = field(default_factory=dict)
    # (modulo, azione) -> (ambito massimo, "" = negato; motivo)
    eccezioni: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    _team: frozenset[int] | None = None

    @property
    def team(self) -> frozenset[int]:
        if self._team is None:
            from core.permessi.team import team_di

            self._team = team_di(self.legacy_user_id)
        return self._team


def _soggetto(soggetto):
    """Accetta una request o uno User e restituisce (user, request)."""
    if soggetto is None:
        return None, None
    if hasattr(soggetto, "user") and hasattr(soggetto, "method"):
        return soggetto.user, soggetto
    return soggetto, None


def _legacy_user_di(user, request=None):
    if request is not None and getattr(request, "legacy_user", None) is not None:
        return request.legacy_user
    from core.legacy_utils import get_legacy_user

    try:
        return get_legacy_user(user)
    except Exception:
        return None


def ruoli_della_persona(legacy_user_id: int | None, *, includi_base: bool = True) -> list:
    """AccessGroup attivi della persona, dal piu' alto in ordine.

    Somma i ruoli assegnati a mano, quelli che arrivano dall'organigramma
    (:mod:`core.permessi.organigramma`) e il ruolo base.
    """
    from core.models import AccessGroup

    try:
        qs = AccessGroup.objects.filter(is_active=True)
        if legacy_user_id:
            from django.db.models import Q

            from core.permessi.organigramma import profili_da_organigramma
            from core.permessi.scadenze import q_appartenenze_valide

            filtro = Q(memberships__legacy_user_id=int(legacy_user_id)) & q_appartenenze_valide("memberships__")
            da_organigramma = profili_da_organigramma(legacy_user_id)
            if da_organigramma:
                filtro |= Q(id__in=da_organigramma)
            if includi_base:
                filtro |= Q(preset=PRESET_BASE)
            qs = qs.filter(filtro)
        elif includi_base:
            qs = qs.filter(preset=PRESET_BASE)
        else:
            return []
        return list(qs.distinct().order_by("-priority", "label", "id"))
    except DatabaseError:
        logger.warning("permessi: ruoli non leggibili per %s", legacy_user_id, exc_info=True)
        return []


def contesto_per(soggetto) -> ContestoPermessi:
    """Contesto memorizzato sull'utente: si legge dal DB una volta per richiesta."""
    user, request = _soggetto(soggetto)
    cached = getattr(user, "_permessi_contesto", None) if user is not None else None
    if cached is not None:
        return cached

    if user is None or not getattr(user, "is_authenticated", False):
        return ContestoPermessi(legacy_user_id=None)

    legacy_user = _legacy_user_di(user, request)
    legacy_user_id = getattr(legacy_user, "id", None)
    ctx = ContestoPermessi(legacy_user_id=int(legacy_user_id) if legacy_user_id else None)
    ctx.superuser = bool(getattr(user, "is_superuser", False))
    if legacy_user is not None:
        from core.legacy_utils import is_legacy_admin

        ctx.amministratore = bool(is_legacy_admin(legacy_user))

    gruppi = ruoli_della_persona(ctx.legacy_user_id)
    ctx.ruoli = [
        _Ruolo(
            id=int(g.id),
            label=g.label,
            priority=int(g.priority or 0),
            vede_tutto=bool(g.vede_tutto),
            amministratore=bool(g.amministratore),
        )
        for g in gruppi
    ]
    if any(r.amministratore for r in ctx.ruoli):
        ctx.amministratore = True

    if ctx.ruoli:
        from core.models import RuoloPermessoModulo

        try:
            for ruolo_id, mod, azione, consentito, ambito in RuoloPermessoModulo.objects.filter(
                ruolo_id__in=[r.id for r in ctx.ruoli]
            ).values_list("ruolo_id", "modulo", "azione", "consentito", "ambito"):
                ctx.celle[(int(ruolo_id), mod, azione)] = (bool(consentito), ambito)
        except DatabaseError:
            logger.warning("permessi: matrice non leggibile", exc_info=True)
            ctx.celle = {}

    ctx.eccezioni = eccezioni_della_persona(ctx.legacy_user_id)

    if user is not None:
        try:
            user._permessi_contesto = ctx
        except AttributeError:
            pass  # oggetto utente senza __dict__ (es. SimpleNamespace con slots)
    return ctx


def eccezioni_della_persona(legacy_user_id: int | None) -> dict[tuple[str, str], tuple[str, str]]:
    if not legacy_user_id:
        return {}
    from core.models import EccezionePermessoPersona

    try:
        return {
            (mod, azione): (ambito or "", motivo or "")
            for mod, azione, ambito, motivo in EccezionePermessoPersona.objects.filter(
                legacy_user_id=int(legacy_user_id)
            ).values_list("modulo", "azione", "ambito_massimo", "motivo")
        }
    except DatabaseError:
        logger.warning("permessi: eccezioni non leggibili per %s", legacy_user_id, exc_info=True)
        return {}


def invalida_contesto(user) -> None:
    if user is not None and hasattr(user, "_permessi_contesto"):
        try:
            del user._permessi_contesto
        except AttributeError:
            pass


def _decidi(ctx: ContestoPermessi, chiave_modulo: str, azione: str) -> Decisione:
    if ctx.superuser:
        return Decisione(True, AMBITO_TUTTI, FONTE_SUPERUSER, motivo="Superuser: vede e fa tutto.")
    if ctx.amministratore:
        return Decisione(True, AMBITO_TUTTI, FONTE_AMMINISTRATORE, motivo="Amministratore del portale.")
    esito = _decidi_dai_ruoli(ctx, chiave_modulo, azione)
    eccezione = ctx.eccezioni.get((chiave_modulo, azione))
    if eccezione is None or not esito.consentito:
        return esito
    limite, motivo = eccezione
    nota = f" Motivo: {motivo}" if motivo else ""
    if not limite:
        return Decisione(
            False, "", FONTE_ECCEZIONE, esito.ruolo, esito.ruolo_id, esito.ordine,
            motivo=f"Eccezione sulla persona: negato anche se il ruolo «{esito.ruolo}» lo concede.{nota}",
        )
    if ambito_piu_ampio(limite, esito.ambito) == limite:
        return esito  # il ruolo concede gia' non piu' del limite
    return Decisione(
        True, limite, FONTE_ECCEZIONE, esito.ruolo, esito.ruolo_id, esito.ordine,
        motivo=f"Eccezione sulla persona: il ruolo «{esito.ruolo}» darebbe di più, limitato.{nota}",
    )


def _decidi_dai_ruoli(ctx: ContestoPermessi, chiave_modulo: str, azione: str) -> Decisione:

    # Raggruppa per ordine: al primo livello d'ordine in cui qualcuno si esprime, si decide.
    livello: int | None = None
    espressi: list[tuple[_Ruolo, bool, str, str]] = []
    for ruolo in ctx.ruoli:
        if livello is not None and ruolo.priority < livello:
            break
        cella = ctx.celle.get((ruolo.id, chiave_modulo, azione))
        if cella is not None:
            consentito, ambito = cella
            espressi.append((ruolo, consentito, ambito if consentito else "", FONTE_RUOLO))
            livello = ruolo.priority
        elif ruolo.vede_tutto and azione in AZIONI_LETTURA:
            espressi.append((ruolo, True, AMBITO_TUTTI, FONTE_VEDE_TUTTO))
            livello = ruolo.priority

    if not espressi:
        return Decisione(False, "", FONTE_NESSUNO, motivo="Nessun ruolo concede questa azione.")

    negati = [e for e in espressi if not e[1]]
    if negati:
        ruolo = negati[0][0]
        return Decisione(
            False, "", FONTE_RUOLO, ruolo.label, ruolo.id, ruolo.priority,
            motivo=f"Il ruolo «{ruolo.label}» non lo consente.",
        )
    migliore = max(espressi, key=lambda e: {AMBITO_PROPRI: 1, AMBITO_TEAM: 2, AMBITO_TUTTI: 3}.get(e[2], 0))
    ruolo, _ok, ambito, fonte = migliore
    ambito = ambito_piu_ampio(*(e[2] for e in espressi)) or AMBITO_PROPRI
    return Decisione(
        True, ambito, fonte, ruolo.label, ruolo.id, ruolo.priority,
        motivo=f"Concesso dal ruolo «{ruolo.label}».",
    )


def decisione(soggetto, chiave_modulo: str, azione: str) -> Decisione:
    """Esito completo, con ruolo che decide e visibilita'. Fail-closed."""
    chiave_modulo = str(chiave_modulo or "").strip().lower()
    azione = str(azione or "").strip().lower()
    spec = modulo_registrato(chiave_modulo)
    if spec is None:
        logger.warning("permessi: modulo «%s» non registrato: accesso negato.", chiave_modulo)
        return Decisione(False, motivo=f"Modulo «{chiave_modulo}» non registrato.")
    if azione not in spec.azioni:
        logger.warning("permessi: azione «%s» non dichiarata da «%s».", azione, chiave_modulo)
        return Decisione(False, motivo=f"Azione «{azione}» non dichiarata dal modulo.")
    try:
        return _decidi(contesto_per(soggetto), chiave_modulo, azione)
    except Exception:
        logger.exception("permessi: decisione fallita (%s.%s): negato.", chiave_modulo, azione)
        return Decisione(False, motivo="Errore nella valutazione dei permessi.")


def proprietari(chiave_modulo: str, oggetto) -> frozenset[int]:
    spec = modulo_registrato(chiave_modulo)
    if spec is None or spec.proprietario is None or oggetto is None:
        return frozenset()
    try:
        valore = spec.proprietario(oggetto)
    except Exception:
        logger.warning("permessi: proprietario non leggibile per %s", chiave_modulo, exc_info=True)
        return frozenset()
    if valore is None or valore == "":
        return frozenset()
    if isinstance(valore, (list, tuple, set, frozenset)):
        return frozenset(int(v) for v in valore if v not in (None, ""))
    try:
        return frozenset({int(valore)})
    except (TypeError, ValueError):
        return frozenset()


def puo_fare(soggetto, chiave_modulo: str, azione: str, oggetto=None) -> bool:
    """La persona puo' fare ``azione`` su ``chiave_modulo`` (e su ``oggetto``, se dato)?

    Senza ``oggetto`` risponde alla domanda generale («puo' creare assenze?»).
    Con ``oggetto`` applica anche la visibilita': «propri» solo se e' il
    proprietario, «team» anche se il proprietario e' nel suo team, «tutti»
    sempre. Un record senza proprietario determinabile e' solo per «tutti».
    """
    esito = decisione(soggetto, chiave_modulo, azione)
    if not esito.consentito:
        return False
    if oggetto is None or esito.ambito == AMBITO_TUTTI:
        return True
    ctx = contesto_per(soggetto)
    owners = proprietari(chiave_modulo, oggetto)
    if not owners or ctx.legacy_user_id is None:
        return False
    if ctx.legacy_user_id in owners:
        return True
    if esito.ambito == AMBITO_TEAM:
        return bool(owners & ctx.team)
    return False


def utenti_visibili(soggetto, chiave_modulo: str, azione: str = "vedere") -> frozenset[int] | None:
    """Per filtrare elenchi: ``None`` = tutti, altrimenti gli ``utenti.id`` ammessi.

    Insieme vuoto = nessun dato (azione non concessa). L'insieme comprende
    sempre la persona stessa quando l'azione e' concessa.
    """
    esito = decisione(soggetto, chiave_modulo, azione)
    if not esito.consentito:
        return frozenset()
    if esito.ambito == AMBITO_TUTTI:
        return None
    ctx = contesto_per(soggetto)
    if ctx.legacy_user_id is None:
        return frozenset()
    ids = {ctx.legacy_user_id}
    if esito.ambito == AMBITO_TEAM:
        ids |= set(ctx.team)
    return frozenset(ids)


def anteprima(soggetto) -> list[dict]:
    """«Cosa vede questa persona»: per ogni modulo, azione per azione."""
    from core.permessi.registro import moduli_registrati

    righe = []
    for spec in moduli_registrati().values():
        azioni = []
        for azione in spec.azioni:
            esito = decisione(soggetto, spec.chiave, azione)
            azioni.append({"azione": azione, "label": spec.etichetta_azione(azione), "esito": esito})
        righe.append({
            "modulo": spec,
            "azioni": azioni,
            "qualcosa": any(a["esito"].consentito for a in azioni),
            "eccezioni": any(a["esito"].fonte == FONTE_ECCEZIONE for a in azioni),
        })
    return righe
