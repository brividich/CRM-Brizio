"""Catalogo delle sezioni dati componibili nei modelli di report.

Ogni sezione dichiara le colonne disponibili (l'utente sceglie quali stampare),
i riferimenti normativi e, se tratta dati particolari, il permesso aggiuntivo
richiesto. Il builder riceve il :class:`~anagrafica.reportistica.dati.Contesto`
(periodo + perimetro di persone) e restituisce un :class:`Risultato`.

Due famiglie:
- sezioni di anagrafica, che rispettano il perimetro di persone del modello;
- i report gia' esistenti in *Report conformità*, riusati cosi' come sono
  (perimetro aziendale, colonne fisse): un solo calcolo per i due moduli.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable

from report_conformita.registry import TONE_DANGER, TONE_OK, TONE_WARN, Kpi

from .dati import Contesto, anni_compiuti
from .permessi import perm_check

logger = logging.getLogger(__name__)

# ── Norme selezionabili nei modelli ────────────────────────────────────────
ISO_9001 = "ISO 9001"
EN_9100 = "EN 9100"
ISO_45001 = "ISO 45001"
ISO_27001 = "ISO 27001"
PDR_125 = "UNI/PdR 125:2022"
NORME = (ISO_9001, EN_9100, ISO_45001, ISO_27001, PDR_125)

GRUPPO_PERSONE = "Persone e competenze"
GRUPPO_ORGANICO = "Organico e indicatori"
GRUPPO_SICUREZZA = "Salute e sicurezza (ISO 45001)"
GRUPPO_PDR = "Parità di genere (UNI/PdR 125)"
GRUPPO_SISTEMA = "Indicatori di sistema (Report conformità)"
GRUPPI_ORDINE = (GRUPPO_PERSONE, GRUPPO_ORGANICO, GRUPPO_SICUREZZA, GRUPPO_PDR, GRUPPO_SISTEMA)


@dataclass
class Risultato:
    kpis: list[Kpi] = field(default_factory=list)
    colonne: list[tuple[str, str]] = field(default_factory=list)
    righe: list[dict] = field(default_factory=list)
    toni: list[str] = field(default_factory=list)
    note: list[str] = field(default_factory=list)

    def riga(self, valori: dict, tono: str = "") -> None:
        self.righe.append(valori)
        self.toni.append(tono)


@dataclass(frozen=True)
class Sezione:
    key: str
    titolo: str
    gruppo: str
    descrizione: str
    builder: Callable[[Contesto], Risultato]
    riferimenti: tuple[str, ...] = ()
    colonne: tuple[tuple[str, str], ...] = ()
    predefinite: tuple[str, ...] = ()
    # Permesso ulteriore oltre alla reportistica (es. dati sanitari). None = nessuno.
    permesso: Callable | None = None
    nominativa: bool = True
    usa_perimetro: bool = True
    usa_periodo: bool = False

    def consentita(self, request) -> bool:
        return self.permesso is None or bool(self.permesso(request))

    def colonne_effettive(self, scelte: list[str] | None) -> list[str]:
        validi = [k for k, _l in self.colonne]
        scelte = [k for k in (scelte or []) if k in validi]
        if scelte:
            return [k for k in validi if k in scelte]
        return list(self.predefinite) or validi


_CATALOGO: dict[str, Sezione] = {}


def _registra(sezione: Sezione) -> Sezione:
    if sezione.key in _CATALOGO:
        raise ValueError(f"Sezione duplicata: {sezione.key}")
    _CATALOGO[sezione.key] = sezione
    return sezione


# ── Utilita' ───────────────────────────────────────────────────────────────

def _d(value) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def _pct(parte: int | float, totale: int | float) -> str:
    if not totale:
        return "n/d"
    return f"{round(parte * 100 / totale)}%"


def _stato_scadenza(scadenza: date | None, oggi: date, preavviso: int) -> tuple[str, str]:
    if not scadenza:
        return "Senza scadenza", ""
    giorni = (scadenza - oggi).days
    if giorni < 0:
        return "Scaduta", TONE_DANGER
    if giorni <= preavviso:
        return f"In scadenza ({giorni} gg)", TONE_WARN
    return "Valida", TONE_OK


def _ore(value) -> Decimal:
    try:
        return Decimal(value or 0)
    except Exception:
        return Decimal(0)


def _fmt_ore(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'))}".replace(".", ",")


# ═══════════════════════════════════════════════════════════════════════════
# Persone e competenze
# ═══════════════════════════════════════════════════════════════════════════

def _elenco_personale(ctx: Contesto) -> Risultato:
    res = Risultato()
    persone = ctx.dipendenti()
    for p in persone:
        anni = anni_compiuti(p.data_assunzione, ctx.today)
        res.riga({
            "nominativo": p.nominativo, "matricola": p.matricola, "reparto": p.reparto, "area": p.area,
            "mansione": p.mansione, "ruolo": p.ruolo_aziendale, "contratto": p.contratto_label,
            "livello": p.livello, "assunzione": _d(p.data_assunzione),
            "anzianita": "" if anni is None else f"{anni} anni",
            "titolo_studio": p.titolo_studio,
            "stato": "In forza" if p.in_forza_al(ctx.today) else f"Cessato {_d(p.data_cessazione)}".strip(),
        })
    reparti = {p.reparto for p in persone if p.reparto}
    mansioni = {p.mansione for p in persone if p.mansione}
    res.kpis = [
        Kpi("Persone", len(persone)),
        Kpi("Reparti", len(reparti)),
        Kpi("Mansioni", len(mansioni)),
    ]
    res.note = [f"Situazione al {ctx.today:%d/%m/%Y}."]
    return res


_registra(Sezione(
    key="personale_elenco",
    titolo="Elenco del personale",
    gruppo=GRUPPO_PERSONE,
    descrizione="Nominativo, matricola, reparto, mansione, contratto e anzianità delle persone nel perimetro.",
    builder=_elenco_personale,
    riferimenti=(f"{ISO_9001} §7.1.2", f"{EN_9100} §7.1.2"),
    colonne=(
        ("nominativo", "Nominativo"), ("matricola", "Matricola"), ("reparto", "Reparto"),
        ("area", "Area aziendale"), ("mansione", "Mansione"), ("ruolo", "Ruolo aziendale"),
        ("contratto", "Contratto"), ("livello", "Livello"), ("assunzione", "Assunzione"),
        ("anzianita", "Anzianità"), ("titolo_studio", "Titolo di studio"), ("stato", "Stato"),
    ),
    predefinite=("nominativo", "matricola", "reparto", "mansione", "assunzione"),
))


def _qualifiche_personale(ctx: Contesto) -> Risultato:
    from anagrafica.models import DipendenteQualifica

    res = Risultato()
    persone = {p.id: p for p in ctx.dipendenti()}
    # Una qualifica rinnovata lascia la riga vecchia: per persona e tipo vale l'ultima.
    ultime: dict[tuple[int, int], DipendenteQualifica] = {}
    for q in (
        DipendenteQualifica.objects.filter(legacy_anagrafica_id__in=list(persone))
        .select_related("tipo")
        .order_by("legacy_anagrafica_id", "tipo_id", "data_conseguimento", "id")
    ):
        ultime[(q.legacy_anagrafica_id, q.tipo_id)] = q
    valide = scadute = in_scadenza = 0
    con_qualifica: set[int] = set()
    for q in sorted(ultime.values(), key=lambda x: (persone[x.legacy_anagrafica_id].nominativo.casefold(),
                                                     getattr(x.tipo, "nome", "").casefold())):
        p = persone[q.legacy_anagrafica_id]
        stato, tono = _stato_scadenza(q.data_scadenza, ctx.today, 60)
        if tono == TONE_DANGER:
            scadute += 1
        else:
            valide += 1
            if tono == TONE_WARN:
                in_scadenza += 1
        con_qualifica.add(p.id)
        tipo = q.tipo
        res.riga({
            "nominativo": p.nominativo, "reparto": p.reparto, "mansione": p.mansione,
            "qualifica": getattr(tipo, "nome", ""),
            "categoria": tipo.get_categoria_display() if tipo and getattr(tipo, "categoria", "") else "",
            "livello": q.livello or "", "numero": q.numero or "", "ente": q.ente or "",
            "conseguita": _d(q.data_conseguimento), "scadenza": _d(q.data_scadenza), "stato": stato,
            "verificata": "Sì" if q.verificata else "No",
        }, tono)
    res.kpis = [
        Kpi("Persone con qualifiche", len(con_qualifica), hint=f"su {len(persone)} nel perimetro"),
        Kpi("Qualifiche valide", valide, TONE_OK if valide else ""),
        Kpi("In scadenza entro 60 gg", in_scadenza, TONE_WARN if in_scadenza else ""),
        Kpi("Scadute", scadute, TONE_DANGER if scadute else TONE_OK),
    ]
    res.note = ["Per ogni persona e tipo di qualifica è riportata l'ultima registrazione (i rinnovi sostituiscono le precedenti)."]
    return res


_registra(Sezione(
    key="personale_qualifiche",
    titolo="Qualifiche e abilitazioni del personale",
    gruppo=GRUPPO_PERSONE,
    descrizione="Patentini, certificazioni e abilitazioni possedute, con scadenza e stato.",
    builder=_qualifiche_personale,
    riferimenti=(f"{ISO_9001} §7.2", f"{EN_9100} §7.2", f"{EN_9100} §8.5.1.2"),
    colonne=(
        ("nominativo", "Nominativo"), ("reparto", "Reparto"), ("mansione", "Mansione"),
        ("qualifica", "Qualifica"), ("categoria", "Categoria"), ("livello", "Livello"),
        ("numero", "N. certificato"), ("ente", "Ente"), ("conseguita", "Conseguita il"),
        ("scadenza", "Scadenza"), ("stato", "Stato"), ("verificata", "Verificata"),
    ),
    predefinite=("nominativo", "mansione", "qualifica", "numero", "conseguita", "scadenza", "stato"),
))


_STATI_FORMAZIONE = {
    "VALIDO": ("Valida", TONE_OK),
    "UNA_TANTUM": ("Completata (una tantum)", TONE_OK),
    "IN_SCADENZA_90": ("In scadenza ≤90 gg", ""),
    "IN_SCADENZA_30": ("In scadenza ≤30 gg", TONE_WARN),
    "SCADUTO": ("Scaduta", TONE_DANGER),
    "MAI_FREQUENTATO": ("Mai frequentata", TONE_DANGER),
}
_STATI_COPERTI = {"VALIDO", "UNA_TANTUM", "IN_SCADENZA_90", "IN_SCADENZA_30"}
_FONTI_SICUREZZA = {"LEGGE", "ACCORDO"}


def _formazione_obbligatoria(ctx: Contesto, *, solo_sicurezza: bool) -> Risultato:
    from anagrafica.models import TrainingDeadline

    res = Risultato()
    persone = {p.id: p for p in ctx.dipendenti()}
    qs = (
        TrainingDeadline.objects.filter(is_required=True, legacy_anagrafica_id__in=list(persone))
        .select_related("corso")
    )
    scadenze = []
    for s in qs:
        corso = s.corso
        if solo_sicurezza and not (
            getattr(corso, "fonte_obbligo", "") in _FONTI_SICUREZZA or getattr(corso, "categoria_id", None)
        ):
            continue
        scadenze.append(s)
    conteggi = Counter(s.stato_scadenza for s in scadenze)
    coperti = sum(1 for s in scadenze if s.stato_scadenza in _STATI_COPERTI)
    persone_ko = {s.legacy_anagrafica_id for s in scadenze if s.stato_scadenza in ("SCADUTO", "MAI_FREQUENTATO")}
    for s in sorted(scadenze, key=lambda x: (persone[x.legacy_anagrafica_id].nominativo.casefold(),
                                             getattr(x.corso, "titolo", "").casefold())):
        p = persone[s.legacy_anagrafica_id]
        stato, tono = _STATI_FORMAZIONE.get(s.stato_scadenza, (s.stato_scadenza, ""))
        corso = s.corso
        res.riga({
            "nominativo": p.nominativo, "reparto": p.reparto, "mansione": p.mansione,
            "corso": getattr(corso, "titolo", ""), "codice": getattr(corso, "codice", ""),
            "fonte": corso.get_fonte_obbligo_display() if getattr(corso, "fonte_obbligo", "") else "",
            "ore": _fmt_ore(_ore(getattr(corso, "durata_ore_teorica", 0))),
            "completato": _d(s.data_ultimo_completamento), "scadenza": _d(s.data_scadenza), "stato": stato,
        }, tono)
    totale = len(scadenze)
    res.kpis = [
        Kpi("Copertura requisiti", _pct(coperti, totale),
            (TONE_OK if coperti * 100 >= totale * 95 else TONE_WARN) if totale else "",
            f"{coperti} su {totale} requisiti"),
        Kpi("Scaduti", conteggi["SCADUTO"], TONE_DANGER if conteggi["SCADUTO"] else TONE_OK),
        Kpi("Mai frequentati", conteggi["MAI_FREQUENTATO"], TONE_DANGER if conteggi["MAI_FREQUENTATO"] else TONE_OK),
        Kpi("In scadenza ≤30 gg", conteggi["IN_SCADENZA_30"], TONE_WARN if conteggi["IN_SCADENZA_30"] else ""),
        Kpi("Persone con lacune", len(persone_ko), TONE_DANGER if persone_ko else TONE_OK),
    ]
    res.note = ["Requisiti derivati da mansione, ruolo e regole dello scadenzario formazione."]
    if solo_sicurezza:
        res.note.append("Formazione sicurezza: corsi con obbligo di legge / Accordo Stato-Regioni "
                        "o legati ai fattori di rischio (D.Lgs. 81/2008 artt. 36-37).")
    return res


_COLONNE_FORMAZIONE = (
    ("nominativo", "Nominativo"), ("reparto", "Reparto"), ("mansione", "Mansione"),
    ("corso", "Corso"), ("codice", "Codice"), ("fonte", "Fonte obbligo"), ("ore", "Ore"),
    ("completato", "Ultimo completamento"), ("scadenza", "Scadenza"), ("stato", "Stato"),
)

_registra(Sezione(
    key="personale_formazione",
    titolo="Formazione obbligatoria",
    gruppo=GRUPPO_PERSONE,
    descrizione="Requisiti formativi per persona (mansione, ruolo, regole) con ultimo completamento e scadenza.",
    builder=lambda ctx: _formazione_obbligatoria(ctx, solo_sicurezza=False),
    riferimenti=(f"{ISO_9001} §7.2", f"{EN_9100} §7.2", f"{ISO_27001} §7.2"),
    colonne=_COLONNE_FORMAZIONE,
    predefinite=("nominativo", "mansione", "corso", "completato", "scadenza", "stato"),
))


def _formazione_erogata(ctx: Contesto) -> Risultato:
    from anagrafica.models import TrainingEmployeeRecord

    res = Risultato()
    persone = {p.id: p for p in ctx.dipendenti_perimetro()}
    per_persona: dict[int, dict] = defaultdict(lambda: {"corsi": 0, "ore": Decimal(0), "titoli": []})
    for r in TrainingEmployeeRecord.objects.filter(
        legacy_anagrafica_id__in=list(persone),
        data_completamento__range=(ctx.date_from, ctx.date_to),
    ).only("legacy_anagrafica_id", "ore_frequentate", "duration_hours_snapshot", "course_title_snapshot"):
        acc = per_persona[r.legacy_anagrafica_id]
        acc["corsi"] += 1
        acc["ore"] += _ore(r.ore_frequentate) or _ore(r.duration_hours_snapshot)
        if r.course_title_snapshot and r.course_title_snapshot not in acc["titoli"]:
            acc["titoli"].append(r.course_title_snapshot)
    ore_tot = sum((v["ore"] for v in per_persona.values()), Decimal(0))
    for lid, acc in sorted(per_persona.items(), key=lambda kv: persone[kv[0]].nominativo.casefold()):
        p = persone[lid]
        res.riga({
            "nominativo": p.nominativo, "reparto": p.reparto, "mansione": p.mansione,
            "corsi": acc["corsi"], "ore": _fmt_ore(acc["ore"]), "titoli": "; ".join(acc["titoli"][:8]),
        })
    in_forza = [p for p in persone.values() if p.in_forza_al(ctx.date_to)]
    res.kpis = [
        Kpi("Ore di formazione erogate", _fmt_ore(ore_tot)),
        Kpi("Persone formate", len(per_persona), hint=f"su {len(in_forza)} in forza a fine periodo"),
        Kpi("Ore medie pro capite", _fmt_ore(ore_tot / len(in_forza)) if in_forza else "n/d",
            hint="ore erogate / persone in forza"),
        Kpi("Completamenti", sum(v["corsi"] for v in per_persona.values())),
    ]
    res.note = [f"Completamenti registrati nel periodo {ctx.periodo_label}."]
    return res


_registra(Sezione(
    key="formazione_erogata",
    titolo="Formazione erogata nel periodo",
    gruppo=GRUPPO_PERSONE,
    descrizione="Corsi completati e ore di formazione per persona nel periodo del report.",
    builder=_formazione_erogata,
    riferimenti=(f"{ISO_9001} §7.2", f"{ISO_45001} §7.2", f"{PDR_125} – Opportunità di crescita"),
    colonne=(
        ("nominativo", "Nominativo"), ("reparto", "Reparto"), ("mansione", "Mansione"),
        ("corsi", "Corsi completati"), ("ore", "Ore"), ("titoli", "Corsi"),
    ),
    predefinite=("nominativo", "reparto", "corsi", "ore", "titoli"),
    usa_periodo=True,
))


# ═══════════════════════════════════════════════════════════════════════════
# Organico e indicatori
# ═══════════════════════════════════════════════════════════════════════════

_FASCE_ETA = ((0, 29, "Fino a 29 anni"), (30, 39, "30-39 anni"), (40, 49, "40-49 anni"),
              (50, 59, "50-59 anni"), (60, 200, "60 anni e oltre"))


def _fascia_eta(eta: int | None) -> str:
    if eta is None:
        return "Non registrata"
    for lo, hi, label in _FASCE_ETA:
        if lo <= eta <= hi:
            return label
    return "Non registrata"


def _movimenti(ctx: Contesto) -> tuple[list, list]:
    tutti = ctx.dipendenti_perimetro()
    assunti = [p for p in tutti if p.data_assunzione and ctx.date_from <= p.data_assunzione <= ctx.date_to]
    cessati = [p for p in tutti if p.data_cessazione and ctx.date_from <= p.data_cessazione <= ctx.date_to]
    return assunti, cessati


def _organico(ctx: Contesto) -> Risultato:
    res = Risultato()
    tutti = ctx.dipendenti_perimetro()
    in_forza = [p for p in tutti if p.in_forza_al(ctx.today)]
    totale = len(in_forza)
    assunti, cessati = _movimenti(ctx)
    inizio = sum(1 for p in tutti if p.in_forza_al(ctx.date_from))
    fine = sum(1 for p in tutti if p.in_forza_al(ctx.date_to))
    medio = (inizio + fine) / 2
    eta = [e for e in (anni_compiuti(p.data_nascita, ctx.today) for p in in_forza) if e is not None]
    anzianita = [a for a in (anni_compiuti(p.data_assunzione, ctx.today) for p in in_forza) if a is not None]
    indeterminato = sum(1 for p in in_forza if p.contratto == "INDETERMINATO")

    res.kpis = [
        Kpi("Persone in forza", totale, hint=f"al {ctx.today:%d/%m/%Y}"),
        Kpi("Tempo indeterminato", _pct(indeterminato, totale), hint=f"{indeterminato} persone"),
        Kpi("Assunzioni nel periodo", len(assunti)),
        Kpi("Cessazioni nel periodo", len(cessati)),
        Kpi("Turnover in uscita", _pct(len(cessati), medio) if medio else "n/d",
            hint=f"cessazioni / organico medio ({medio:g})"),
        Kpi("Età media", f"{sum(eta) / len(eta):.1f}".replace(".", ",") if eta else "n/d",
            hint=f"{len(eta)} date di nascita registrate"),
        Kpi("Anzianità media (anni)", f"{sum(anzianita) / len(anzianita):.1f}".replace(".", ",") if anzianita else "n/d"),
    ]

    def _distribuzione(dimensione: str, chiave: Callable) -> None:
        conteggi = Counter(chiave(p) or "Non registrato" for p in in_forza)
        for voce, n in sorted(conteggi.items(), key=lambda kv: (-kv[1], kv[0].casefold())):
            res.riga({"dimensione": dimensione, "voce": voce, "n": n, "pct": _pct(n, totale)})

    _distribuzione("Reparto", lambda p: p.reparto)
    _distribuzione("Area aziendale", lambda p: p.area)
    _distribuzione("Contratto", lambda p: p.contratto_label)
    _distribuzione("Livello", lambda p: p.livello)
    _distribuzione("Fascia d'età", lambda p: _fascia_eta(anni_compiuti(p.data_nascita, ctx.today)))
    _distribuzione("Titolo di studio", lambda p: p.titolo_studio)
    res.note = [
        "Dati aggregati: nessun nominativo.",
        f"Movimenti e turnover nel periodo {ctx.periodo_label}; organico medio = media fra inizio e fine periodo.",
    ]
    return res


_registra(Sezione(
    key="organico_indicatori",
    titolo="Organico e indicatori del personale",
    gruppo=GRUPPO_ORGANICO,
    descrizione="Persone in forza, contratti, turnover, età e anzianità medie, distribuzioni per reparto, livello, età.",
    builder=_organico,
    riferimenti=(f"{ISO_9001} §7.1.2", f"{EN_9100} §7.1.2", f"{ISO_9001} §9.1.3"),
    colonne=(("dimensione", "Dimensione"), ("voce", "Voce"), ("n", "Persone"), ("pct", "%")),
    predefinite=("dimensione", "voce", "n", "pct"),
    nominativa=False,
    usa_periodo=True,
))


def _movimenti_personale(ctx: Contesto) -> Risultato:
    res = Risultato()
    assunti, cessati = _movimenti(ctx)
    righe = [(p.data_assunzione, "Assunzione", p) for p in assunti] + [(p.data_cessazione, "Cessazione", p) for p in cessati]
    for giorno, tipo, p in sorted(righe, key=lambda r: (r[0], r[2].nominativo.casefold())):
        res.riga({
            "data": _d(giorno), "movimento": tipo, "nominativo": p.nominativo, "reparto": p.reparto,
            "mansione": p.mansione, "contratto": p.contratto_label,
        }, TONE_OK if tipo == "Assunzione" else "")
    res.kpis = [Kpi("Assunzioni", len(assunti)), Kpi("Cessazioni", len(cessati)),
                Kpi("Saldo", len(assunti) - len(cessati))]
    res.note = [f"Movimenti nel periodo {ctx.periodo_label} (data di assunzione corrente e data di cessazione)."]
    return res


_registra(Sezione(
    key="organico_movimenti",
    titolo="Assunzioni e cessazioni",
    gruppo=GRUPPO_ORGANICO,
    descrizione="Elenco nominativo dei movimenti di personale nel periodo.",
    builder=_movimenti_personale,
    riferimenti=(f"{ISO_9001} §7.1.2",),
    colonne=(("data", "Data"), ("movimento", "Movimento"), ("nominativo", "Nominativo"),
             ("reparto", "Reparto"), ("mansione", "Mansione"), ("contratto", "Contratto")),
    predefinite=("data", "movimento", "nominativo", "reparto", "mansione"),
    usa_periodo=True,
))


# ═══════════════════════════════════════════════════════════════════════════
# Salute e sicurezza (ISO 45001)
# ═══════════════════════════════════════════════════════════════════════════

_registra(Sezione(
    key="sicurezza_formazione",
    titolo="Formazione sicurezza (D.Lgs. 81/2008)",
    gruppo=GRUPPO_SICUREZZA,
    descrizione="Solo corsi obbligatori per legge / Accordo Stato-Regioni o legati ai rischi della mansione.",
    builder=lambda ctx: _formazione_obbligatoria(ctx, solo_sicurezza=True),
    riferimenti=(f"{ISO_45001} §7.2", f"{ISO_45001} §7.3", "D.Lgs. 81/2008 artt. 36-37"),
    colonne=_COLONNE_FORMAZIONE,
    predefinite=("nominativo", "mansione", "corso", "completato", "scadenza", "stato"),
))


def _sorveglianza_sanitaria(ctx: Contesto) -> Risultato:
    from anagrafica.models import VisitaMedica

    res = Risultato()
    persone = {p.id: p for p in ctx.dipendenti()}
    ultime: dict[tuple[int, int], VisitaMedica] = {}
    for v in (
        VisitaMedica.objects.filter(legacy_anagrafica_id__in=list(persone), superata_il__isnull=True)
        .select_related("tipo")
        .only("legacy_anagrafica_id", "tipo_id", "tipo__nome", "data_svolgimento", "data_scadenza")
        .order_by("legacy_anagrafica_id", "tipo_id", "data_svolgimento", "id")
    ):
        ultime[(v.legacy_anagrafica_id, v.tipo_id)] = v
    con_visita: set[int] = set()
    scadute: set[int] = set()
    in_scadenza: set[int] = set()
    for v in sorted(ultime.values(), key=lambda x: (persone[x.legacy_anagrafica_id].nominativo.casefold(),
                                                     getattr(x.tipo, "nome", "").casefold())):
        p = persone[v.legacy_anagrafica_id]
        stato, tono = _stato_scadenza(v.data_scadenza, ctx.today, 30)
        con_visita.add(p.id)
        if tono == TONE_DANGER:
            scadute.add(p.id)
        elif tono == TONE_WARN:
            in_scadenza.add(p.id)
        res.riga({
            "nominativo": p.nominativo, "reparto": p.reparto, "mansione": p.mansione,
            "visita": getattr(v.tipo, "nome", ""), "ultima": _d(v.data_svolgimento),
            "scadenza": _d(v.data_scadenza), "stato": stato,
        }, tono)
    senza = [p for p in persone.values() if p.id not in con_visita]
    for p in senza:
        res.riga({"nominativo": p.nominativo, "reparto": p.reparto, "mansione": p.mansione,
                  "visita": "", "ultima": "", "scadenza": "", "stato": "Nessuna visita registrata"}, TONE_WARN)
    validi = len(con_visita - scadute)
    res.kpis = [
        Kpi("Persone con visita valida", _pct(validi, len(persone)), TONE_OK if persone and validi == len(persone) else TONE_WARN,
            f"{validi} su {len(persone)}"),
        Kpi("Visite scadute", len(scadute), TONE_DANGER if scadute else TONE_OK, "persone"),
        Kpi("In scadenza entro 30 gg", len(in_scadenza), TONE_WARN if in_scadenza else "", "persone"),
        Kpi("Senza visite registrate", len(senza), TONE_WARN if senza else TONE_OK),
    ]
    res.note = [
        "Riporta solo data e validità della visita: giudizio di idoneità, limitazioni e prescrizioni "
        "restano riservati al medico competente e al datore di lavoro (GDPR art. 9, D.Lgs. 81/2008 art. 41).",
    ]
    return res


_registra(Sezione(
    key="sicurezza_sorveglianza",
    titolo="Sorveglianza sanitaria – validità delle visite",
    gruppo=GRUPPO_SICUREZZA,
    descrizione="Ultima visita e scadenza per persona e tipo di visita, senza giudizio né prescrizioni.",
    builder=_sorveglianza_sanitaria,
    riferimenti=(f"{ISO_45001} §8.1", "D.Lgs. 81/2008 art. 41"),
    colonne=(("nominativo", "Nominativo"), ("reparto", "Reparto"), ("mansione", "Mansione"),
             ("visita", "Tipo visita"), ("ultima", "Ultima visita"), ("scadenza", "Scadenza"), ("stato", "Stato")),
    predefinite=("nominativo", "mansione", "visita", "ultima", "scadenza", "stato"),
    permesso=perm_check("anagrafica.visite.view"),
))


# ═══════════════════════════════════════════════════════════════════════════
# Parità di genere (UNI/PdR 125:2022)
# ═══════════════════════════════════════════════════════════════════════════

_GENERI = (("F", "Donne"), ("M", "Uomini"))


def _responsabili_ids() -> set[int]:
    from anagrafica.models import AreaAziendale, Reparto

    ids = set(Reparto.objects.filter(caporeparto_legacy_id__isnull=False).values_list("caporeparto_legacy_id", flat=True))
    ids |= set(AreaAziendale.objects.filter(responsabile_legacy_id__isnull=False).values_list("responsabile_legacy_id", flat=True))
    return {int(x) for x in ids if x}


def _parita_genere(ctx: Contesto) -> Risultato:
    from anagrafica.models import TrainingEmployeeRecord

    res = Risultato()
    tutti = ctx.dipendenti_perimetro()
    in_forza = [p for p in tutti if p.in_forza_al(ctx.today)]
    assunti, cessati = _movimenti(ctx)
    responsabili = _responsabili_ids()

    def _conta(persone) -> dict[str, int]:
        c = Counter(p.genere if p.genere in ("F", "M") else "ND" for p in persone)
        return {"F": c["F"], "M": c["M"], "ND": c["ND"]}

    def _riga(area: str, indicatore: str, persone, tono: str = "") -> dict:
        c = _conta(persone)
        tot = c["F"] + c["M"] + c["ND"]
        valori = {"area": area, "indicatore": indicatore, "donne": c["F"], "uomini": c["M"],
                  "nd": c["ND"], "totale": tot, "pct_donne": _pct(c["F"], tot)}
        res.riga(valori, tono)
        return c

    org = _riga("Organico", "Persone in forza", in_forza)
    for codice, label in sorted({(p.contratto, p.contratto_label) for p in in_forza if p.contratto}, key=lambda x: x[1]):
        _riga("Organico", f"Contratto: {label}", [p for p in in_forza if p.contratto == codice])
    for livello in sorted({p.livello for p in in_forza if p.livello}, key=str.casefold):
        _riga("Organico", f"Livello: {livello}", [p for p in in_forza if p.livello == livello])
    for reparto in sorted({p.reparto for p in in_forza if p.reparto}, key=str.casefold):
        _riga("Organico", f"Reparto: {reparto}", [p for p in in_forza if p.reparto == reparto])
    resp = _riga("Governance", "Responsabili di reparto / area", [p for p in in_forza if p.id in responsabili])
    ass = _riga("Processi HR", "Assunzioni nel periodo", assunti)
    _riga("Processi HR", "Cessazioni nel periodo", cessati)

    # Formazione: partecipanti e ore per genere nel periodo.
    ore = {"F": Decimal(0), "M": Decimal(0), "ND": Decimal(0)}
    formati: dict[str, set[int]] = {"F": set(), "M": set(), "ND": set()}
    per_id = {p.id: p for p in tutti}
    for r in TrainingEmployeeRecord.objects.filter(
        legacy_anagrafica_id__in=list(per_id), data_completamento__range=(ctx.date_from, ctx.date_to),
    ).only("legacy_anagrafica_id", "ore_frequentate", "duration_hours_snapshot"):
        g = per_id[r.legacy_anagrafica_id].genere
        g = g if g in ("F", "M") else "ND"
        ore[g] += _ore(r.ore_frequentate) or _ore(r.duration_hours_snapshot)
        formati[g].add(r.legacy_anagrafica_id)
    _riga("Opportunità di crescita", "Persone formate nel periodo",
          [per_id[i] for g in formati for i in formati[g]])
    ore_tot = sum(ore.values(), Decimal(0))
    res.riga({"area": "Opportunità di crescita", "indicatore": "Ore di formazione nel periodo",
              "donne": _fmt_ore(ore["F"]), "uomini": _fmt_ore(ore["M"]), "nd": _fmt_ore(ore["ND"]),
              "totale": _fmt_ore(ore_tot), "pct_donne": _pct(float(ore["F"]), float(ore_tot))})
    media = {g: (ore[g] / org[g]) if org[g] else None for g in ("F", "M")}
    res.riga({"area": "Opportunità di crescita", "indicatore": "Ore medie pro capite (in forza)",
              "donne": _fmt_ore(media["F"]) if media["F"] is not None else "n/d",
              "uomini": _fmt_ore(media["M"]) if media["M"] is not None else "n/d",
              "nd": "", "totale": "", "pct_donne": ""})

    tot_org = org["F"] + org["M"] + org["ND"]
    tot_resp = resp["F"] + resp["M"] + resp["ND"]
    tot_ass = ass["F"] + ass["M"] + ass["ND"]
    res.kpis = [
        Kpi("Donne in organico", _pct(org["F"], tot_org), hint=f"{org['F']} su {tot_org}"),
        Kpi("Donne tra i responsabili", _pct(resp["F"], tot_resp), hint=f"{resp['F']} su {tot_resp}"),
        Kpi("Donne tra gli assunti", _pct(ass["F"], tot_ass), hint=f"{ass['F']} su {tot_ass} nel periodo"),
        Kpi("Ore formazione medie D / U",
            f"{_fmt_ore(media['F']) if media['F'] is not None else 'n/d'} / "
            f"{_fmt_ore(media['M']) if media['M'] is not None else 'n/d'}"),
        Kpi("Genere non registrato", org["ND"], TONE_WARN if org["ND"] else TONE_OK,
            "completa l'anagrafica civile" if org["ND"] else ""),
    ]
    res.note = [
        "Dati aggregati per genere, nessun nominativo. Le righe con pochissime persone possono comunque "
        "rendere riconoscibile un individuo: valuta di accorpare prima di diffondere il documento all'esterno.",
        "Aree PdR 125 coperte: Cultura e strategia (organico), Governance (responsabili), Processi HR "
        "(assunzioni, cessazioni), Opportunità di crescita (formazione). Equità remunerativa e tutela della "
        "genitorialità non sono calcolate qui: integrale con un blocco di testo.",
        "Responsabili = capi reparto e responsabili di area aziendale da catalogo.",
    ]
    return res


_registra(Sezione(
    key="pdr125_indicatori",
    titolo="Indicatori di parità di genere",
    gruppo=GRUPPO_PDR,
    descrizione="Organico, contratti, livelli, reparti, responsabili, assunzioni, cessazioni e formazione per genere.",
    builder=_parita_genere,
    riferimenti=(f"{PDR_125} – KPI delle aree di valutazione",),
    colonne=(("area", "Area PdR 125"), ("indicatore", "Indicatore"), ("donne", "Donne"), ("uomini", "Uomini"),
             ("nd", "N.D."), ("totale", "Totale"), ("pct_donne", "% donne")),
    predefinite=("area", "indicatore", "donne", "uomini", "totale", "pct_donne"),
    nominativa=False,
    usa_periodo=True,
))


# ═══════════════════════════════════════════════════════════════════════════
# Report conformità esistenti (riuso)
# ═══════════════════════════════════════════════════════════════════════════

def _sezioni_conformita() -> None:
    from report_conformita.acl_bootstrap import PERM_AREA, PERM_VIEW
    from report_conformita.registry import ReportParams, all_reports

    for definition in all_reports():
        def _builder(ctx: Contesto, _definition=definition) -> Risultato:
            params = ReportParams(date_from=ctx.date_from, date_to=ctx.date_to, today=ctx.today)
            result = _definition.build(params)
            colonne = [(f"c{i}", label) for i, label in enumerate(result.columns)]
            res = Risultato(kpis=list(result.kpis), colonne=colonne, note=list(result.notes))
            for values, tono in zip(result.rows, result.row_tones):
                res.riga({k: values[i] if i < len(values) else "" for i, (k, _l) in enumerate(colonne)}, tono)
            return res

        def _permesso(request, _code=PERM_AREA.get(definition.area)) -> bool:
            from .permessi import has_perm

            return bool(_code) and has_perm(request, PERM_VIEW) and has_perm(request, _code)

        _registra(Sezione(
            key=f"rc:{definition.slug}",
            titolo=definition.title,
            gruppo=GRUPPO_SISTEMA,
            descrizione=definition.description + " (perimetro aziendale, colonne fisse)",
            builder=_builder,
            riferimenti=tuple(str(c) for c in definition.clausole),
            permesso=_permesso,
            usa_perimetro=False,
            usa_periodo=definition.usa_periodo,
        ))


_caricato = False


def _ensure_loaded() -> None:
    global _caricato
    if _caricato:
        return
    _caricato = True
    try:
        _sezioni_conformita()
    except Exception:
        logger.warning("reportistica: report conformità non disponibili come sezioni", exc_info=True)


def catalogo() -> list[Sezione]:
    _ensure_loaded()
    ordine = {g: i for i, g in enumerate(GRUPPI_ORDINE)}
    chiavi = list(_CATALOGO)
    return sorted(_CATALOGO.values(), key=lambda s: (ordine.get(s.gruppo, 99), chiavi.index(s.key)))


def get(key: str) -> Sezione | None:
    _ensure_loaded()
    return _CATALOGO.get(key)


def catalogo_per_gruppo(request=None) -> list[tuple[str, list[Sezione]]]:
    gruppi: dict[str, list[Sezione]] = defaultdict(list)
    for s in catalogo():
        if request is None or s.consentita(request):
            gruppi[s.gruppo].append(s)
    return [(g, gruppi[g]) for g in GRUPPI_ORDINE if gruppi.get(g)]
