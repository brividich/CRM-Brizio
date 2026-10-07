"""Requisiti e stato di formazione e visite, calcolati alla data del report.

Perche' non basta leggere le tabelle gia' pronte:

- ``TrainingDeadline`` e' una cache: lo stato («valido», «scaduto»…) e' quello
  dell'ultimo ricalcolo, che non e' pianificato. Un corso scaduto dopo l'ultimo
  ricalcolo risulterebbe ancora valido. In piu' la cache conosce solo le regole
  individuali e i processi MOD.128: gli obblighi da mansione, fattori di rischio,
  area e ruolo non ci sono.
- per le visite vale l'ultima visita della *famiglia* (``TipoVisitaMedica.categoria``):
  passare da visita annuale a biennale non deve lasciare l'annuale «scaduta».

Qui i requisiti si risolvono dalle stesse fonti che usano il libretto sanitario
e lo scadenzario (resolver ``mansionario``, processi qualificati, regole di
obbligatorieta', ruoli operativi, protocollo sanitario) e lo stato si calcola
dalle registrazioni effettive con le regole gia' in uso nel portale
(``training_deadline_service._compute_stato``, ``visite.ultime_visite_correnti_ids``).
Ogni voce porta la sua *origine*, cosi' ogni riga del report e' verificabile.

Tutte le query lavorano su tutti gli id legacy delle persone (anagrafiche doppie
fuse) e riconducono i record all'id principale con ``ctx.canonico``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from anagrafica.reportistica.dati import a_blocchi, filtra_in, persone_a_blocchi

logger = logging.getLogger(__name__)

ORIGINE_FREQUENTATO = "Corso frequentato (non richiesto)"
ORIGINE_VISITA_REGISTRATA = "Visita registrata (non richiesta)"


def _aggiungi(origini: dict, chiave, etichetta: str) -> None:
    voci = origini.setdefault(chiave, [])
    if etichetta not in voci:
        voci.append(etichetta)


def _regola_in_vigore(regola, oggi: date) -> bool:
    if regola.data_inizio_validita and regola.data_inizio_validita > oggi:
        return False
    if regola.data_fine_validita and regola.data_fine_validita < oggi:
        return False
    return True


def _ruoli_in_essere(ctx, estesi: list[int]) -> dict[int, list]:
    """Ruoli operativi in essere per persona (id principale)."""
    from anagrafica.models import DipendenteRuoloOperativo

    out: dict[int, list] = {}
    for a in filtra_in(DipendenteRuoloOperativo.objects.select_related("ruolo"), "legacy_anagrafica_id", estesi):
        if a.data_fine and a.data_fine < ctx.today:
            continue
        out.setdefault(ctx.canonico(a.legacy_anagrafica_id), []).append(a.ruolo)
    return out


def _requisiti_mansione(ctx, persone: dict) -> dict:
    """Resolver unico del portale: mansione + fattori di rischio + esposizioni di area e dirette.

    Un errore qui non viene nascosto: senza i requisiti di mansione il report
    direbbe il falso, quindi la sezione risulta «non calcolabile».
    """
    from anagrafica.services import mansionario

    # La chiave include mansione e area: la stessa persona simulata su un'altra mansione
    # (cambio mansione) non deve riusare i requisiti di quella attuale.
    chiave = ("requisiti_mansione", tuple(sorted((pid, p.mansione, p.area_aziendale_id) for pid, p in persone.items())))
    if chiave not in ctx._cache:
        out: dict = {}
        for blocco in persone_a_blocchi(persone):
            out.update(mansionario.requisiti_dipendenti_dettaglio(
                list(blocco), mansioni_per_legacy={pid: p.mansione for pid, p in blocco.items()},
                aree_per_legacy={pid: p.area_aziendale_id for pid, p in blocco.items()},
            ))
        ctx._cache[chiave] = out
    return ctx._cache[chiave]


def _requisiti_processi(ctx, estesi: list[int]) -> dict[int, dict]:
    """Requisiti MOD.128 per persona (id principale), con l'origine."""
    from anagrafica.services.mpq_idoneita import requisiti_processo_dettaglio

    grezzi: dict = {}
    try:
        for blocco in a_blocchi(estesi):
            grezzi.update(requisiti_processo_dettaglio(blocco))
    except Exception:
        # Modulo processi non migrato (dev): si dice nel documento, non si tace.
        logger.warning("reportistica: requisiti dei processi qualificati non risolvibili", exc_info=True)
        ctx.avviso("Requisiti dei processi qualificati (MOD.128) non disponibili: non sono compresi.")
        return {}
    out: dict[int, dict] = {}
    for lid, dato in grezzi.items():
        acc = out.setdefault(ctx.canonico(lid), {"requisiti": {"dpi": [], "visite": [], "corsi": []}, "origini": {}})
        for dominio, voci in dato["requisiti"].items():
            acc["requisiti"].setdefault(dominio, []).extend(voci)
        for chiave, etichette in dato["origini"].items():
            for etichetta in etichette:
                _aggiungi(acc["origini"], chiave, etichetta)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Qualifiche
# ═══════════════════════════════════════════════════════════════════════════

def qualifiche_correnti(ctx, qs, persone: dict) -> tuple[dict, list]:
    """(qualifica corrente per (persona, tipo), registrazioni sostituite da un rinnovo).

    ``qs``: queryset di ``DipendenteQualifica`` gia' filtrato per tipo/categoria.
    Vale la registrazione conseguita per ultima; gli id delle anagrafiche doppie
    sono ricondotti alla persona.
    """
    registrazioni = [q for q in filtra_in(qs.select_related("tipo"), "legacy_anagrafica_id", ctx.id_estesi(persone))
                     if ctx.canonico(q.legacy_anagrafica_id) in persone]
    correnti: dict[tuple[int, int], object] = {}
    sostituite: list = []
    for q in sorted(registrazioni, key=lambda x: (x.data_conseguimento or date.min, x.id)):
        chiave = (ctx.canonico(q.legacy_anagrafica_id), q.tipo_id)
        if chiave in correnti:
            sostituite.append(correnti[chiave])
        correnti[chiave] = q
    return correnti, sostituite


# ═══════════════════════════════════════════════════════════════════════════
# Formazione
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class VoceFormazione:
    persona: int
    corso: object
    obbligatorio: bool
    origini: list[str] = field(default_factory=list)
    completato: date | None = None
    scadenza: date | None = None
    stato: str = "MAI_FREQUENTATO"
    giorni: int | None = None


def requisiti_formazione(ctx, persone: dict) -> dict[int, dict[int, list[str]]]:
    """``{persona: {corso_id: [origini]}}`` dei corsi obbligatori per ogni persona."""
    from anagrafica.models_formazione import TrainingCourse, TrainingRequirementRule

    estesi = ctx.id_estesi(persone)
    richiesti: dict[int, dict[int, list[str]]] = {pid: {} for pid in persone}
    piani_richiesti: dict[int, dict[int, list[str]]] = {pid: {} for pid in persone}

    # 1) Mansione, fattori di rischio, esposizioni (stesso resolver del libretto sanitario).
    for pid, dettaglio in _requisiti_mansione(ctx, persone).items():
        if pid not in richiesti:
            continue
        origini = dettaglio.get("origini") or {}
        req = dettaglio.get("requisiti") or {}
        for corso in req.get("corsi") or []:
            for etichetta in origini.get(("corsi", corso.pk)) or [f"Mansione «{dettaglio.get('mansione_nome', '')}»"]:
                _aggiungi(richiesti[pid], corso.pk, etichetta)
        for piano in req.get("piani") or []:
            _aggiungi(piani_richiesti[pid], piano.pk, f"Mansione «{dettaglio.get('mansione_nome', '')}» (piano {piano})")

    # 2) Processi qualificati MOD.128.
    for pid, dato in _requisiti_processi(ctx, estesi).items():
        if pid not in richiesti:
            continue
        for corso in dato["requisiti"].get("corsi") or []:
            for etichetta in dato["origini"].get(("corsi", corso.pk)) or ["Processo qualificato"]:
                _aggiungi(richiesti[pid], corso.pk, etichetta)

    # 3) Regole di obbligatorieta' per persona, ruolo operativo e area (la mansione e' gia' nel punto 1).
    regole = [
        r for r in TrainingRequirementRule.objects.filter(is_active=True, is_mandatory=True)
        .exclude(legacy_anagrafica_id__isnull=True, ruolo_operativo__isnull=True, area__isnull=True)
        .select_related("ruolo_operativo", "area")
        if _regola_in_vigore(r, ctx.today)
    ]
    if regole:
        ruoli = _ruoli_in_essere(ctx, estesi)
        # Area della persona (anche quella simulata in un cambio mansione); la scheda
        # aziendale e' gia' stata letta su tutti gli id delle anagrafiche doppie.
        aree = {pid: p.area_aziendale_id for pid, p in persone.items() if p.area_aziendale_id}
        for r in regole:
            destinatari: list[tuple[int, str]] = []
            if r.legacy_anagrafica_id:
                pid = ctx.canonico(r.legacy_anagrafica_id)
                if pid in richiesti:
                    destinatari.append((pid, "Regola individuale"))
            if r.ruolo_operativo_id:
                destinatari += [(pid, f"Ruolo «{r.ruolo_operativo}»") for pid, lista in ruoli.items()
                                if pid in richiesti and any(x.pk == r.ruolo_operativo_id for x in lista)]
            if r.area_id:
                destinatari += [(pid, f"Area «{r.area}»") for pid, area_id in aree.items()
                                if pid in richiesti and area_id == r.area_id]
            for pid, etichetta in destinatari:
                if r.corso_id:
                    _aggiungi(richiesti[pid], r.corso_id, etichetta)
                elif r.piano_id:
                    _aggiungi(piani_richiesti[pid], r.piano_id, f"{etichetta} (piano)")

    # Un piano richiesto = tutti i suoi corsi attivi.
    id_piani = {pk for voci in piani_richiesti.values() for pk in voci}
    if id_piani:
        corsi_piano: dict[int, list[int]] = {}
        for corso_id, piano_id in TrainingCourse.objects.filter(piano_id__in=id_piani, is_active=True).values_list("id", "piano_id"):
            corsi_piano.setdefault(piano_id, []).append(corso_id)
        for pid, voci in piani_richiesti.items():
            for piano_id, etichette in voci.items():
                for corso_id in corsi_piano.get(piano_id, []):
                    for etichetta in etichette:
                        _aggiungi(richiesti[pid], corso_id, etichetta)
    return richiesti


def ultimi_completamenti(ctx, persone: dict) -> dict[tuple[int, int], tuple[date, date | None]]:
    """Ultimo completamento idoneo per ``(persona, corso)``: (data completamento, scadenza)."""
    from anagrafica.models_formazione import TrainingEmployeeRecord

    out: dict[tuple[int, int], tuple[date, date | None]] = {}
    # Un completamento con data futura (sessione ancora pianificata, anno sbagliato)
    # non e' avvenuto: contandolo diventerebbe «l'ultimo» e coprirebbe quello vero.
    for lid, corso_id, completato, scadenza in filtra_in(
        TrainingEmployeeRecord.objects.filter(idoneo=True, data_completamento__lte=ctx.today)
        .values_list("legacy_anagrafica_id", "corso_id", "data_completamento", "data_scadenza"),
        "legacy_anagrafica_id", ctx.id_estesi(persone),
    ):
        chiave = (ctx.canonico(lid), corso_id)
        if chiave[0] in persone:
            precedente = out.get(chiave)
            if precedente is None or completato >= precedente[0]:
                out[chiave] = (completato, scadenza)
    return out


def formazione(ctx, persone: dict, *, solo_obbligatori: bool = True) -> list[VoceFormazione]:
    """Voci di formazione per persona e corso, con lo stato alla data del report."""
    from anagrafica.models_formazione import TrainingCourse
    from anagrafica.services.training_deadline_service import _compute_stato

    richiesti = requisiti_formazione(ctx, persone)
    completamenti = ultimi_completamenti(ctx, persone)
    coppie: dict[tuple[int, int], list[str]] = {
        (pid, corso_id): list(origini) for pid, corsi in richiesti.items() for corso_id, origini in corsi.items()
    }
    obbligatorie = set(coppie)
    if not solo_obbligatori:
        for chiave in completamenti:
            coppie.setdefault(chiave, [ORIGINE_FREQUENTATO])
    corsi = {c.pk: c for c in filtra_in(TrainingCourse.objects.all(), "pk", {c for _p, c in coppie})}
    voci: list[VoceFormazione] = []
    for (pid, corso_id), origini in coppie.items():
        corso = corsi.get(corso_id)
        if corso is None:
            continue
        ultimo = completamenti.get((pid, corso_id))
        if ultimo is None:
            if not corso.is_active:
                continue  # corso dismesso e mai frequentato: non e' un obbligo esigibile
            voci.append(VoceFormazione(pid, corso, (pid, corso_id) in obbligatorie, origini))
            continue
        stato, giorni = _compute_stato(ultimo[1], corso.validita_mesi, ctx.today)
        voci.append(VoceFormazione(pid, corso, (pid, corso_id) in obbligatorie, origini,
                                   completato=ultimo[0], scadenza=ultimo[1], stato=stato, giorni=giorni))
    return voci


# ═══════════════════════════════════════════════════════════════════════════
# Visite mediche
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class VoceVisita:
    persona: int
    tipo: object
    richiesta: bool
    origini: list[str] = field(default_factory=list)
    ultima: date | None = None
    scadenza: date | None = None
    # Scadenza secondo il tipo della visita fatta; ``scadenza`` e' quella effettiva
    # (ricalcolo prudente, vedi ``scadenza_prudente``). ``nota`` spiega la riduzione.
    scadenza_propria: date | None = None
    nota: str = ""
    visita_id: int | None = None
    # Tipo richiesto alla persona nella famiglia (periodicita' piu' stretta): per le
    # visite gia' fatte ``tipo`` e' quello della visita, che puo' essere diverso.
    tipo_richiesto: object = None

    @property
    def tipo_da_mostrare(self):
        return self.tipo_richiesto or self.tipo


def _famiglia(tipo) -> str:
    """Stessa chiave di ``visite.ultime_visite_correnti_ids``."""
    categoria = (getattr(tipo, "categoria", "") or "").strip()
    return f"cat:{categoria.lower()}" if categoria else f"tipo:{tipo.pk}"


def scadenza_prudente(data_svolgimento: date, durata_propria: int | None,
                      mesi_richiesti: int | None) -> date | None:
    """Scadenza effettiva di una visita quando la periodicita' richiesta e' cambiata.

    Regola scelta dall'azienda (07/10/2026), «ricalcolo prudente»: la visita fatta
    resta valida, ma scade alla data **piu' vicina** fra la sua scadenza naturale
    (tipo della visita fatta) e quella calcolata con la periodicita' richiesta oggi.
    Una periodicita' piu' lunga non allunga mai la scadenza da sola: serve una
    nuova visita del tipo giusto.
    """
    from anagrafica.models import _add_months

    propria = _add_months(data_svolgimento, durata_propria) if durata_propria and durata_propria > 0 else None
    if not mesi_richiesti or mesi_richiesti <= 0:
        return propria
    richiesta = _add_months(data_svolgimento, mesi_richiesti)
    return min(propria, richiesta) if propria else richiesta


def periodicita_richieste(richieste: dict) -> dict[tuple[int, str], tuple[int, object]]:
    """``{(persona, famiglia): (mesi, tipo)}``: la periodicita' piu' stretta fra i tipi richiesti."""
    out: dict[tuple[int, str], tuple[int, object]] = {}
    for pid, tipi in richieste.items():
        for tipo, _origini in tipi.values():
            mesi = int(getattr(tipo, "durata_mesi", 0) or 0)
            if mesi <= 0:
                continue
            chiave = (pid, _famiglia(tipo))
            if chiave not in out or mesi < out[chiave][0]:
                out[chiave] = (mesi, tipo)
    return out


def requisiti_visite(ctx, persone: dict) -> dict[int, dict[int, tuple[object, list[str]]]]:
    """``{persona: {tipo_id: (tipo, [origini])}}`` delle visite dovute.

    Fonti: ruoli operativi in essere, protocollo sanitario dell'ultimo
    certificato, mansione e fattori di rischio, processi qualificati.
    """
    from anagrafica.models import TipoVisitaMedica

    estesi = ctx.id_estesi(persone)
    out: dict[int, dict[int, tuple[object, list[str]]]] = {pid: {} for pid in persone}

    def _metti(pid: int, tipo, etichetta: str) -> None:
        if pid not in out or tipo is None or not tipo.is_active:
            return
        voce = out[pid].setdefault(tipo.pk, (tipo, []))
        if etichetta not in voce[1]:
            voce[1].append(etichetta)

    ruoli = _ruoli_in_essere(ctx, estesi)
    if ruoli:
        per_ruolo: dict[int, list] = {}
        for tipo in TipoVisitaMedica.objects.filter(is_active=True, obbligatoria=True).prefetch_related("ruoli_operativi"):
            for ruolo in tipo.ruoli_operativi.all():
                per_ruolo.setdefault(ruolo.pk, []).append(tipo)
        for pid, lista in ruoli.items():
            for ruolo in lista:
                for tipo in per_ruolo.get(ruolo.pk, []):
                    _metti(pid, tipo, f"Ruolo «{ruolo}»")

    try:
        from anagrafica.models_sorveglianza import RequisitoVisitaDipendente

        for req in filtra_in(RequisitoVisitaDipendente.objects.filter(attivo=True, tipo__isnull=False)
                             .select_related("tipo"), "legacy_anagrafica_id", estesi):
            _metti(ctx.canonico(req.legacy_anagrafica_id), req.tipo,
                   f"Protocollo sanitario del {req.data_certificato:%d/%m/%Y}")
    except Exception:
        logger.warning("reportistica: protocollo sanitario non leggibile", exc_info=True)
        ctx.avviso("Protocollo sanitario dei certificati non leggibile: le visite che richiede non sono comprese.")

    for pid, dettaglio in _requisiti_mansione(ctx, persone).items():
        origini = dettaglio.get("origini") or {}
        for tipo in (dettaglio.get("requisiti") or {}).get("visite") or []:
            for etichetta in origini.get(("visite", tipo.pk)) or ["Mansione"]:
                _metti(pid, tipo, etichetta)

    for pid, dato in _requisiti_processi(ctx, estesi).items():
        for tipo in dato["requisiti"].get("visite") or []:
            for etichetta in dato["origini"].get(("visite", tipo.pk)) or ["Processo qualificato"]:
                _metti(pid, tipo, etichetta)
    return out


def visite(ctx, persone: dict) -> list[VoceVisita]:
    """Visita corrente per persona e famiglia, piu' le visite dovute mai registrate."""
    from anagrafica.models import VisitaMedica
    from anagrafica.services.visite import ultime_visite_correnti_ids

    richieste = requisiti_visite(ctx, persone)
    id_correnti: set[int] = set()
    for blocco in persone_a_blocchi(persone):
        # A blocchi di persone: tutti gli id di una persona finiscono nello stesso blocco.
        id_correnti |= ultime_visite_correnti_ids(ctx.id_estesi(blocco), includi_cessati=True)
    correnti: dict[tuple[int, str], VisitaMedica] = {}
    for v in filtra_in(VisitaMedica.objects.select_related("tipo"), "pk", id_correnti):
        pid = ctx.canonico(v.legacy_anagrafica_id)
        if pid not in persone:
            continue
        chiave = (pid, _famiglia(v.tipo))
        prev = correnti.get(chiave)
        # Anagrafiche doppie: due visite «correnti» della stessa famiglia, vale la piu' recente.
        if prev is None or (v.data_svolgimento, v.pk) > (prev.data_svolgimento, prev.pk):
            correnti[chiave] = v

    voci: list[VoceVisita] = []
    coperte: set[tuple[int, str]] = set()
    origini_famiglia: dict[tuple[int, str], list[str]] = {}
    for pid, tipi in richieste.items():
        for tipo, origini in tipi.values():
            for etichetta in origini:
                _aggiungi(origini_famiglia, (pid, _famiglia(tipo)), etichetta)
    periodicita = periodicita_richieste(richieste)
    for (pid, fam), v in correnti.items():
        origini = origini_famiglia.get((pid, fam))
        coperte.add((pid, fam))
        mesi, tipo_richiesto = periodicita.get((pid, fam), (None, None))
        propria = scadenza_prudente(v.data_svolgimento, v.tipo.durata_mesi, None)
        effettiva = scadenza_prudente(v.data_svolgimento, v.tipo.durata_mesi, mesi)
        nota = ""
        if effettiva and (propria is None or effettiva < propria):
            # L'obbligo puo' venire da mansione, ruolo, protocollo o processo: si dice da dove.
            fonte = ", ".join(origini or []) or "il requisito"
            nota = (f"Scadenza anticipata: {fonte} richiede «{tipo_richiesto.nome}» "
                    f"(ogni {mesi} mesi), la visita fatta era «{v.tipo.nome}».")
        if origini and tipo_richiesto is None:
            # Richiesta senza periodicita' (durata 0): si mostra il primo tipo richiesto della famiglia.
            tipo_richiesto = next((t for t, _o in richieste.get(pid, {}).values() if _famiglia(t) == fam), None)
        voci.append(VoceVisita(pid, v.tipo, bool(origini), list(origini or [ORIGINE_VISITA_REGISTRATA]),
                               ultima=v.data_svolgimento, scadenza=effettiva, scadenza_propria=propria,
                               nota=nota, visita_id=v.pk, tipo_richiesto=tipo_richiesto if origini else None))
    for pid, tipi in richieste.items():
        for tipo, origini in tipi.values():
            chiave = (pid, _famiglia(tipo))
            if chiave in coperte:
                continue
            coperte.add(chiave)
            # Piu' tipi richiesti nella stessa famiglia: si mostra quello con la periodicita' piu' stretta.
            tipo_mostrato = periodicita.get(chiave, (None, tipo))[1]
            voci.append(VoceVisita(pid, tipo_mostrato, True, list(origini_famiglia.get(chiave) or origini),
                                   tipo_richiesto=tipo_mostrato))
    return voci


def id_qualifiche_correnti(ctx=None) -> set[int]:
    """Id delle ``DipendenteQualifica`` correnti: per persona e tipo, la conseguita per ultima.

    Una qualifica rinnovata con una nuova registrazione lascia la vecchia nel DB:
    chi elenca le scadenze deve ignorarla, altrimenti risulta «scaduta» una
    qualifica valida. Le anagrafiche doppie contano come una persona sola.
    """
    from anagrafica.models import DipendenteQualifica

    ctx = ctx or ambito()
    migliori: dict[tuple[int, int], tuple] = {}
    for pk, lid, tipo_id, conseguita in DipendenteQualifica.objects.values_list(
            "pk", "legacy_anagrafica_id", "tipo_id", "data_conseguimento"):
        chiave = (ctx.canonico(lid), tipo_id)
        valore = (conseguita or date.min, pk)
        if chiave not in migliori or valore > migliori[chiave]:
            migliori[chiave] = valore
    return {pk for _data, pk in migliori.values()}


def ambito(oggi: date | None = None):
    """Contesto aziendale (tutto il personale) per i calcoli fuori dalla reportistica."""
    from django.utils import timezone

    from anagrafica.reportistica.dati import Contesto, Perimetro

    oggi = oggi or timezone.localdate()
    return Contesto(date_from=oggi, date_to=oggi, perimetro=Perimetro(), today=oggi)
