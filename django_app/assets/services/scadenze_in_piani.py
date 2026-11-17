"""«Sposta nei piani»: le scadenze amministrative diventano piani di manutenzione.

Il registro delle scadenze amministrative (``AssetAdministrativeDeadline``) e i piani di
manutenzione si accorpano: ogni scadenza diventa l'applicazione su quell'asset di un piano
di tipo «Scadenza amministrativa» con lo stesso titolo (un piano per titolo, riusato fra
gli asset), ogni N mesi, prima scadenza = la data della scadenza, ancorato alla scadenza
teorica. Da li' in poi si registra come le altre manutenzioni (Da fare, Scadenzario, OdL).

Prima di spostare si controllano i doppioni:

- **gia' coperta da un piano**: sull'asset c'e' gia' un piano attivo con lo stesso titolo
  o la stessa sigla (VTS, SAT...), anche ereditato da gruppo o categoria → non si crea
  niente, la scadenza si spegne e fa fede il piano;
- **serie**: piu' righe dello stesso titolo sullo stesso asset (una per data) → una sola
  applicazione, periodicita' dalla distanza fra le date;
- **stesso titolo su piu' asset** → un piano solo, un'applicazione per asset.

Restano nel registro: le scadenze adempiute da una verifica impianto (si rinnovano
registrando la verifica) e quelle senza periodicita' finche' non la si indica.

Nessuna riga si cancella: la scadenza resta, non attiva, con il suo storico e il
riferimento al piano (``moved_to_plan``). Sola lettura finche' non si chiama ``applica``.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from ..models import (
    AssetAdministrativeDeadline,
    MaintenanceInterventionTemplate,
    MaintenancePlanAssignment,
    PeriodicCheckType,
)

AZIONE_SPOSTA = "sposta"
AZIONE_DOPPIONE = "doppione"
AZIONE_SENZA_PERIODO = "senza_periodo"
AZIONE_RESTA = "resta"
AZIONI_LABEL = {
    AZIONE_SPOSTA: "Diventa piano",
    AZIONE_DOPPIONE: "Doppione di un piano",
    AZIONE_SENZA_PERIODO: "Senza periodicità",
    AZIONE_RESTA: "Resta nel registro",
}
AUDIT_ACTION = "ASSET_SCADENZA_AMMINISTRATIVA_SPOSTATA_NEI_PIANI"
_SIGLA = re.compile(r"\b[A-Z]{3,}\b")
_SPAZI = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _SPAZI.sub(" ", (text or "").strip().lower())


def _sigle(text: str) -> set[str]:
    return set(_SIGLA.findall(text or ""))


def _mesi_fra(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


@dataclass
class Proposta:
    """Una riga dell'anteprima: una scadenza (o una serie) su un asset."""

    chiave: str
    azione: str
    righe: list[AssetAdministrativeDeadline]
    etichetta_piano: str
    mesi: int | None = None
    motivo: str = ""
    piano_esistente: MaintenanceInterventionTemplate | None = None
    prossima_del_piano: date | None = None

    @property
    def prima(self) -> AssetAdministrativeDeadline:
        return self.righe[0]

    @property
    def asset(self):
        return self.prima.asset

    @property
    def scadenza(self) -> date:
        return min(r.due_date for r in self.righe)

    @property
    def azione_label(self) -> str:
        return AZIONI_LABEL[self.azione]

    @property
    def selezionabile(self) -> bool:
        return self.azione in (AZIONE_SPOSTA, AZIONE_DOPPIONE, AZIONE_SENZA_PERIODO)

    @property
    def scelta_di_base(self) -> bool:
        return self.azione in (AZIONE_SPOSTA, AZIONE_DOPPIONE)


@dataclass
class Analisi:
    proposte: list[Proposta] = field(default_factory=list)

    def conta(self, azione: str) -> int:
        return sum(1 for p in self.proposte if p.azione == azione)

    @property
    def da_spostare(self) -> int:
        return self.conta(AZIONE_SPOSTA) + self.conta(AZIONE_DOPPIONE) + self.conta(AZIONE_SENZA_PERIODO)


def _etichetta(d: AssetAdministrativeDeadline) -> str:
    titolo = _SPAZI.sub(" ", d.title.strip())
    if d.component_id and d.component:
        titolo = f"{titolo} · {d.component}"
    return titolo[:120]


def _piani_sugli_asset(asset_ids: set[int]) -> dict[int, list]:
    """asset -> [(piano, prossima scadenza aperta)] dei piani attivi applicati (anche ereditati)."""
    from ..models import Asset, MaintenanceOccurrence
    from . import maintenance_domain as domain

    if not asset_ids:
        return {}
    resolutions = domain.build_plan_resolutions(asset_queryset=Asset.objects.filter(pk__in=asset_ids))
    aperte: dict[tuple[int, int], date] = {}
    for occ in MaintenanceOccurrence.objects.filter(
        asset_id__in=asset_ids, status=MaintenanceOccurrence.STATUS_OPEN,
    ).only("plan_id", "asset_id", "due_date").order_by("due_date"):
        aperte.setdefault((occ.plan_id, occ.asset_id), occ.due_date)
    out: dict[int, list] = defaultdict(list)
    for (plan_id, asset_id), resolution in resolutions.items():
        if resolution.is_conflict or resolution.is_excluded or resolution.assignment is None:
            continue
        if not resolution.plan.is_active:
            continue
        out[asset_id].append((resolution.plan, aperte.get((plan_id, asset_id))))
    return out


def analizza(*, asset_ids: set[int] | None = None) -> Analisi:
    """Anteprima: cosa succede a ogni scadenza amministrativa attiva."""
    qs = AssetAdministrativeDeadline.objects.filter(is_active=True).select_related("asset", "component")
    if asset_ids is not None:
        qs = qs.filter(asset_id__in=asset_ids)
    attive = list(qs.order_by("asset__asset_tag", "title", "due_date", "id"))
    collegate = set(
        PeriodicCheckType.objects.filter(is_active=True, administrative_deadline__isnull=False)
        .values_list("administrative_deadline_id", flat=True)
    )
    serie: dict[tuple, list[AssetAdministrativeDeadline]] = defaultdict(list)
    for d in attive:
        serie[(_norm(d.title), d.asset_id, d.component_id)].append(d)

    # Periodicita' ricavata dalle serie, per titolo: vale anche sugli asset con una riga sola.
    mesi_titolo: dict[str, int] = {}
    for (titolo, _a, _c), righe in serie.items():
        date_serie = sorted({r.due_date for r in righe})
        salti = [g for g in (_mesi_fra(a, b) for a, b in zip(date_serie, date_serie[1:])) if g > 0]
        if salti:
            mesi_titolo[titolo] = min(min(salti), mesi_titolo.get(titolo, 10**6))

    piani = _piani_sugli_asset({d.asset_id for d in attive})
    analisi = Analisi()
    for (titolo, asset_id, _comp), righe in sorted(serie.items(), key=lambda kv: (kv[1][0].asset.asset_tag, kv[0][0])):
        lead = righe[0]
        chiave = ",".join(str(r.id) for r in righe)
        etichetta = _etichetta(lead)
        if any(r.id in collegate for r in righe):
            analisi.proposte.append(Proposta(
                chiave, AZIONE_RESTA, righe, etichetta,
                motivo="Si rinnova registrando la verifica impianto collegata.",
            ))
            continue
        doppione = None
        sigle = _sigle(lead.title)
        for piano, prossima in piani.get(asset_id, []):
            if _norm(piano.label) == _norm(etichetta) or _norm(piano.label) == titolo or (sigle and sigle & _sigle(piano.label)):
                doppione = (piano, prossima)
                break
        if doppione is not None:
            analisi.proposte.append(Proposta(
                chiave, AZIONE_DOPPIONE, righe, etichetta, piano_esistente=doppione[0],
                prossima_del_piano=doppione[1],
                motivo="Sull'asset c'è già il piano: la scadenza si spegne e fa fede il piano.",
            ))
            continue
        date_serie = sorted({r.due_date for r in righe})
        salti = [g for g in (_mesi_fra(a, b) for a, b in zip(date_serie, date_serie[1:])) if g > 0]
        mesi = lead.recurrence_months or (min(salti) if salti else None) or mesi_titolo.get(titolo)
        if not mesi:
            analisi.proposte.append(Proposta(
                chiave, AZIONE_SENZA_PERIODO, righe, etichetta,
                motivo="Indica ogni quanti mesi si ripete; senza resta nel registro.",
            ))
            continue
        motivo = f"Serie di {len(righe)} righe: una sola applicazione." if len(righe) > 1 else ""
        analisi.proposte.append(Proposta(chiave, AZIONE_SPOSTA, righe, etichetta, mesi=int(mesi), motivo=motivo))
    return analisi


def _codice_piano(etichetta: str) -> str:
    return f"amm-{slugify(etichetta)}"[:80].rstrip("-") or "amm-scadenza"


def _piano_per(etichetta: str, cache: dict) -> tuple[MaintenanceInterventionTemplate, bool]:
    chiave = _norm(etichetta)
    if chiave in cache:
        return cache[chiave], False
    codice = _codice_piano(etichetta)
    piano = MaintenanceInterventionTemplate.objects.filter(code=codice).first()
    creato = False
    if piano is None:
        piano = MaintenanceInterventionTemplate.objects.create(
            code=codice,
            label=etichetta,
            maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
            is_active=True,
        )
        creato = True
    elif not piano.is_active:
        piano.is_active = True
        piano.save(update_fields=["is_active", "updated_at"])
    cache[chiave] = piano
    return piano, creato


def _fornitore_ente(issuer: str):
    from fornitori.ingressi import _fornitore_con_nome

    return _fornitore_con_nome(issuer) if (issuer or "").strip() else None


@dataclass
class Esito:
    piani_creati: int = 0
    applicazioni: int = 0
    doppioni: int = 0
    righe_spostate: int = 0
    saltate: list[str] = field(default_factory=list)
    occorrenze: int = 0


def applica(chiavi: list[str], *, mesi: dict[str, int] | None = None, user=None) -> Esito:
    """Sposta le proposte scelte (``chiavi`` = id delle righe, separati da virgola).

    Si rifa' l'analisi al momento: una scelta non piu' valida (scadenza gia' spostata o
    cambiata) si salta e lo si dice. ``mesi`` = periodicita' indicate a mano.
    """
    from core.audit import log_action

    from . import maintenance_domain as domain

    mesi = mesi or {}
    scelte = set(chiavi)
    analisi = analizza()
    proposte = {p.chiave: p for p in analisi.proposte}
    esito = Esito()
    for chiave in scelte - set(proposte):
        esito.saltate.append(f"#{chiave}: non più da spostare (già spostata o modificata)")
    oggi = timezone.localdate()
    timbro = f"{oggi:%d/%m/%Y}"
    autore = user if getattr(user, "is_authenticated", False) else None
    cache: dict = {}
    piani_toccati: set[int] = set()
    with transaction.atomic():
        for chiave in sorted(scelte & set(proposte)):
            p = proposte[chiave]
            if not p.selezionabile:
                esito.saltate.append(f"{p.asset.asset_tag} «{p.prima.title}»: {p.motivo}")
                continue
            if p.azione == AZIONE_DOPPIONE:
                for r in p.righe:
                    r.is_active = False
                    r.moved_to_plan = p.piano_esistente
                    r.notes = f"{r.notes}\n[{timbro}] Doppione del piano «{p.piano_esistente.label}»: fa fede il piano.".strip()
                    r.save(update_fields=["is_active", "moved_to_plan", "notes", "updated_at"])
                esito.doppioni += 1
                esito.righe_spostate += len(p.righe)
                piani_toccati.add(p.piano_esistente.id)
                log_action(None, AUDIT_ACTION, "assets", {
                    "operazione": "doppione_spento", "deadline_ids": [r.id for r in p.righe],
                    "plan_id": p.piano_esistente.id, "asset_id": p.asset.id,
                    "utente": getattr(autore, "username", ""),
                }, oggetto=p.prima)
                continue
            n_mesi = mesi.get(chiave) or p.mesi
            if not n_mesi or n_mesi <= 0:
                esito.saltate.append(f"{p.asset.asset_tag} «{p.prima.title}»: manca ogni quanti mesi si ripete")
                continue
            piano, creato = _piano_per(p.etichetta_piano, cache)
            esito.piani_creati += int(creato)
            piani_toccati.add(piano.id)
            fornitore = _fornitore_ente(p.prima.issuer)
            assignment, nuova = MaintenancePlanAssignment.objects.get_or_create(
                plan=piano,
                asset=p.asset,
                target_type=MaintenancePlanAssignment.TARGET_ASSET,
                defaults={
                    "frequency": MaintenancePlanAssignment.FREQ_MONTHS,
                    "interval": int(n_mesi),
                    "first_due_date": p.scadenza,
                    "warning_days": p.prima.warning_days,
                    "schedule_anchor": MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR,
                    "auto_generate": True,
                    "is_active": True,
                    "execution_mode": MaintenanceInterventionTemplate.MODE_EXTERNAL if fornitore else "",
                    "supplier": fornitore,
                },
            )
            if not nuova and not assignment.is_active:
                assignment.frequency = MaintenancePlanAssignment.FREQ_MONTHS
                assignment.interval = int(n_mesi)
                assignment.first_due_date = p.scadenza
                assignment.is_excluded = False
                assignment.is_active = True
                assignment.save()
            ids = ", ".join(f"#{r.id}" for r in p.righe)
            assignment.notes = f"{assignment.notes}\n[{timbro}] Dalle scadenze amministrative {ids}.".strip()
            assignment.save(update_fields=["notes", "updated_at"])
            for r in p.righe:
                r.is_active = False
                r.moved_to_plan = piano
                r.notes = f"{r.notes}\n[{timbro}] Spostata nel piano di manutenzione «{piano.label}».".strip()
                r.save(update_fields=["is_active", "moved_to_plan", "notes", "updated_at"])
            esito.applicazioni += 1
            esito.righe_spostate += len(p.righe)
            log_action(None, AUDIT_ACTION, "assets", {
                "operazione": "spostata_nel_piano", "deadline_ids": [r.id for r in p.righe], "plan_id": piano.id,
                "assignment_id": assignment.id, "asset_id": p.asset.id, "mesi": int(n_mesi),
                "piano_creato": creato, "utente": getattr(autore, "username", ""),
            }, oggetto=p.prima)
    if piani_toccati:
        esito.occorrenze = int(domain.generate_occurrences(plan_ids=piani_toccati).get("created", 0) or 0)
    return esito
