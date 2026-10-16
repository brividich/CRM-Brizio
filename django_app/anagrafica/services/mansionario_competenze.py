"""Mansionario fase 3: competenze della mansione, livello calcolato, esito.

Spec ``docs/superpowers/specs/2026-10-15-mansionario-ruolo-mansione-competenze-rischio-design.md`` §3.3.

Ogni mansione ha le sue competenze (``VoceMacchinaCatalogo.mansione``, D17),
ciascuna con livello minimo, flag bloccante e requisiti formali facoltativi
(corso valido, qualifica valida, abilitazione MOD.128 operativa). La persona ha
un livello I/L/U/O per competenza (``AbilitazioneMacchinaVoce``); il livello
sulla mansione si calcola con ``SkillMatrixConfig.regola_multivoce`` (di default
«media con tetto sulla voce bloccante», D16) e si riscrive su
``AbilitazioneMacchina.livello``, così skill matrix, pool capacità e carichi
macchina leggono già il valore giusto.

Esito per persona e mansione:

- **abilitato**: livello calcolato ≥ soglia operativa, nessuna competenza sotto
  il proprio minimo, requisiti formali presenti;
- **in addestramento**: manca solo livello (competenze non bloccanti sotto il
  minimo, o livello complessivo sotto soglia);
- **non abilitato**: manca un requisito formale, oppure una competenza
  bloccante è sotto il minimo. Il livello sulla mansione resta sotto la soglia
  operativa, quindi la persona non conta negli operativi né nel pool capacità.

Una mansione senza competenze definite usa il livello assegnato a mano.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from ..models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaStorico,
    AbilitazioneMacchinaVoce,
    CompetenzaSkm,
    LivelloSkm,
    SkillMatrixConfig,
    VoceMacchinaCatalogo,
    ordinale_livello,
)

ABILITATO = "abilitato"
IN_ADDESTRAMENTO = "in_addestramento"
NON_ABILITATO = "non_abilitato"
ESITI_LABEL = {ABILITATO: "Abilitato", IN_ADDESTRAMENTO: "In addestramento", NON_ABILITATO: "Non abilitato"}
_DA_ORDINALE = {v: k for k, v in {c: ordinale_livello(c) for c, _ in LivelloSkm.choices}.items()}


def competenze(mansione: CompetenzaSkm, *, solo_attive: bool = True):
    qs = (VoceMacchinaCatalogo.objects.filter(mansione=mansione)
          .select_related("corso", "qualifica", "processo_mpq").order_by("ordine", "pk"))
    return qs.filter(attiva=True) if solo_attive else qs


def _codice(mansione: CompetenzaSkm, nome: str) -> str:
    base = f"M{mansione.pk}-" + re.sub(r"[^0-9A-Z]+", "-", (nome or "").upper()).strip("-")[:40]
    codice, n = base, 2
    while VoceMacchinaCatalogo.objects.filter(codice=codice).exists():
        codice, n = f"{base}-{n}", n + 1
    return codice


@transaction.atomic
def salva_competenza(mansione: CompetenzaSkm, *, voce: VoceMacchinaCatalogo | None = None, nome: str,
                     livello_minimo: str = "U", bloccante: bool = False, corso_id=None, qualifica_id=None,
                     processo_id=None, ordine: int = 0) -> VoceMacchinaCatalogo:
    nome = (nome or "").strip()[:150]
    if not nome:
        raise ValueError("Il nome della competenza è obbligatorio.")
    if livello_minimo not in dict(LivelloSkm.choices):
        raise ValueError(f"Livello minimo non valido: {livello_minimo!r}")
    doppione = VoceMacchinaCatalogo.objects.filter(mansione=mansione, attiva=True, nome__iexact=nome)
    if voce is not None:
        doppione = doppione.exclude(pk=voce.pk)
    if doppione.exists():
        raise ValueError(f"La mansione ha già la competenza «{nome}».")
    if voce is None:
        # Una competenza tolta in passato con lo stesso nome si riattiva: una voce
        # nuova lascerebbe orfani i livelli già registrati sulla vecchia.
        voce = (VoceMacchinaCatalogo.objects.filter(mansione=mansione, attiva=False, nome__iexact=nome)
                .order_by("pk").first())
    if voce is None:
        voce = VoceMacchinaCatalogo(mansione=mansione, codice=_codice(mansione, nome))
    voce.nome = nome
    voce.livello_minimo = livello_minimo
    voce.bloccante = bool(bloccante)
    voce.corso_id = corso_id or None
    voce.qualifica_id = qualifica_id or None
    voce.processo_mpq_id = processo_id or None
    voce.ordine = int(ordine or 0)
    voce.attiva = True
    voce.save()
    return voce


def livello_calcolato(livelli_voci: list[tuple[VoceMacchinaCatalogo, str]], regola: str) -> str:
    """Livello sulla mansione dai livelli per competenza. Una competenza senza livello vale 0."""
    if not livelli_voci:
        return ""
    ordinali = [(v, ordinale_livello(lv)) for v, lv in livelli_voci]
    tutti = [o for _, o in ordinali]
    bloccanti = [o for v, o in ordinali if v.bloccante]
    if regola == SkillMatrixConfig.REGOLA_MIN:
        valore = min(tutti)
    elif regola == SkillMatrixConfig.REGOLA_MEDIA:
        valore = math.floor(sum(tutti) / len(tutti))
    elif regola == SkillMatrixConfig.REGOLA_BLOCCANTI:
        valore = min(bloccanti) if bloccanti else min(tutti)
    else:  # MEDIA_TETTO (D16)
        valore = math.floor(sum(tutti) / len(tutti))
        if bloccanti:
            valore = min(valore, min(bloccanti))
    return _DA_ORDINALE.get(valore, "") if valore > 0 else ""


def _requisito_mancante(voce: VoceMacchinaCatalogo, legacy_id: int, oggi) -> str:
    """Testo del requisito formale che manca su questa competenza, '' se presente."""
    from .skillmatrix_qualifica import corso_valido

    if voce.corso_id and not corso_valido(legacy_id, voce.corso):
        return f"corso «{voce.corso.titolo}»"
    if voce.qualifica_id:
        from ..models import DipendenteQualifica
        valida = any(not q.is_scaduta for q in DipendenteQualifica.objects.filter(
            legacy_anagrafica_id=legacy_id, tipo_id=voce.qualifica_id))
        if not valida:
            return f"qualifica «{voce.qualifica.nome}»"
    if voce.processo_mpq_id:
        from ..models_mpq import AbilitazioneProcesso, ProcessoQualificato
        p = voce.processo_mpq
        processo_ok = p.stato == ProcessoQualificato.STATO_ATTIVO and (p.data_scadenza is None or p.data_scadenza >= oggi)
        persona_ok = AbilitazioneProcesso.objects.filter(
            legacy_anagrafica_id=legacy_id, processo=p, stato=AbilitazioneProcesso.STATO_ATTIVA).exists()
        if not (processo_ok and persona_ok):
            return f"abilitazione MOD.128 «{p.nome}»"
    return ""


class Requisiti:
    """Requisiti formali precaricati per un gruppo di persone e competenze.

    Stesse regole di ``_requisito_mancante`` con tre query in tutto invece di
    fino a tre per persona e competenza: le pagine che valutano molte persone
    (home del Mansionario, lacune, scheda della mansione) restano veloci anche
    con l'intero organico in lista.
    """

    def __init__(self, legacy_ids, voci, *, oggi=None):
        from ..models import DipendenteQualifica, TrainingDeadline
        from ..models_mpq import AbilitazioneProcesso
        from .skillmatrix_qualifica import _STATI_VALIDI

        self.oggi = oggi or timezone.localdate()
        ids = {int(i) for i in legacy_ids if i}
        voci = list(voci)
        corsi = {v.corso_id for v in voci if v.corso_id}
        qualifiche = {v.qualifica_id for v in voci if v.qualifica_id}
        processi = {v.processo_mpq_id for v in voci if v.processo_mpq_id}
        self.corsi_ok = set()
        self.qualifiche_ok = set()
        self.mpq_ok = set()
        if not ids:
            return
        if corsi:
            self.corsi_ok = {
                (lid, cid) for lid, cid, stato in TrainingDeadline.objects.filter(
                    legacy_anagrafica_id__in=ids, corso_id__in=corsi,
                ).values_list("legacy_anagrafica_id", "corso_id", "stato_scadenza")
                if stato in _STATI_VALIDI
            }
        if qualifiche:
            self.qualifiche_ok = {
                (lid, tid) for lid, tid, scad in DipendenteQualifica.objects.filter(
                    legacy_anagrafica_id__in=ids, tipo_id__in=qualifiche,
                ).values_list("legacy_anagrafica_id", "tipo_id", "data_scadenza")
                if scad is None or scad >= self.oggi
            }
        if processi:
            self.mpq_ok = set(AbilitazioneProcesso.objects.filter(
                legacy_anagrafica_id__in=ids, processo_id__in=processi, stato=AbilitazioneProcesso.STATO_ATTIVA,
            ).values_list("legacy_anagrafica_id", "processo_id"))

    def mancante(self, voce: VoceMacchinaCatalogo, legacy_id: int) -> str:
        from ..models_mpq import ProcessoQualificato

        if voce.corso_id and (legacy_id, voce.corso_id) not in self.corsi_ok:
            return f"corso «{voce.corso.titolo}»"
        if voce.qualifica_id and (legacy_id, voce.qualifica_id) not in self.qualifiche_ok:
            return f"qualifica «{voce.qualifica.nome}»"
        if voce.processo_mpq_id:
            p = voce.processo_mpq
            processo_ok = p.stato == ProcessoQualificato.STATO_ATTIVO and (p.data_scadenza is None or p.data_scadenza >= self.oggi)
            if not (processo_ok and (legacy_id, p.pk) in self.mpq_ok):
                return f"abilitazione MOD.128 «{p.nome}»"
        return ""


@dataclass
class Valutazione:
    esito: str
    livello: str
    voci: list[dict] = field(default_factory=list)      # {voce, livello, minimo, sotto, requisito}
    mancanze: list[str] = field(default_factory=list)

    @property
    def esito_label(self) -> str:
        return ESITI_LABEL[self.esito]


def valuta(abilitazione: AbilitazioneMacchina, *, voci=None, config=None, oggi=None,
           requisiti: Requisiti | None = None) -> Valutazione:
    config = config or SkillMatrixConfig.get_instance()
    oggi = oggi or timezone.localdate()
    soglia = config.soglia_operativa_ordinale
    voci = list(voci) if voci is not None else list(competenze(abilitazione.competenza)) if abilitazione.competenza_id else []
    if not voci:
        ok = abilitazione.is_operativa(soglia)
        return Valutazione(esito=ABILITATO if ok else IN_ADDESTRAMENTO, livello=abilitazione.livello,
                           mancanze=[] if ok else [f"livello {abilitazione.livello or '—'} sotto la soglia"])
    livelli = {v.voce_id: v.livello for v in abilitazione.voci.all()}
    righe, mancanze = [], []
    non_abilitato = False
    for v in voci:
        lv = livelli.get(v.pk, "")
        requisito = (requisiti.mancante(v, abilitazione.legacy_anagrafica_id) if requisiti is not None
                     else _requisito_mancante(v, abilitazione.legacy_anagrafica_id, oggi))
        if requisito:
            # Senza requisito formale la competenza non supera «I – in formazione».
            lv = "I" if lv else ""
        sotto = ordinale_livello(lv) < ordinale_livello(v.livello_minimo)
        righe.append({"voce": v, "livello": lv, "minimo": v.livello_minimo, "sotto": sotto, "requisito": requisito})
        if requisito:
            non_abilitato = True
            mancanze.append(f"{v.nome}: manca {requisito}")
        elif sotto:
            non_abilitato = non_abilitato or v.bloccante
            mancanze.append(f"{v.nome}: {lv or 'nessun livello'}, richiesto {v.livello_minimo}")
    livello = livello_calcolato([(r["voce"], r["livello"]) for r in righe], config.regola_multivoce)
    if non_abilitato:
        esito = NON_ABILITATO
        # Chi non è abilitato non può risultare operativo: il livello sulla mansione
        # resta sotto la soglia, così anche skill matrix e pool capacità lo escludono.
        if ordinale_livello(livello) >= soglia:
            livello = _DA_ORDINALE.get(soglia - 1, "")
    elif mancanze or ordinale_livello(livello) < soglia or abilitazione.stato != AbilitazioneMacchina.STATO_ATTIVA:
        esito = IN_ADDESTRAMENTO
    else:
        esito = ABILITATO
    return Valutazione(esito=esito, livello=livello, voci=righe, mancanze=mancanze)


@transaction.atomic
def registra_livelli(abilitazione: AbilitazioneMacchina, livelli: dict[int, str], *, user=None) -> Valutazione:
    """Salva i livelli per competenza, ricalcola il livello sulla mansione e lo storicizza."""
    voci = {v.pk: v for v in competenze(abilitazione.competenza)}
    for voce_id, lv in livelli.items():
        voce = voci.get(int(voce_id))
        if voce is None:
            continue
        lv = (lv or "").strip().upper()
        if lv in dict(LivelloSkm.choices):
            AbilitazioneMacchinaVoce.objects.update_or_create(abilitazione=abilitazione, voce=voce, defaults={"livello": lv})
        else:
            AbilitazioneMacchinaVoce.objects.filter(abilitazione=abilitazione, voce=voce).delete()
    val = valuta(abilitazione, voci=list(voci.values()))
    if val.livello and val.livello != abilitazione.livello:
        abilitazione.livello = val.livello
        abilitazione.save(update_fields=["livello", "updated_at"])
    AbilitazioneMacchinaStorico.objects.create(
        legacy_anagrafica_id=abilitazione.legacy_anagrafica_id, asset_id=abilitazione.asset_id,
        competenza_id=abilitazione.competenza_id, livello=abilitazione.livello,
        data_rilevazione=timezone.localdate(), fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE,
        note=f"Mansionario: valutazione competenze ({val.esito_label})"[:255],
    )
    return val


def scheda_persona(legacy_id: int) -> dict:
    """Mansioni della persona con esito, reparto principale e mansioni di rischio ricavate."""
    from .mansionario_struttura import reparto_principale

    abil = list(
        AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_id, in_lista=True, competenza__isnull=False)
        .select_related("competenza__asset", "competenza__reparto")
        .prefetch_related("voci", "competenza__mansioni_rischio", "competenza__ruoli")
    )
    config = SkillMatrixConfig.get_instance()
    voci_per_mansione: dict[int, list] = {}
    for v in VoceMacchinaCatalogo.objects.filter(mansione_id__in={a.competenza_id for a in abil}, attiva=True) \
            .select_related("corso", "qualifica", "processo_mpq").order_by("ordine", "pk"):
        voci_per_mansione.setdefault(v.mansione_id, []).append(v)
    requisiti = Requisiti([legacy_id], [v for vs in voci_per_mansione.values() for v in vs])
    righe, rischi = [], {}
    for a in abil:
        val = valuta(a, voci=voci_per_mansione.get(a.competenza_id, []), config=config, requisiti=requisiti)
        righe.append({"abilitazione": a, "mansione": a.competenza, "valutazione": val})
        for m in a.competenza.mansioni_rischio.all():
            rischi.setdefault(m.pk, {"mansione": m, "da": []})["da"].append(a.competenza.nome)
    righe.sort(key=lambda r: (-ordinale_livello(r["abilitazione"].livello), r["mansione"].nome.casefold()))
    return {
        "righe": righe,
        "reparto_principale": reparto_principale(legacy_id),
        "rischi": sorted(rischi.values(), key=lambda r: r["mansione"].nome.casefold()),
    }


def lacune() -> list[dict]:
    """Tutte le persone in lista che non sono abilitate sulla loro mansione, con cosa manca."""
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    config = SkillMatrixConfig.get_instance()
    abil = list(
        AbilitazioneMacchina.objects.filter(in_lista=True, competenza__isnull=False, competenza__attiva=True)
        .select_related("competenza__asset", "competenza__reparto").prefetch_related("voci")
    )
    voci_per_mansione: dict[int, list] = {}
    for v in VoceMacchinaCatalogo.objects.filter(mansione_id__in={a.competenza_id for a in abil}, attiva=True) \
            .select_related("corso", "qualifica", "processo_mpq").order_by("ordine", "pk"):
        voci_per_mansione.setdefault(v.mansione_id, []).append(v)
    nomi = {int(r["id"]): naming.nome_completo(r.get("nome"), r.get("cognome"))
            for r in fetch_anagrafica_rows(ids=list({a.legacy_anagrafica_id for a in abil}))} if abil else {}
    requisiti = Requisiti({a.legacy_anagrafica_id for a in abil},
                          [v for vs in voci_per_mansione.values() for v in vs])
    out = []
    for a in abil:
        val = valuta(a, voci=voci_per_mansione.get(a.competenza_id, []), config=config, requisiti=requisiti)
        if val.esito == ABILITATO:
            continue
        out.append({"legacy_id": a.legacy_anagrafica_id, "nome": nomi.get(a.legacy_anagrafica_id, f"#{a.legacy_anagrafica_id}"),
                    "mansione": a.competenza, "reparto": a.competenza.reparto_effettivo, "valutazione": val})
    ordine = {NON_ABILITATO: 0, IN_ADDESTRAMENTO: 1}
    out.sort(key=lambda r: (ordine[r["valutazione"].esito], r["nome"].casefold(), r["mansione"].nome.casefold()))
    return out
