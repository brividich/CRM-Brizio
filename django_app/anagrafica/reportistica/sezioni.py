"""Catalogo delle sezioni dati componibili nei modelli di report.

Ogni sezione dichiara:
- le colonne disponibili (l'utente sceglie quali stampare e in che ordine);
- le *opzioni* proprie (stati, categorie, giorni di preavviso, dimensioni…),
  rese nel form dell'editor e salvate nel blocco: massima granularita' senza
  scrivere codice per ogni variante;
- i riferimenti normativi e, per i dati particolari, il permesso ulteriore.

Le opzioni generali di tabella (ordinamento, raggruppamento, solo righe critiche,
numero massimo di righe, sezione nascosta se vuota) valgono per tutte e sono
applicate dal motore, non dai singoli builder.

I builder restituiscono valori *grezzi* (date, numeri, testo): la formattazione
avviene in uscita, cosi' l'Excel riceve date e numeri veri e l'ordinamento e'
corretto. Il tono di una singola cella (matrici) va in ``riga["_toni"]``.

Due famiglie di sezioni:
- di anagrafica, che rispettano il perimetro di persone del modello;
- i report di *Report conformità*, riusati cosi' come sono (perimetro aziendale).
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from report_conformita.registry import TONE_DANGER, TONE_OK, TONE_WARN, Kpi

from anagrafica.services import requisiti as calcoli
from .dati import Contesto, anni_compiuti
from .permessi import has_perm, perm_check

logger = logging.getLogger(__name__)

# ── Norme selezionabili nei modelli ────────────────────────────────────────
ISO_9001 = "ISO 9001"
EN_9100 = "EN 9100"
ISO_45001 = "ISO 45001"
ISO_27001 = "ISO 27001"
PDR_125 = "UNI/PdR 125:2022"
NORME = (ISO_9001, EN_9100, ISO_45001, ISO_27001, PDR_125)

GRUPPO_PERSONE = "Persone e competenze"
GRUPPO_MATRICI = "Matrici e scadenzari"
GRUPPO_ORGANICO = "Organico e indicatori"
GRUPPO_SICUREZZA = "Salute e sicurezza (ISO 45001)"
GRUPPO_PDR = "Parità di genere (UNI/PdR 125)"
GRUPPO_SISTEMA = "Indicatori di sistema (Report conformità)"
GRUPPI_ORDINE = (GRUPPO_PERSONE, GRUPPO_MATRICI, GRUPPO_ORGANICO, GRUPPO_SICUREZZA, GRUPPO_PDR, GRUPPO_SISTEMA)

PERM_VISITE = "anagrafica.visite.view"


# ═══════════════════════════════════════════════════════════════════════════
# Opzioni
# ═══════════════════════════════════════════════════════════════════════════

SCELTA = "scelta"
MULTI = "multi"
INTERO = "intero"
SI_NO = "si_no"


@dataclass(frozen=True)
class Opzione:
    nome: str
    etichetta: str
    tipo: str
    scelte: tuple | Callable = ()
    predefinito: object = None
    aiuto: str = ""
    minimo: int = 0
    massimo: int = 3650

    def elenco_scelte(self) -> list[tuple[str, str]]:
        try:
            raw = self.scelte() if callable(self.scelte) else self.scelte
        except Exception:
            logger.warning("reportistica: scelte non disponibili per %s", self.nome, exc_info=True)
            raw = ()
        return [(str(k), str(v)) for k, v in raw]

    def default(self):
        if self.predefinito is not None:
            return list(self.predefinito) if self.tipo == MULTI else self.predefinito
        return {MULTI: [], INTERO: 0, SI_NO: False}.get(self.tipo, "")

    def normalizza(self, valore):
        """Valore salvato o inviato -> valore valido (fallback al predefinito)."""
        if self.tipo == SI_NO:
            if isinstance(valore, list):
                valore = valore[-1] if valore else False
            return valore in (True, "on", "1", "true", "True", 1)
        if self.tipo == INTERO:
            if isinstance(valore, list):
                valore = valore[-1] if valore else None
            try:
                return max(self.minimo, min(self.massimo, int(valore)))
            except (TypeError, ValueError):
                return self.default()
        validi = {k for k, _l in self.elenco_scelte()}
        if self.tipo == MULTI:
            if valore is None:
                return self.default()
            lista = valore if isinstance(valore, list) else [valore]
            return [str(v) for v in lista if str(v) in validi]
        if isinstance(valore, list):
            valore = valore[-1] if valore else ""
        valore = "" if valore is None else str(valore)
        return valore if valore in validi or (valore == "" and not validi) else self.default()


def _opzioni_generali(colonne: tuple[tuple[str, str], ...]) -> tuple[Opzione, ...]:
    scelte_colonne = (("", "— nessuno —"), *colonne)
    generali = []
    if colonne:
        generali += [
            Opzione("ordina_per", "Ordina per", SCELTA, scelte_colonne, ""),
            Opzione("ordine", "Verso", SCELTA, (("asc", "Crescente"), ("desc", "Decrescente")), "asc"),
            Opzione("raggruppa_per", "Raggruppa per", SCELTA, scelte_colonne, "",
                    aiuto="Una sottotabella per ogni valore (es. per reparto o per persona)."),
        ]
    generali += [
        Opzione("solo_criticita", "Solo righe critiche", SI_NO, predefinito=False,
                aiuto="Mostra solo righe in rosso o arancione (scadute, in scadenza, mancanti)."),
        Opzione("max_righe", "Massimo righe", INTERO, predefinito=0, massimo=100000, aiuto="0 = tutte."),
        Opzione("nascondi_se_vuota", "Ometti la sezione se non ha righe", SI_NO, predefinito=False),
    ]
    return tuple(generali)


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
    builder: Callable[[Contesto, dict], Risultato]
    riferimenti: tuple[str, ...] = ()
    colonne: tuple[tuple[str, str], ...] = ()
    predefinite: tuple[str, ...] = ()
    opzioni: tuple[Opzione, ...] = ()
    # Permesso ulteriore oltre alla reportistica (es. dati sanitari). None = nessuno.
    permesso: Callable | None = None
    nominativa: bool = True
    usa_perimetro: bool = True
    usa_periodo: bool = False
    # Colonne decise dai dati (matrici, report conformità): niente scelta colonne.
    colonne_dinamiche: bool = False

    def consentita(self, request) -> bool:
        return self.permesso is None or bool(self.permesso(request))

    def colonne_effettive(self, scelte: list[str] | None) -> list[str]:
        """Colonne da stampare nell'ordine scelto; nessuna scelta = predefinite."""
        validi = [k for k, _l in self.colonne]
        scelte = [k for k in dict.fromkeys(scelte or []) if k in validi]
        return scelte or list(self.predefinite) or validi

    def tutte_le_opzioni(self) -> tuple[Opzione, ...]:
        return self.opzioni + _opzioni_generali(() if self.colonne_dinamiche else self.colonne)

    def valori_opzioni(self, salvate: dict | None) -> dict:
        salvate = salvate if isinstance(salvate, dict) else {}
        return {o.nome: (o.normalizza(salvate[o.nome]) if o.nome in salvate else o.default())
                for o in self.tutte_le_opzioni()}

    def calcola(self, ctx: Contesto, opzioni: dict | None = None) -> Risultato:
        return self.builder(ctx, self.valori_opzioni(opzioni))


_CATALOGO: dict[str, Sezione] = {}


def _registra(sezione: Sezione) -> Sezione:
    if sezione.key in _CATALOGO:
        raise ValueError(f"Sezione duplicata: {sezione.key}")
    nomi = [o.nome for o in sezione.tutte_le_opzioni()]
    if len(nomi) != len(set(nomi)):
        raise ValueError(f"Opzioni duplicate in {sezione.key}")
    _CATALOGO[sezione.key] = sezione
    return sezione


# ── Utilita' ───────────────────────────────────────────────────────────────

def _d(value) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def _pct(parte: int | float, totale: int | float) -> str:
    if not totale:
        return "n/d"
    return f"{round(parte * 100 / totale)}%"


def _ore(value) -> Decimal:
    try:
        return Decimal(value or 0)
    except Exception:
        return Decimal(0)


def _ore_record(r) -> Decimal:
    """Ore di un completamento: frequentate, altrimenti durata salvata, altrimenti durata del corso.

    Un completamento senza ore registrate non vale 0 ore: falserebbe totali, medie e
    i filtri «meno di N ore».
    """
    return (_ore(r.ore_frequentate) or _ore(r.duration_hours_snapshot)
            or _ore(getattr(r.corso, "durata_ore_teorica", 0)))


def _fmt_ore(value: Decimal | None) -> str:
    if value is None:
        return "n/d"
    return f"{Decimal(value).quantize(Decimal('0.1'))}".replace(".", ",")


def _stato_scadenza(scadenza: date | None, oggi: date, preavviso: int) -> tuple[str, str, str]:
    """(codice, etichetta, tono) di una scadenza."""
    if not scadenza:
        return "senza", "Senza scadenza", ""
    giorni = (scadenza - oggi).days
    if giorni < 0:
        return "scaduta", "Scaduta", TONE_DANGER
    if giorni <= preavviso:
        return "in_scadenza", f"In scadenza ({giorni} gg)", TONE_WARN
    return "valida", "Valida", TONE_OK


_MESI = ("", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
         "ottobre", "novembre", "dicembre")


def _mese(giorno: date) -> str:
    """«2026-09 settembre»: leggibile e ordinabile come testo."""
    return f"{giorno:%Y-%m} {_MESI[giorno.month]}"


def _soglia(n: int, k: int) -> object:
    """Anonimato statistico: con soglia k>1 i conteggi fra 1 e k-1 diventano «<k»."""
    if k > 1 and 0 < n < k:
        return f"<{k}"
    return n


_STATI_SCADENZA = (("valida", "Valida"), ("in_scadenza", "In scadenza"), ("scaduta", "Scaduta"),
                   ("senza", "Senza scadenza"))


def _scelte_tipi_qualifica():
    from anagrafica.models import TipoQualifica

    return [(str(t.pk), t.nome) for t in TipoQualifica.objects.filter(is_active=True).order_by("nome")]


def _scelte_categorie_qualifica():
    from anagrafica.models import TipoQualifica

    return TipoQualifica.CATEGORIA_CHOICES


def _scelte_fonti():
    from anagrafica.models import TrainingCourse

    return TrainingCourse.FONTE_OBBLIGO_CHOICES


def _scelte_tipi_visita():
    from anagrafica.models import TipoVisitaMedica

    return [(str(t.pk), t.nome) for t in TipoVisitaMedica.objects.filter(is_active=True).order_by("nome")]


def _scelte_processi():
    from anagrafica.models import ProcessoQualificato

    return [(str(p.pk), p.nome) for p in ProcessoQualificato.objects.order_by("nome")]


def _opz_qualifiche(preavviso: int = 60) -> tuple[Opzione, ...]:
    return (
        Opzione("categorie", "Categorie di qualifica", MULTI, _scelte_categorie_qualifica, aiuto="Vuoto = tutte."),
        Opzione("tipi", "Qualifiche specifiche", MULTI, _scelte_tipi_qualifica, aiuto="Vuoto = tutte."),
        Opzione("preavviso", "Giorni di preavviso «in scadenza»", INTERO, predefinito=preavviso),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Persone e competenze
# ═══════════════════════════════════════════════════════════════════════════

def _elenco_personale(ctx: Contesto, o: dict) -> Risultato:
    res = Risultato()
    persone = ctx.dipendenti()
    for p in persone:
        anni = anni_compiuti(p.data_assunzione, ctx.today)
        res.riga({
            "nominativo": p.nominativo, "matricola": p.matricola, "reparto": p.reparto, "area": p.area,
            "mansione": p.mansione, "ruolo": p.ruolo_aziendale, "contratto": p.contratto_label,
            "livello": p.livello, "assunzione": p.data_assunzione, "anzianita": anni,
            "titolo_studio": p.titolo_studio, "cessazione": p.cessazione_effettiva,
            "stato": "In forza" if p.in_forza_al(ctx.today) else "Cessato",
        })
    res.kpis = [
        Kpi("Persone", len(persone)),
        Kpi("Reparti", len({p.reparto for p in persone if p.reparto})),
        Kpi("Mansioni", len({p.mansione for p in persone if p.mansione})),
    ]
    res.note = [f"Situazione al {ctx.today:%d/%m/%Y}. Anzianità in anni dalla data di assunzione corrente."]
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
        ("anzianita", "Anzianità (anni)"), ("titolo_studio", "Titolo di studio"),
        ("cessazione", "Cessazione"), ("stato", "Stato"),
    ),
    predefinite=("nominativo", "matricola", "reparto", "mansione", "assunzione"),
))


def _qualifiche_filtrate(o: dict):
    """Qualifiche che rispettano i filtri di sezione, senza ancora il filtro sulle persone."""
    from anagrafica.models import DipendenteQualifica

    qs = DipendenteQualifica.objects.all()
    if o.get("categorie"):
        qs = qs.filter(tipo__categoria__in=o["categorie"])
    if o.get("tipi"):
        qs = qs.filter(tipo_id__in=[int(t) for t in o["tipi"]])
    if o.get("solo_verificate"):
        qs = qs.filter(verificata=True)
    return qs


_qualifiche_correnti = calcoli.qualifiche_correnti


def _riga_qualifica(p, q, *, conseguita, scadenza, numero, livello, ente, stato, verificata, oggi) -> dict:
    tipo = q.tipo
    return {
        "nominativo": p.nominativo, "matricola": p.matricola, "reparto": p.reparto, "mansione": p.mansione,
        "qualifica": getattr(tipo, "nome", ""),
        "categoria": tipo.get_categoria_display() if tipo and getattr(tipo, "categoria", "") else "",
        "livello": livello or "", "numero": numero or "", "ente": ente or "",
        "conseguita": conseguita, "scadenza": scadenza,
        "giorni": (scadenza - oggi).days if scadenza else None,
        "stato": stato, "verificata": "Sì" if verificata else "No",
    }


def _qualifiche_personale(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.models import DipendenteQualificaStorico

    res = Risultato()
    persone = {p.id: p for p in ctx.dipendenti()}
    base = _qualifiche_filtrate(o)
    correnti, sostituite = _qualifiche_correnti(ctx, base, persone)
    conteggi = Counter()
    con_qualifica: set[int] = set()
    righe: list[tuple[dict, str]] = []
    for (pid, _t), q in correnti.items():
        codice, stato, tono = _stato_scadenza(q.data_scadenza, ctx.today, o["preavviso"])
        if o["stati"] and codice not in o["stati"]:
            continue
        conteggi[codice] += 1
        con_qualifica.add(pid)
        righe.append((_riga_qualifica(persone[pid], q, conseguita=q.data_conseguimento, scadenza=q.data_scadenza,
                                      numero=q.numero, livello=q.livello, ente=q.ente, stato=stato,
                                      verificata=q.verificata, oggi=ctx.today), tono))
    if o["storico"]:
        # Rinnovi: le registrazioni superate e gli snapshot dello storico (DipendenteQualificaStorico).
        attuali = {(q.pk, q.data_conseguimento, q.data_scadenza) for q in correnti.values()}
        for q in sostituite:
            p = persone[ctx.canonico(q.legacy_anagrafica_id)]
            righe.append((_riga_qualifica(p, q, conseguita=q.data_conseguimento, scadenza=q.data_scadenza,
                                          numero=q.numero, livello=q.livello, ente=q.ente,
                                          stato="Sostituita da rinnovo", verificata=q.verificata, oggi=ctx.today), ""))
        per_pk = {q.pk: q for q in list(correnti.values()) + sostituite}
        for snap in DipendenteQualificaStorico.objects.filter(qualifica_id__in=list(per_pk)):
            q = per_pk[snap.qualifica_id]
            if (q.pk, snap.data_conseguimento, snap.data_scadenza) in attuali:
                continue  # snapshot dello stato corrente: e' gia' la riga principale
            p = persone[ctx.canonico(q.legacy_anagrafica_id)]
            righe.append((_riga_qualifica(p, q, conseguita=snap.data_conseguimento, scadenza=snap.data_scadenza,
                                          numero=snap.numero, livello=snap.livello, ente=snap.ente,
                                          stato="Sostituita da rinnovo", verificata=False, oggi=ctx.today), ""))
    for riga, tono in sorted(righe, key=lambda rt: (rt[0]["nominativo"].casefold(), rt[0]["qualifica"].casefold(),
                                                     rt[0]["conseguita"] or date.min)):
        res.riga(riga, tono)
    res.kpis = [
        Kpi("Persone con qualifiche", len(con_qualifica), hint=f"su {len(persone)} nel perimetro"),
        Kpi("Valide", conteggi["valida"] + conteggi["senza"], TONE_OK if conteggi["valida"] + conteggi["senza"] else ""),
        Kpi(f"In scadenza entro {o['preavviso']} gg", conteggi["in_scadenza"], TONE_WARN if conteggi["in_scadenza"] else ""),
        Kpi("Scadute", conteggi["scaduta"], TONE_DANGER if conteggi["scaduta"] else TONE_OK),
    ]
    res.note = ["Per ogni persona e tipo di qualifica vale la registrazione conseguita per ultima."
                + (" Sono elencate anche le registrazioni sostituite dai rinnovi." if o["storico"] else "")]
    ctx.segnala_esclusi(base.values_list("legacy_anagrafica_id", flat=True),
                                 incluse=persone, cosa="qualifiche")
    return res


_registra(Sezione(
    key="personale_qualifiche",
    titolo="Qualifiche e abilitazioni del personale",
    gruppo=GRUPPO_PERSONE,
    descrizione="Patentini, certificazioni e abilitazioni possedute, con scadenza e stato.",
    builder=_qualifiche_personale,
    riferimenti=(f"{ISO_9001} §7.2", f"{EN_9100} §7.2", f"{EN_9100} §8.5.1.2"),
    colonne=(
        ("nominativo", "Nominativo"), ("matricola", "Matricola"), ("reparto", "Reparto"), ("mansione", "Mansione"),
        ("qualifica", "Qualifica"), ("categoria", "Categoria"), ("livello", "Livello"),
        ("numero", "N. certificato"), ("ente", "Ente"), ("conseguita", "Conseguita il"),
        ("scadenza", "Scadenza"), ("giorni", "Giorni alla scadenza"), ("stato", "Stato"), ("verificata", "Verificata"),
    ),
    predefinite=("nominativo", "mansione", "qualifica", "numero", "conseguita", "scadenza", "stato"),
    opzioni=_opz_qualifiche() + (
        Opzione("stati", "Stati da includere", MULTI, _STATI_SCADENZA, aiuto="Vuoto = tutti."),
        Opzione("solo_verificate", "Solo qualifiche verificate", SI_NO, predefinito=False),
        Opzione("storico", "Includi anche le registrazioni rinnovate (storico)", SI_NO, predefinito=False),
    ),
))


_STATI_FORMAZIONE = {
    "VALIDO": ("Valida", TONE_OK),
    "UNA_TANTUM": ("Completata (una tantum)", TONE_OK),
    "IN_SCADENZA_90": ("In scadenza entro 90 gg", ""),
    "IN_SCADENZA_30": ("In scadenza entro 30 gg", TONE_WARN),
    "SCADUTO": ("Scaduta", TONE_DANGER),
    "MAI_FREQUENTATO": ("Mai frequentata", TONE_DANGER),
}
_STATI_COPERTI = {"VALIDO", "UNA_TANTUM", "IN_SCADENZA_90", "IN_SCADENZA_30"}
_FONTI_SICUREZZA = {"LEGGE", "ACCORDO"}
_SCELTE_STATI_FORMAZIONE = tuple((k, v[0]) for k, v in _STATI_FORMAZIONE.items())


def _corso_sicurezza(corso) -> bool:
    return getattr(corso, "fonte_obbligo", "") in _FONTI_SICUREZZA or bool(getattr(corso, "categoria_id", None))


def _voci_formazione(ctx: Contesto, o: dict, persone: dict, *, solo_sicurezza: bool) -> list:
    """Voci di formazione (persona × corso) filtrate dalle opzioni di sezione."""
    voci = calcoli.formazione(ctx, persone, solo_obbligatori=o.get("solo_obbligatori", True))
    if o.get("fonti"):
        voci = [v for v in voci if getattr(v.corso, "fonte_obbligo", "") in o["fonti"]]
    if solo_sicurezza:
        voci = [v for v in voci if _corso_sicurezza(v.corso)]
    if o.get("stati"):
        voci = [v for v in voci if v.stato in o["stati"]]
    return voci


def _formazione_obbligatoria(ctx: Contesto, o: dict, *, solo_sicurezza: bool) -> Risultato:
    res = Risultato()
    persone = {p.id: p for p in ctx.dipendenti()}
    voci = _voci_formazione(ctx, o, persone, solo_sicurezza=solo_sicurezza)
    richieste = [v for v in voci if v.obbligatorio]
    conteggi = Counter(v.stato for v in richieste)
    coperti = sum(1 for v in richieste if v.stato in _STATI_COPERTI)
    persone_ko = {v.persona for v in richieste if v.stato in ("SCADUTO", "MAI_FREQUENTATO")}
    for v in sorted(voci, key=lambda x: (persone[x.persona].nominativo.casefold(),
                                         getattr(x.corso, "titolo", "").casefold())):
        p = persone[v.persona]
        stato, tono = _STATI_FORMAZIONE.get(v.stato, (v.stato, ""))
        corso = v.corso
        res.riga({
            "nominativo": p.nominativo, "matricola": p.matricola, "reparto": p.reparto, "mansione": p.mansione,
            "corso": getattr(corso, "titolo", ""), "codice": getattr(corso, "codice", ""),
            "fonte": corso.get_fonte_obbligo_display() if getattr(corso, "fonte_obbligo", "") else "",
            "riferimento": getattr(corso, "riferimento_fonte", "") or "",
            "ore": _ore(getattr(corso, "durata_ore_teorica", 0)),
            "obbligatorio": "Sì" if v.obbligatorio else "No",
            "origine": "; ".join(v.origini),
            "completato": v.completato, "scadenza": v.scadenza,
            "giorni": v.giorni, "stato": stato,
        }, tono if v.obbligatorio else "")
    totale = len(richieste)
    res.kpis = [
        Kpi("Copertura requisiti", _pct(coperti, totale),
            (TONE_OK if coperti * 100 >= totale * 95 else TONE_WARN) if totale else "",
            f"{coperti} su {totale} requisiti"),
        Kpi("Scaduti", conteggi["SCADUTO"], TONE_DANGER if conteggi["SCADUTO"] else TONE_OK),
        Kpi("Mai frequentati", conteggi["MAI_FREQUENTATO"], TONE_DANGER if conteggi["MAI_FREQUENTATO"] else TONE_OK),
        Kpi("In scadenza entro 30 gg", conteggi["IN_SCADENZA_30"], TONE_WARN if conteggi["IN_SCADENZA_30"] else ""),
        Kpi("Persone con lacune", len(persone_ko), TONE_DANGER if persone_ko else TONE_OK),
    ]
    res.note = [
        f"Stato calcolato al {ctx.today:%d/%m/%Y} dall'ultimo completamento idoneo di ogni corso.",
        "Requisiti da mansione e fattori di rischio, esposizioni di area, ruoli operativi, regole di "
        "obbligatorietà in vigore e processi qualificati (MOD.128): la colonna «Richiesto da» ne indica l'origine.",
    ]
    if solo_sicurezza:
        res.note.append("Formazione sicurezza: corsi con obbligo di legge / Accordo Stato-Regioni "
                        "o legati ai fattori di rischio (D.Lgs. 81/2008 artt. 36-37).")
    return res


_COLONNE_FORMAZIONE = (
    ("nominativo", "Nominativo"), ("matricola", "Matricola"), ("reparto", "Reparto"), ("mansione", "Mansione"),
    ("corso", "Corso"), ("codice", "Codice"), ("fonte", "Fonte obbligo"), ("riferimento", "Riferimento"),
    ("ore", "Ore"), ("obbligatorio", "Obbligatorio"), ("origine", "Richiesto da"),
    ("completato", "Ultimo completamento"), ("scadenza", "Scadenza"), ("giorni", "Giorni alla scadenza"),
    ("stato", "Stato"),
)
_OPZ_FORMAZIONE = (
    Opzione("stati", "Stati da includere", MULTI, _SCELTE_STATI_FORMAZIONE, aiuto="Vuoto = tutti."),
    Opzione("fonti", "Fonte dell'obbligo", MULTI, _scelte_fonti, aiuto="Vuoto = tutte."),
    Opzione("solo_obbligatori", "Solo requisiti obbligatori", SI_NO, predefinito=True,
            aiuto="Senza spunta compaiono anche i corsi frequentati ma non richiesti."),
)

_registra(Sezione(
    key="personale_formazione",
    titolo="Formazione obbligatoria",
    gruppo=GRUPPO_PERSONE,
    descrizione="Requisiti formativi per persona (mansione, ruolo, regole) con ultimo completamento e scadenza.",
    builder=lambda ctx, o: _formazione_obbligatoria(ctx, o, solo_sicurezza=False),
    riferimenti=(f"{ISO_9001} §7.2", f"{EN_9100} §7.2", f"{ISO_27001} §7.2"),
    colonne=_COLONNE_FORMAZIONE,
    predefinite=("nominativo", "mansione", "corso", "completato", "scadenza", "stato"),
    opzioni=_OPZ_FORMAZIONE,
))


def _persone_del_periodo(ctx: Contesto) -> dict:
    """Persone di una sezione di periodo: in forza a fine periodo, o tutte se si includono i cessati.

    Le stesse persone sono numeratore e denominatore degli indicatori: chi e' uscito
    nel periodo, senza «Includi il personale cessato», non e' contato da nessuna parte
    (i suoi completamenti sono segnalati come esclusi).
    """
    persone = ctx.dipendenti_perimetro()
    if not ctx.perimetro.includi_cessati:
        persone = [p for p in persone if p.in_forza_al(ctx.date_to)]
    return {p.id: p for p in persone}


_CONFRONTI_ORE = (("", "— nessun filtro —"), ("meno_di", "Meno di"), ("al_massimo", "Al massimo"),
                  ("almeno", "Almeno"), ("piu_di", "Più di"))


def _filtro_ore(o: dict):
    """Filtro sulle ore della riga (None = nessun filtro). «Meno di 5» comprende chi ha 0 ore."""
    confronto, soglia = o.get("confronto_ore") or "", Decimal(o.get("soglia_ore") or 0)
    return {
        "meno_di": lambda ore: ore < soglia,
        "al_massimo": lambda ore: ore <= soglia,
        "almeno": lambda ore: ore >= soglia,
        "piu_di": lambda ore: ore > soglia,
    }.get(confronto)


def _formazione_erogata(ctx: Contesto, o: dict) -> Risultato:
    res = Risultato()
    persone = _persone_del_periodo(ctx)
    record = _completamenti(ctx, o, persone)
    filtro = _filtro_ore(o)
    per_persona = o["dettaglio"] == "persona"
    per_chiave: dict[str, dict] = {}

    def _base_persona(p) -> dict:
        return {"voce": p.nominativo, "codice": p.matricola, "nominativo": p.nominativo, "matricola": p.matricola,
                "reparto": p.reparto, "mansione": p.mansione}

    for r in record:
        p = persone[ctx.canonico(r.legacy_anagrafica_id)]
        if o["dettaglio"] == "corso":
            chiave, base = r.course_code_snapshot or r.course_title_snapshot, {
                "voce": r.course_title_snapshot or r.course_code_snapshot, "codice": r.course_code_snapshot}
        elif o["dettaglio"] == "reparto":
            chiave, base = p.reparto or "—", {"voce": p.reparto or "Senza reparto", "codice": "",
                                              "reparto": p.reparto or "Senza reparto"}
        else:
            chiave, base = str(p.id), _base_persona(p)
        acc = per_chiave.setdefault(chiave, {**base, "completamenti": 0, "ore": Decimal(0), "persone": set(), "corsi": []})
        acc["completamenti"] += 1
        acc["ore"] += _ore_record(r)
        acc["persone"].add(p.id)
        titolo = r.course_title_snapshot or r.course_code_snapshot
        if titolo and titolo not in acc["corsi"]:
            acc["corsi"].append(titolo)
    # Chi non ha formazione nel periodo ha 0 ore: compare se chiesto, o se il filtro sulle
    # ore lo comprende («meno di 5 ore» deve elencare anche chi non ne ha fatta nessuna).
    senza_formazione = 0
    if per_persona and (o["includi_non_formati"] or (filtro and filtro(Decimal(0)))):
        for p in persone.values():
            if str(p.id) not in per_chiave:
                senza_formazione += 1
                per_chiave[str(p.id)] = {**_base_persona(p), "completamenti": 0, "ore": Decimal(0),
                                         "persone": {p.id}, "corsi": []}
    righe = list(per_chiave.values())
    if filtro:
        righe = [acc for acc in righe if filtro(acc["ore"])]
    for acc in sorted(righe, key=lambda a: str(a["voce"]).casefold()):
        res.riga({
            "voce": acc["voce"], "codice": acc.get("codice", ""), "nominativo": acc.get("nominativo", ""),
            "matricola": acc.get("matricola", ""), "reparto": acc.get("reparto", ""),
            "mansione": acc.get("mansione", ""), "completamenti": acc["completamenti"], "ore": acc["ore"],
            "persone": len(acc["persone"]), "corsi": "; ".join(acc["corsi"][:10]),
        }, TONE_WARN if per_persona and not acc["completamenti"] else "")
    ore_tot = sum((_ore_record(r) for r in record), Decimal(0))
    formati = {ctx.canonico(r.legacy_anagrafica_id) for r in record}
    chi = "nel perimetro (cessati compresi)" if ctx.perimetro.includi_cessati else "in forza a fine periodo"
    res.kpis = [
        Kpi("Ore di formazione erogate", _fmt_ore(ore_tot)),
        Kpi("Persone formate", len(formati), hint=f"su {len(persone)} {chi}"),
        Kpi("Ore medie pro capite", _fmt_ore(ore_tot / len(persone)) if persone else "n/d",
            hint=f"ore erogate / persone {chi}"),
        Kpi("Completamenti", len(record)),
    ]
    if filtro:
        etichetta = dict(_CONFRONTI_ORE)[o["confronto_ore"]].lower()
        cosa = {"persona": "Persone", "corso": "Corsi", "reparto": "Reparti"}[o["dettaglio"]]
        res.kpis.append(Kpi(f"{cosa} con {etichetta} {o['soglia_ore']} ore", len(res.righe),
                            TONE_WARN if res.righe and o["confronto_ore"] in ("meno_di", "al_massimo") else ""))
    res.note = [f"Completamenti registrati nel periodo {ctx.periodo_label}, dettaglio per "
                f"{dict(_DETTAGLI_EROGATA)[o['dettaglio']].lower()}. Ore = ore frequentate, "
                "o durata del corso se non registrate."]
    if filtro:
        res.note.append(f"Solo le righe con {dict(_CONFRONTI_ORE)[o['confronto_ore']].lower()} "
                        f"{o['soglia_ore']} ore nel periodo.")
    if senza_formazione:
        res.note.append(f"Comprese {senza_formazione} persone senza formazione registrata nel periodo (0 ore).")
    return res


def _completamenti(ctx: Contesto, o: dict, persone: dict) -> list:
    """Completamenti nel periodo delle persone; quelli trovati ma esclusi diventano avvisi."""
    from anagrafica.models import TrainingEmployeeRecord

    base = TrainingEmployeeRecord.objects.filter(
        data_completamento__range=(ctx.date_from, ctx.date_to),
    ).select_related("corso")
    if o.get("fonti"):
        base = base.filter(corso__fonte_obbligo__in=o["fonti"])
    tutti = list(base.order_by("data_completamento", "id"))
    if o.get("solo_sicurezza"):
        tutti = [r for r in tutti if _corso_sicurezza(r.corso)]
    record = [r for r in tutti if ctx.canonico(r.legacy_anagrafica_id) in persone]
    ctx.segnala_esclusi([r.legacy_anagrafica_id for r in tutti], incluse=persone, cosa="completamenti del periodo")
    return record


_DETTAGLI_EROGATA = (("persona", "Persona"), ("corso", "Corso"), ("reparto", "Reparto"))

_registra(Sezione(
    key="formazione_erogata",
    titolo="Formazione erogata nel periodo",
    gruppo=GRUPPO_PERSONE,
    descrizione="Ore e completamenti nel periodo, per persona, per corso o per reparto.",
    builder=_formazione_erogata,
    riferimenti=(f"{ISO_9001} §7.2", f"{ISO_45001} §7.2", f"{PDR_125} – Opportunità di crescita"),
    colonne=(
        ("voce", "Persona / corso / reparto"), ("codice", "Matricola / codice"),
        ("nominativo", "Nominativo"), ("matricola", "Matricola"), ("reparto", "Reparto"),
        ("mansione", "Mansione"), ("completamenti", "Completamenti"), ("ore", "Ore"),
        ("persone", "Persone"), ("corsi", "Corsi"),
    ),
    predefinite=("voce", "completamenti", "ore", "corsi"),
    opzioni=(
        Opzione("dettaglio", "Dettaglio per", SCELTA, _DETTAGLI_EROGATA, "persona"),
        Opzione("fonti", "Fonte dell'obbligo", MULTI, _scelte_fonti, aiuto="Vuoto = tutte."),
        Opzione("solo_sicurezza", "Solo formazione sicurezza", SI_NO, predefinito=False),
        Opzione("confronto_ore", "Filtro sulle ore", SCELTA, _CONFRONTI_ORE, "",
                aiuto="Con «Meno di»/«Al massimo» e dettaglio per persona compare anche chi ha 0 ore."),
        Opzione("soglia_ore", "Soglia ore", INTERO, predefinito=0, massimo=10000),
        Opzione("includi_non_formati", "Elenca anche chi non ha formazione nel periodo", SI_NO, predefinito=False,
                aiuto="Solo con dettaglio per persona: righe a 0 ore."),
    ),
    usa_periodo=True,
))


def _attestati(ctx: Contesto, o: dict) -> Risultato:
    res = Risultato()
    persone = _persone_del_periodo(ctx)
    record = _completamenti(ctx, o, persone)
    for r in sorted(record, key=lambda x: (persone[ctx.canonico(x.legacy_anagrafica_id)].nominativo.casefold(),
                                           x.data_completamento)):
        p = persone[ctx.canonico(r.legacy_anagrafica_id)]
        res.riga({
            "nominativo": p.nominativo, "matricola": p.matricola, "reparto": p.reparto,
            "corso": r.course_title_snapshot, "codice": r.course_code_snapshot,
            "data": r.data_completamento, "ore": _ore_record(r),
            "protocollo": r.numero_protocollo, "docente": r.teacher_name_snapshot,
            "esito": "Idoneo" if r.idoneo else "Non idoneo", "scadenza": r.data_scadenza,
        }, "" if r.idoneo else TONE_WARN)
    res.kpis = [Kpi("Attestati nel periodo", len(record)),
                Kpi("Persone", len({ctx.canonico(r.legacy_anagrafica_id) for r in record}))]
    res.note = [f"Completamenti registrati nel periodo {ctx.periodo_label}: evidenza delle attività formative svolte."]
    return res


_registra(Sezione(
    key="attestati_formazione",
    titolo="Attestati di formazione",
    gruppo=GRUPPO_PERSONE,
    descrizione="Elenco dei corsi completati nel periodo con protocollo, ore, docente ed esito.",
    builder=_attestati,
    riferimenti=(f"{ISO_9001} §7.2 d)", f"{ISO_45001} §7.2"),
    colonne=(
        ("nominativo", "Nominativo"), ("matricola", "Matricola"), ("reparto", "Reparto"), ("corso", "Corso"),
        ("codice", "Codice"), ("data", "Completato il"), ("ore", "Ore"), ("protocollo", "N. protocollo"),
        ("docente", "Docente"), ("esito", "Esito"), ("scadenza", "Scadenza"),
    ),
    predefinite=("nominativo", "corso", "data", "ore", "protocollo", "scadenza"),
    opzioni=(
        Opzione("fonti", "Fonte dell'obbligo", MULTI, _scelte_fonti, aiuto="Vuoto = tutte."),
        Opzione("solo_sicurezza", "Solo formazione sicurezza", SI_NO, predefinito=False),
    ),
    usa_periodo=True,
))


def _abilitazioni_processi(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.models import AbilitazioneProcesso, CertificazioneIndividuale

    res = Risultato()
    persone = {p.id: p for p in ctx.dipendenti()}
    base = AbilitazioneProcesso.objects.exclude(legacy_anagrafica_id=0)
    if o["solo_attive"]:
        base = base.filter(stato=AbilitazioneProcesso.STATO_ATTIVA)
    if o["processi"]:
        base = base.filter(processo_id__in=[int(x) for x in o["processi"]])
    abilitazioni = [a for a in base.filter(legacy_anagrafica_id__in=ctx.id_estesi(persone))
                    .select_related("processo", "processo__cliente")
                    if ctx.canonico(a.legacy_anagrafica_id) in persone]
    cert: dict[int, date] = {}
    for c in CertificazioneIndividuale.objects.filter(
        abilitazione__in=abilitazioni, stato="ATTIVA", data_scadenza__isnull=False,
    ).order_by("data_scadenza"):
        cert.setdefault(c.abilitazione_id, c.data_scadenza)
    scadute = 0
    for a in sorted(abilitazioni, key=lambda x: (persone[ctx.canonico(x.legacy_anagrafica_id)].nominativo.casefold(),
                                                 x.processo.nome.casefold())):
        p = persone[ctx.canonico(a.legacy_anagrafica_id)]
        ruoli = [lbl for flag, lbl in ((a.is_qualificato, "Qualificato"), (a.is_addetto, "Addetto"),
                                       (a.is_controllore, "Controllore"), (a.is_part145, "Part 145")) if flag]
        scad = cert.get(a.id)
        _c, stato, tono = _stato_scadenza(scad, ctx.today, o["preavviso"]) if scad else ("", a.get_stato_display(), "")
        if tono == TONE_DANGER:
            scadute += 1
        res.riga({
            "nominativo": p.nominativo, "matricola": p.matricola, "reparto": p.reparto,
            "processo": a.processo.nome, "regime": a.processo.get_regime_display(),
            "cliente": str(a.processo.cliente or ""), "ruoli": ", ".join(ruoli),
            "dal": a.data_ingresso, "certificazione": scad, "stato": stato,
        }, tono)
    res.kpis = [Kpi("Abilitazioni", len(abilitazioni)),
                Kpi("Persone abilitate", len({ctx.canonico(a.legacy_anagrafica_id) for a in abilitazioni})),
                Kpi("Certificazioni scadute", scadute, TONE_DANGER if scadute else TONE_OK)]
    res.note = ["Processi speciali qualificati (MOD.128): EN 9100 §8.5.1.2 richiede la qualifica del personale."]
    ctx.segnala_esclusi(base.values_list("legacy_anagrafica_id", flat=True), incluse=persone,
                                 cosa="abilitazioni")
    return res


_registra(Sezione(
    key="abilitazioni_processi",
    titolo="Abilitazioni ai processi speciali",
    gruppo=GRUPPO_PERSONE,
    descrizione="Per persona: processi qualificati (NADCAP, Part 145, specifiche cliente), ruolo e certificazione.",
    builder=_abilitazioni_processi,
    riferimenti=(f"{EN_9100} §8.5.1.2", f"{ISO_9001} §8.5.1 f)"),
    colonne=(
        ("nominativo", "Nominativo"), ("matricola", "Matricola"), ("reparto", "Reparto"), ("processo", "Processo"),
        ("regime", "Regime"), ("cliente", "Cliente"), ("ruoli", "Ruolo"), ("dal", "Abilitato dal"),
        ("certificazione", "Scadenza certificazione"), ("stato", "Stato"),
    ),
    predefinite=("nominativo", "processo", "cliente", "ruoli", "certificazione", "stato"),
    opzioni=(
        Opzione("processi", "Processi", MULTI, _scelte_processi, aiuto="Vuoto = tutti."),
        Opzione("solo_attive", "Solo abilitazioni attive", SI_NO, predefinito=True),
        Opzione("preavviso", "Giorni di preavviso «in scadenza»", INTERO, predefinito=60),
    ),
))


_INCLUSIONI_SCHEDA = (("qualifiche", "Qualifiche"), ("formazione", "Formazione obbligatoria"),
                      ("processi", "Abilitazioni ai processi"), ("visite", "Visite mediche (solo validità)"))


def _scheda_individuale(ctx: Contesto, o: dict) -> Risultato:
    res = Risultato()
    persone = {p.id: p for p in ctx.dipendenti()}
    righe: list[tuple] = []
    incl = set(o["includi"])
    if "qualifiche" in incl:
        r = _qualifiche_personale(ctx, {"categorie": [], "tipi": [], "preavviso": o["preavviso"], "stati": [],
                                        "solo_verificate": False, "storico": False})
        righe += [(x["nominativo"], "Qualifica", x["qualifica"], x["numero"], x["scadenza"], x["stato"], t)
                  for x, t in zip(r.righe, r.toni)]
    if "formazione" in incl:
        r = _formazione_obbligatoria(ctx, {"stati": [], "fonti": [], "solo_obbligatori": True}, solo_sicurezza=False)
        righe += [(x["nominativo"], "Formazione", x["corso"], x["codice"], x["scadenza"], x["stato"], t)
                  for x, t in zip(r.righe, r.toni)]
    if "processi" in incl:
        r = _abilitazioni_processi(ctx, {"processi": [], "solo_attive": True, "preavviso": o["preavviso"]})
        righe += [(x["nominativo"], "Processo speciale", x["processo"], x["ruoli"], x["certificazione"], x["stato"], t)
                  for x, t in zip(r.righe, r.toni)]
    visite_ok = "visite" in incl and has_perm(ctx.request, PERM_VISITE)
    if visite_ok:
        r = _sorveglianza(ctx, {"preavviso": o["preavviso"], "stati": [], "tipi": [], "includi_senza_visita": False})
        righe += [(x["nominativo"], "Visita medica", x["visita"], "", x["scadenza"], x["stato"], t)
                  for x, t in zip(r.righe, r.toni)]
    ordine = {"Qualifica": 0, "Processo speciale": 1, "Formazione": 2, "Visita medica": 3}
    for nom, tipo, voce, rif, scad, stato, tono in sorted(righe, key=lambda x: (x[0].casefold(), ordine[x[1]], str(x[2]).casefold())):
        res.riga({"nominativo": nom, "tipo": tipo, "voce": voce, "riferimento": rif, "scadenza": scad,
                  "stato": stato}, tono)
    res.kpis = [Kpi("Persone", len(persone)), Kpi("Voci", len(righe)),
                Kpi("Voci critiche", sum(1 for x in righe if x[6] in (TONE_DANGER, TONE_WARN)),
                    TONE_WARN if any(x[6] in (TONE_DANGER, TONE_WARN) for x in righe) else TONE_OK)]
    res.note = ["Scheda di competenza per persona: una sottotabella per nominativo."]
    if "visite" in incl and not visite_ok:
        res.note.append("Visite mediche omesse: servono i permessi sui dati sanitari.")
    return res


_registra(Sezione(
    key="scheda_individuale",
    titolo="Scheda individuale delle competenze",
    gruppo=GRUPPO_PERSONE,
    descrizione="Per ogni persona: qualifiche, abilitazioni, formazione e (con permesso) visite, in un'unica scheda.",
    builder=_scheda_individuale,
    riferimenti=(f"{ISO_9001} §7.2", f"{EN_9100} §7.2"),
    colonne=(("nominativo", "Nominativo"), ("tipo", "Tipo"), ("voce", "Voce"), ("riferimento", "Rif. / numero"),
             ("scadenza", "Scadenza"), ("stato", "Stato")),
    predefinite=("tipo", "voce", "riferimento", "scadenza", "stato"),
    opzioni=(
        Opzione("includi", "Contenuti", MULTI, _INCLUSIONI_SCHEDA, ("qualifiche", "processi", "formazione")),
        Opzione("preavviso", "Giorni di preavviso «in scadenza»", INTERO, predefinito=60),
    ),
))


# ═══════════════════════════════════════════════════════════════════════════
# Matrici e scadenzari
# ═══════════════════════════════════════════════════════════════════════════

_CELLE = (("simbolo", "Simbolo (OK / ! / X)"), ("scadenza", "Data di scadenza"), ("stato", "Stato esteso"))


def _cella(codice: str, stato: str, scadenza: date | None, modo: str) -> object:
    if modo == "scadenza":
        return scadenza or ("OK" if codice in ("valida", "senza") else stato)
    if modo == "stato":
        return stato
    return {"valida": "OK", "senza": "OK", "in_scadenza": "!", "scaduta": "X", "mancante": "—"}.get(codice, stato)


def _matrice_qualifiche(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.models import DipendenteQualifica, TipoQualifica

    res = Risultato()
    persone = ctx.dipendenti()
    tipi_qs = TipoQualifica.objects.all()
    if o["categorie"]:
        tipi_qs = tipi_qs.filter(categoria__in=o["categorie"])
    if o["tipi"]:
        tipi_qs = tipi_qs.filter(pk__in=[int(t) for t in o["tipi"]])
    tipi = {t.pk: t for t in tipi_qs.order_by("categoria", "nome")}
    ultime, _sostituite = _qualifiche_correnti(
        ctx, DipendenteQualifica.objects.filter(tipo_id__in=list(tipi)), {p.id: p for p in persone})
    if o["solo_tipi_posseduti"]:
        posseduti = {t for (_p, t) in ultime}
        tipi = {k: v for k, v in tipi.items() if k in posseduti}
    res.colonne = [("nominativo", "Nominativo"), ("mansione", "Mansione")] + [(f"q{k}", t.nome) for k, t in tipi.items()]
    critiche = 0
    for p in persone:
        riga: dict = {"nominativo": p.nominativo, "mansione": p.mansione, "_toni": {}}
        tono_riga = ""
        for k in tipi:
            q = ultime.get((p.id, k))
            if q is None:
                riga[f"q{k}"] = "" if o["vuoto_se_mancante"] else "—"
                continue
            codice, stato, tono = _stato_scadenza(q.data_scadenza, ctx.today, o["preavviso"])
            riga[f"q{k}"] = _cella(codice, stato, q.data_scadenza, o["cella"])
            riga["_toni"][f"q{k}"] = tono
            if tono in (TONE_DANGER, TONE_WARN):
                tono_riga = TONE_DANGER if TONE_DANGER in (tono, tono_riga) else TONE_WARN
                critiche += 1
        res.righe.append(riga)
        res.toni.append(tono_riga)
    res.kpis = [Kpi("Persone", len(persone)), Kpi("Qualifiche in matrice", len(tipi)),
                Kpi("Celle critiche", critiche, TONE_WARN if critiche else TONE_OK)]
    res.note = ["Legenda: OK valida · ! in scadenza · X scaduta · — non posseduta.",
                f"Preavviso «in scadenza»: {o['preavviso']} giorni. Per persona e tipo vale l'ultima registrazione."]
    return res


_registra(Sezione(
    key="matrice_qualifiche",
    titolo="Matrice qualifiche × persone",
    gruppo=GRUPPO_MATRICI,
    descrizione="Griglia persone/qualifiche con stato di validità per cella: la vista che i clienti chiedono più spesso.",
    builder=_matrice_qualifiche,
    riferimenti=(f"{ISO_9001} §7.2", f"{EN_9100} §7.2"),
    opzioni=_opz_qualifiche() + (
        Opzione("cella", "Contenuto della cella", SCELTA, _CELLE, "simbolo"),
        Opzione("solo_tipi_posseduti", "Solo qualifiche possedute da almeno una persona", SI_NO, predefinito=True),
        Opzione("vuoto_se_mancante", "Cella vuota se non posseduta (invece di —)", SI_NO, predefinito=False),
    ),
    colonne_dinamiche=True,
))


_SIGLE_FORMAZIONE = {"VALIDO": ("valida", "OK"), "UNA_TANTUM": ("valida", "OK"), "IN_SCADENZA_90": ("valida", "OK"),
                     "IN_SCADENZA_30": ("in_scadenza", "!"), "SCADUTO": ("scaduta", "X"),
                     "MAI_FREQUENTATO": ("scaduta", "MAI")}


def _matrice_formazione(ctx: Contesto, o: dict) -> Risultato:
    res = Risultato()
    persone = ctx.dipendenti()
    per_id = {p.id: p for p in persone}
    voci = _voci_formazione(ctx, o, per_id, solo_sicurezza=o["solo_sicurezza"])
    corsi = {}
    for v in sorted(voci, key=lambda x: (getattr(x.corso, "codice", "") or "", x.corso.pk)):
        corsi.setdefault(v.corso.pk, v.corso)
    mappa = {(v.persona, v.corso.pk): v for v in voci}
    etichetta = (lambda c: c.codice) if o["intestazione"] == "codice" else (lambda c: c.titolo)
    res.colonne = [("nominativo", "Nominativo"), ("mansione", "Mansione")] + [(f"c{k}", etichetta(c)) for k, c in corsi.items()]
    critiche = 0
    for p in persone:
        riga: dict = {"nominativo": p.nominativo, "mansione": p.mansione, "_toni": {}}
        tono_riga = ""
        for k in corsi:
            v = mappa.get((p.id, k))
            if v is None:
                riga[f"c{k}"] = ""
                continue
            codice, sigla = _SIGLE_FORMAZIONE.get(v.stato, ("", "?"))
            stato, tono = _STATI_FORMAZIONE.get(v.stato, (v.stato, ""))
            if not v.obbligatorio:
                tono = ""  # corso frequentato ma non richiesto: informativo, mai critico
            riga[f"c{k}"] = (v.scadenza or sigla) if o["cella"] == "scadenza" else (stato if o["cella"] == "stato" else sigla)
            riga["_toni"][f"c{k}"] = tono
            if tono in (TONE_DANGER, TONE_WARN):
                tono_riga = TONE_DANGER if TONE_DANGER in (tono, tono_riga) else TONE_WARN
                critiche += 1
        res.righe.append(riga)
        res.toni.append(tono_riga)
    res.kpis = [Kpi("Persone", len(persone)), Kpi("Corsi in matrice", len(corsi)),
                Kpi("Celle critiche", critiche, TONE_WARN if critiche else TONE_OK)]
    res.note = ["Legenda: OK valida · ! in scadenza entro 30 gg · X scaduta · MAI mai frequentata · vuoto = non richiesta.",
                f"Stato calcolato al {ctx.today:%d/%m/%Y} dall'ultimo completamento idoneo di ogni corso."]
    if o["intestazione"] == "codice" and corsi:
        res.note.append("Corsi: " + "; ".join(f"{c.codice} = {c.titolo}" for c in list(corsi.values())[:40]))
    return res


_registra(Sezione(
    key="matrice_formazione",
    titolo="Matrice formazione × persone",
    gruppo=GRUPPO_MATRICI,
    descrizione="Griglia persone/corsi richiesti con stato per cella (valida, in scadenza, scaduta, mai frequentata).",
    builder=_matrice_formazione,
    riferimenti=(f"{ISO_9001} §7.2", f"{ISO_45001} §7.2"),
    opzioni=_OPZ_FORMAZIONE + (
        Opzione("solo_sicurezza", "Solo formazione sicurezza", SI_NO, predefinito=False),
        Opzione("cella", "Contenuto della cella", SCELTA, _CELLE, "simbolo"),
        Opzione("intestazione", "Intestazione delle colonne", SCELTA, (("codice", "Codice corso"), ("titolo", "Titolo corso")), "codice"),
    ),
    colonne_dinamiche=True,
))


_TIPI_SCADENZARIO = (("qualifiche", "Qualifiche"), ("formazione", "Formazione"), ("processi", "Certificazioni processi"),
                     ("visite", "Visite mediche"))


def _scadenzario(ctx: Contesto, o: dict) -> Risultato:
    res = Risultato()
    limite = ctx.today + timedelta(days=o["giorni"])
    voci: list[tuple] = []
    tipi = set(o["tipi"])
    if "qualifiche" in tipi:
        r = _qualifiche_personale(ctx, {"categorie": [], "tipi": [], "preavviso": o["giorni"], "stati": [],
                                        "solo_verificate": False, "storico": False})
        voci += [(x["scadenza"], "Qualifica", x["nominativo"], x["reparto"], x["qualifica"]) for x in r.righe if x["scadenza"]]
    if "formazione" in tipi:
        r = _formazione_obbligatoria(ctx, {"stati": [], "fonti": [], "solo_obbligatori": True}, solo_sicurezza=False)
        voci += [(x["scadenza"], "Formazione", x["nominativo"], x["reparto"], x["corso"]) for x in r.righe if x["scadenza"]]
    if "processi" in tipi:
        r = _abilitazioni_processi(ctx, {"processi": [], "solo_attive": True, "preavviso": o["giorni"]})
        voci += [(x["certificazione"], "Certificazione processo", x["nominativo"], x["reparto"], x["processo"])
                 for x in r.righe if x["certificazione"]]
    visite_ok = "visite" in tipi and has_perm(ctx.request, PERM_VISITE)
    if visite_ok:
        r = _sorveglianza(ctx, {"preavviso": o["giorni"], "stati": [], "tipi": [], "includi_senza_visita": False})
        # Solo le visite dovute: una visita non richiesta non e' una scadenza da presidiare.
        r.righe = [x for x in r.righe if x["richiesta"] == "Sì"]
        voci += [(x["scadenza"], "Visita medica", x["nominativo"], x["reparto"], x["visita"]) for x in r.righe if x["scadenza"]]
    scadute = 0
    for scad, tipo, nom, rep, voce in sorted(voci, key=lambda v: (v[0], v[2].casefold())):
        if scad > limite or (scad < ctx.today and not o["includi_scadute"]):
            continue
        giorni = (scad - ctx.today).days
        tono = TONE_DANGER if giorni < 0 else TONE_WARN if giorni <= 30 else ""
        scadute += giorni < 0
        res.riga({"scadenza": scad, "giorni": giorni, "tipo": tipo, "nominativo": nom, "reparto": rep, "voce": voce,
                  "mese": _mese(scad)}, tono)
    res.kpis = [Kpi("Scadenze", len(res.righe)), Kpi("Già scadute", scadute, TONE_DANGER if scadute else TONE_OK),
                Kpi("Entro 30 giorni", sum(1 for r in res.righe if 0 <= r["giorni"] <= 30))]
    res.note = [f"Scadenze fino al {limite:%d/%m/%Y} ({o['giorni']} giorni)."]
    if "visite" in tipi and not visite_ok:
        res.note.append("Visite mediche omesse: servono i permessi sui dati sanitari.")
    return res


_registra(Sezione(
    key="scadenzario_unico",
    titolo="Scadenzario unico del personale",
    gruppo=GRUPPO_MATRICI,
    descrizione="Tutte le scadenze in arrivo (qualifiche, formazione, certificazioni, visite) in ordine di data.",
    builder=_scadenzario,
    riferimenti=(f"{ISO_9001} §7.2", f"{ISO_45001} §9.1"),
    colonne=(("scadenza", "Scadenza"), ("giorni", "Giorni"), ("tipo", "Tipo"), ("nominativo", "Nominativo"),
             ("reparto", "Reparto"), ("voce", "Voce"), ("mese", "Mese")),
    predefinite=("scadenza", "giorni", "tipo", "nominativo", "voce"),
    opzioni=(
        Opzione("giorni", "Orizzonte (giorni)", INTERO, predefinito=90, minimo=1),
        Opzione("tipi", "Tipi di scadenza", MULTI, _TIPI_SCADENZARIO, ("qualifiche", "formazione", "processi")),
        Opzione("includi_scadute", "Includi le scadenze già passate", SI_NO, predefinito=True),
    ),
))


# ═══════════════════════════════════════════════════════════════════════════
# Organico e indicatori
# ═══════════════════════════════════════════════════════════════════════════

_FASCE_ETA = ((0, 29, "Fino a 29 anni"), (30, 39, "30-39 anni"), (40, 49, "40-49 anni"),
              (50, 59, "50-59 anni"), (60, 200, "60 anni e oltre"))
_FASCE_ANZIANITA = ((0, 1, "Meno di 2 anni"), (2, 4, "2-4 anni"), (5, 9, "5-9 anni"), (10, 19, "10-19 anni"),
                    (20, 200, "20 anni e oltre"))


def _fascia(valore: int | None, fasce) -> str:
    if valore is None:
        return "Non registrata"
    for lo, hi, label in fasce:
        if lo <= valore <= hi:
            return label
    return "Non registrata"


_DIMENSIONI = (
    ("reparto", "Reparto"), ("area", "Area aziendale"), ("mansione", "Mansione"), ("contratto", "Contratto"),
    ("livello", "Livello"), ("eta", "Fascia d'età"), ("anzianita", "Fascia di anzianità"),
    ("titolo_studio", "Titolo di studio"), ("genere", "Genere"),
)
_GENERE = {"F": "Donne", "M": "Uomini"}


def _valore_dimensione(p, dim: str, oggi: date) -> str:
    if dim == "eta":
        return _fascia(anni_compiuti(p.data_nascita, oggi), _FASCE_ETA)
    if dim == "anzianita":
        return _fascia(anni_compiuti(p.data_assunzione, oggi), _FASCE_ANZIANITA)
    if dim == "contratto":
        return p.contratto_label
    if dim == "genere":
        return _GENERE.get(p.genere, "Non registrato")
    return getattr(p, dim, "")


def _movimenti(ctx: Contesto) -> tuple[list, list]:
    tutti = ctx.dipendenti_perimetro()
    assunti = [p for p in tutti if p.data_assunzione and ctx.date_from <= p.data_assunzione <= ctx.date_to]
    cessati = [p for p in tutti if p.data_cessazione and ctx.date_from <= p.data_cessazione <= ctx.date_to]
    return assunti, cessati


def _organico(ctx: Contesto, o: dict) -> Risultato:
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
        Kpi("Organico a inizio / fine periodo", f"{inizio} / {fine}"),
        Kpi("Assunzioni nel periodo", len(assunti)),
        Kpi("Cessazioni nel periodo", len(cessati)),
        Kpi("Turnover in uscita", _pct(len(cessati), medio) if medio else "n/d",
            hint=f"cessazioni / organico medio ({medio:g})"),
        Kpi("Turnover complessivo", _pct(len(assunti) + len(cessati), medio) if medio else "n/d",
            hint="(assunzioni + cessazioni) / organico medio"),
        Kpi("Età media", f"{sum(eta) / len(eta):.1f}".replace(".", ",") if eta else "n/d",
            hint=f"{len(eta)} date di nascita registrate"),
        Kpi("Anzianità media (anni)", f"{sum(anzianita) / len(anzianita):.1f}".replace(".", ",") if anzianita else "n/d"),
    ]
    for dim in o["dimensioni"]:
        conteggi = Counter(_valore_dimensione(p, dim, ctx.today) or "Non registrato" for p in in_forza)
        for voce, n in sorted(conteggi.items(), key=lambda kv: (-kv[1], kv[0].casefold())):
            res.riga({"dimensione": dict(_DIMENSIONI)[dim], "voce": voce, "n": _soglia(n, o["soglia_anonimato"]),
                      "pct": _pct(n, totale)})
    res.note = [
        "Dati aggregati: nessun nominativo.",
        f"Movimenti e turnover nel periodo {ctx.periodo_label}; organico medio = media fra inizio e fine periodo.",
    ]
    if o["soglia_anonimato"] > 1:
        res.note.append(f"Conteggi sotto {o['soglia_anonimato']} mostrati come «<{o['soglia_anonimato']}» per anonimato.")
    return res


_OPZ_ANONIMATO = Opzione("soglia_anonimato", "Soglia di anonimato", INTERO, predefinito=0, massimo=20,
                         aiuto="Con 3, i conteggi da 1 a 2 appaiono come «<3». 0 = disattivata.")

_registra(Sezione(
    key="organico_indicatori",
    titolo="Organico e indicatori del personale",
    gruppo=GRUPPO_ORGANICO,
    descrizione="Persone in forza, turnover, età e anzianità medie, distribuzioni per le dimensioni scelte.",
    builder=_organico,
    riferimenti=(f"{ISO_9001} §7.1.2", f"{EN_9100} §7.1.2", f"{ISO_9001} §9.1.3"),
    colonne=(("dimensione", "Dimensione"), ("voce", "Voce"), ("n", "Persone"), ("pct", "%")),
    predefinite=("dimensione", "voce", "n", "pct"),
    opzioni=(
        Opzione("dimensioni", "Distribuzioni da mostrare", MULTI, _DIMENSIONI,
                ("reparto", "area", "contratto", "livello", "eta", "titolo_studio")),
        _OPZ_ANONIMATO,
    ),
    nominativa=False,
    usa_periodo=True,
))


def _movimenti_personale(ctx: Contesto, o: dict) -> Risultato:
    res = Risultato()
    assunti, cessati = _movimenti(ctx)
    righe = []
    if "assunzioni" in o["tipi"]:
        righe += [(p.data_assunzione, "Assunzione", p) for p in assunti]
    if "cessazioni" in o["tipi"]:
        righe += [(p.data_cessazione, "Cessazione", p) for p in cessati]
    for giorno, tipo, p in sorted(righe, key=lambda r: (r[0], r[2].nominativo.casefold())):
        res.riga({
            "data": giorno, "movimento": tipo, "nominativo": p.nominativo, "matricola": p.matricola,
            "reparto": p.reparto, "mansione": p.mansione, "contratto": p.contratto_label, "livello": p.livello,
            "mese": _mese(giorno),
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
    colonne=(("data", "Data"), ("movimento", "Movimento"), ("nominativo", "Nominativo"), ("matricola", "Matricola"),
             ("reparto", "Reparto"), ("mansione", "Mansione"), ("contratto", "Contratto"), ("livello", "Livello"),
             ("mese", "Mese")),
    predefinite=("data", "movimento", "nominativo", "reparto", "mansione"),
    opzioni=(Opzione("tipi", "Movimenti", MULTI, (("assunzioni", "Assunzioni"), ("cessazioni", "Cessazioni")),
                     ("assunzioni", "cessazioni")),),
    usa_periodo=True,
))


def _organigramma(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.models import AreaAziendale, Reparto

    res = Risultato()
    persone = ctx.dipendenti()
    nomi = {p.id: p.nominativo for p in ctx._tutti()}

    def _nome(legacy_id) -> str:
        return nomi.get(ctx.canonico(legacy_id), "") if legacy_id else ""

    per_area = Counter(p.area.casefold() for p in persone if p.area)
    per_reparto = Counter(p.reparto.casefold() for p in persone if p.reparto)
    reparti_catalogo = list(Reparto.objects.filter(is_active=True).order_by("nome"))
    for rep in reparti_catalogo:
        n_rep = per_reparto.get(rep.nome.casefold(), 0)
        if o["solo_con_persone"] and not n_rep:
            continue
        res.riga({"reparto": rep.nome, "area": "", "livello": "Reparto",
                  "responsabile": _nome(rep.caporeparto_legacy_id), "persone": n_rep})
        if not o["includi_aree"]:
            continue
        for area in AreaAziendale.objects.filter(is_active=True, reparto=rep).order_by("nome"):
            n_area = per_area.get(area.nome.casefold(), 0)
            if o["solo_con_persone"] and not n_area:
                continue
            res.riga({"reparto": rep.nome, "area": area.nome, "livello": "Area",
                      "responsabile": _nome(area.responsabile_legacy_id), "persone": n_area})
    # Chi ha un reparto che non e' nel catalogo, o nessun reparto, non deve sparire dai conteggi.
    noti = {r.nome.casefold() for r in reparti_catalogo}
    fuori = Counter(p.reparto or "" for p in persone if p.reparto.casefold() not in noti)
    for nome_rep, n in sorted(fuori.items(), key=lambda kv: kv[0].casefold()):
        res.riga({"reparto": nome_rep or "Senza reparto", "area": "", "livello": "Fuori catalogo",
                  "responsabile": "", "persone": n}, TONE_WARN)
    senza = sum(1 for r in res.righe if r["livello"] != "Fuori catalogo" and not r["responsabile"])
    res.kpis = [Kpi("Reparti", sum(1 for r in res.righe if r["livello"] == "Reparto")),
                Kpi("Aree", sum(1 for r in res.righe if r["livello"] == "Area")),
                Kpi("Senza responsabile", senza, TONE_WARN if senza else TONE_OK),
                Kpi("Persone fuori catalogo", sum(fuori.values()), TONE_WARN if fuori else TONE_OK)]
    res.note = ["Struttura dal catalogo reparti/aree; persone conteggiate nel perimetro del documento.",
                f"Totale persone: {len(persone)}."]
    if fuori:
        res.note.append("«Fuori catalogo»: persone con un reparto non presente nel catalogo reparti (o senza "
                        "reparto): vanno assegnate a un reparto dalla scheda.")
    return res


_registra(Sezione(
    key="organigramma",
    titolo="Organigramma e responsabili",
    gruppo=GRUPPO_ORGANICO,
    descrizione="Reparti e aree aziendali con responsabile e numero di persone.",
    builder=_organigramma,
    riferimenti=(f"{ISO_9001} §5.3", f"{ISO_45001} §5.3", f"{ISO_27001} §5.3"),
    colonne=(("reparto", "Reparto"), ("area", "Area aziendale"), ("livello", "Livello"),
             ("responsabile", "Responsabile"), ("persone", "Persone")),
    predefinite=("reparto", "area", "responsabile", "persone"),
    opzioni=(Opzione("includi_aree", "Mostra anche le aree aziendali", SI_NO, predefinito=True),
             Opzione("solo_con_persone", "Solo reparti/aree con persone nel perimetro", SI_NO, predefinito=True)),
))


# ═══════════════════════════════════════════════════════════════════════════
# Salute e sicurezza (ISO 45001)
# ═══════════════════════════════════════════════════════════════════════════

_registra(Sezione(
    key="sicurezza_formazione",
    titolo="Formazione sicurezza (D.Lgs. 81/2008)",
    gruppo=GRUPPO_SICUREZZA,
    descrizione="Solo corsi obbligatori per legge / Accordo Stato-Regioni o legati ai rischi della mansione.",
    builder=lambda ctx, o: _formazione_obbligatoria(ctx, o, solo_sicurezza=True),
    riferimenti=(f"{ISO_45001} §7.2", f"{ISO_45001} §7.3", "D.Lgs. 81/2008 artt. 36-37"),
    colonne=_COLONNE_FORMAZIONE,
    predefinite=("nominativo", "mansione", "corso", "completato", "scadenza", "stato"),
    opzioni=_OPZ_FORMAZIONE,
))


def _sorveglianza(ctx: Contesto, o: dict) -> Risultato:
    res = Risultato()
    persone = {p.id: p for p in ctx.dipendenti()}
    voci = calcoli.visite(ctx, persone)
    if o["tipi"]:
        scelti = {int(t) for t in o["tipi"]}
        voci = [v for v in voci if v.tipo.pk in scelti or v.tipo_da_mostrare.pk in scelti]
    soggette: set[int] = set()
    scadute: set[int] = set()
    in_scadenza: set[int] = set()
    incomplete: set[int] = set()
    mancanti = 0
    righe: list[tuple[dict, str]] = []
    for v in voci:
        if v.richiesta:
            soggette.add(v.persona)
        if v.ultima is None:
            codice, stato, tono = "mancante", "Dovuta, mai registrata", TONE_WARN
            mancanti += 1
            incomplete.add(v.persona)
        else:
            codice, stato, tono = _stato_scadenza(v.scadenza, ctx.today, o["preavviso"])
            if not v.richiesta:
                tono = ""  # visita non richiesta: informativa, non pesa sugli indicatori
            elif tono == TONE_DANGER:
                scadute.add(v.persona)
            elif tono == TONE_WARN:
                in_scadenza.add(v.persona)
        if codice == "mancante" and not o["includi_senza_visita"]:
            continue
        if o["stati"] and codice not in o["stati"]:
            continue
        p = persone[v.persona]
        righe.append(({
            "nominativo": p.nominativo, "matricola": p.matricola, "reparto": p.reparto, "mansione": p.mansione,
            "visita": v.tipo_da_mostrare.nome, "richiesta": "Sì" if v.richiesta else "No",
            "origine": "; ".join(v.origini), "ultima": v.ultima, "scadenza": v.scadenza,
            "giorni": (v.scadenza - ctx.today).days if v.scadenza else None, "stato": stato,
        }, tono))
    for riga, tono in sorted(righe, key=lambda rt: (rt[0]["nominativo"].casefold(), rt[0]["visita"].casefold())):
        res.riga(riga, tono)
    in_regola = soggette - scadute - incomplete
    res.kpis = [
        Kpi("Persone soggette a sorveglianza", len(soggette), hint=f"su {len(persone)} nel perimetro"),
        Kpi("In regola", _pct(len(in_regola), len(soggette)),
            (TONE_OK if len(in_regola) == len(soggette) else TONE_WARN) if soggette else "",
            f"{len(in_regola)} su {len(soggette)} persone soggette"),
        Kpi("Con visite scadute", len(scadute), TONE_DANGER if scadute else TONE_OK, "persone"),
        Kpi(f"In scadenza entro {o['preavviso']} gg", len(in_scadenza), TONE_WARN if in_scadenza else "", "persone"),
        Kpi("Visite dovute mai registrate", mancanti, TONE_WARN if mancanti else TONE_OK),
    ]
    res.note = [
        "Per ogni famiglia di visita vale l'ultima registrata (es. il passaggio da visita annuale a biennale "
        "supera la precedente); le visite segnate come superate non contano.",
        "Visite dovute: ruoli operativi in essere, protocollo sanitario dell'ultimo certificato, mansione e "
        "fattori di rischio, processi qualificati. La colonna «Richiesta da» ne indica l'origine.",
        "Riporta solo data e validità della visita: giudizio di idoneità, limitazioni e prescrizioni "
        "restano riservati al medico competente e al datore di lavoro (GDPR art. 9, D.Lgs. 81/2008 art. 41).",
    ]
    return res


_registra(Sezione(
    key="sicurezza_sorveglianza",
    titolo="Sorveglianza sanitaria – validità delle visite",
    gruppo=GRUPPO_SICUREZZA,
    descrizione="Visite dovute e ultima visita per persona e famiglia di visita, senza giudizio né prescrizioni.",
    builder=_sorveglianza,
    riferimenti=(f"{ISO_45001} §8.1", "D.Lgs. 81/2008 art. 41"),
    colonne=(("nominativo", "Nominativo"), ("matricola", "Matricola"), ("reparto", "Reparto"), ("mansione", "Mansione"),
             ("visita", "Tipo visita"), ("richiesta", "Dovuta"), ("origine", "Richiesta da"),
             ("ultima", "Ultima visita"), ("scadenza", "Scadenza"), ("giorni", "Giorni alla scadenza"), ("stato", "Stato")),
    predefinite=("nominativo", "mansione", "visita", "ultima", "scadenza", "stato"),
    opzioni=(
        Opzione("tipi", "Tipi di visita", MULTI, _scelte_tipi_visita, aiuto="Vuoto = tutti."),
        Opzione("stati", "Stati da includere", MULTI, _STATI_SCADENZA + (("mancante", "Dovuta, mai registrata"),),
                aiuto="Vuoto = tutti."),
        Opzione("preavviso", "Giorni di preavviso «in scadenza»", INTERO, predefinito=30),
        Opzione("includi_senza_visita", "Elenca le visite dovute e mai registrate", SI_NO, predefinito=True,
                aiuto="Solo per chi è soggetto a sorveglianza: chi non ha visite dovute non compare come mancante."),
    ),
    permesso=perm_check(PERM_VISITE),
))


# ═══════════════════════════════════════════════════════════════════════════
# Parità di genere (UNI/PdR 125:2022)
# ═══════════════════════════════════════════════════════════════════════════

def _responsabili_ids() -> set[int]:
    from anagrafica.models import AreaAziendale, Reparto

    ids = set(Reparto.objects.filter(is_active=True, caporeparto_legacy_id__isnull=False)
              .values_list("caporeparto_legacy_id", flat=True))
    ids |= set(AreaAziendale.objects.filter(is_active=True, responsabile_legacy_id__isnull=False)
               .values_list("responsabile_legacy_id", flat=True))
    return {int(x) for x in ids if x}


_DIMENSIONI_PDR = (("contratto", "Contratto"), ("livello", "Livello"), ("reparto", "Reparto"), ("area", "Area aziendale"),
                   ("mansione", "Mansione"), ("eta", "Fascia d'età"), ("anzianita", "Fascia di anzianità"))
_AREE_PDR = (("governance", "Governance (responsabili)"), ("processi_hr", "Processi HR (assunzioni, cessazioni)"),
             ("crescita", "Opportunità di crescita (formazione)"))


def _parita_genere(ctx: Contesto, o: dict) -> Risultato:
    from anagrafica.models import TrainingEmployeeRecord

    res = Risultato()
    k = o["soglia_anonimato"]
    tutti = ctx.dipendenti_perimetro()
    in_forza = [p for p in tutti if p.in_forza_al(ctx.today)]
    assunti, cessati = _movimenti(ctx)

    def _conta(persone) -> dict[str, int]:
        c = Counter(p.genere if p.genere in ("F", "M") else "ND" for p in persone)
        return {"F": c["F"], "M": c["M"], "ND": c["ND"]}

    def _riga(area: str, indicatore: str, persone) -> dict:
        c = _conta(persone)
        tot = c["F"] + c["M"] + c["ND"]
        res.riga({"area": area, "indicatore": indicatore, "donne": _soglia(c["F"], k), "uomini": _soglia(c["M"], k),
                  "nd": _soglia(c["ND"], k), "totale": _soglia(tot, k), "pct_donne": _pct(c["F"], tot)})
        return c

    org = _riga("Organico", "Persone in forza", in_forza)
    for dim in o["dimensioni"]:
        valori = sorted({_valore_dimensione(p, dim, ctx.today) for p in in_forza if _valore_dimensione(p, dim, ctx.today)},
                        key=str.casefold)
        for v in valori:
            _riga("Organico", f"{dict(_DIMENSIONI_PDR)[dim]}: {v}",
                  [p for p in in_forza if _valore_dimensione(p, dim, ctx.today) == v])
    resp = {"F": 0, "M": 0, "ND": 0}
    if "governance" in o["aree"]:
        responsabili = {ctx.canonico(i) for i in _responsabili_ids()}
        resp = _riga("Governance", "Responsabili di reparto / area", [p for p in in_forza if p.id in responsabili])
    ass = {"F": 0, "M": 0, "ND": 0}
    if "processi_hr" in o["aree"]:
        ass = _riga("Processi HR", "Assunzioni nel periodo", assunti)
        _riga("Processi HR", "Cessazioni nel periodo", cessati)
        _riga("Processi HR", "Contratti a tempo indeterminato", [p for p in in_forza if p.contratto == "INDETERMINATO"])
    media = {"F": None, "M": None}
    if "crescita" in o["aree"]:
        ore = {"F": Decimal(0), "M": Decimal(0), "ND": Decimal(0)}
        formati: set[int] = set()
        per_id = {p.id: p for p in tutti}
        for r in TrainingEmployeeRecord.objects.filter(
            legacy_anagrafica_id__in=ctx.id_estesi(per_id), data_completamento__range=(ctx.date_from, ctx.date_to),
        ).select_related("corso").only("legacy_anagrafica_id", "ore_frequentate", "duration_hours_snapshot",
                                       "corso__durata_ore_teorica"):
            pid = ctx.canonico(r.legacy_anagrafica_id)
            if pid not in per_id:
                continue
            g = per_id[pid].genere
            g = g if g in ("F", "M") else "ND"
            ore[g] += _ore_record(r)
            formati.add(pid)
        _riga("Opportunità di crescita", "Persone formate nel periodo", [per_id[i] for i in formati])
        ore_tot = sum(ore.values(), Decimal(0))
        res.riga({"area": "Opportunità di crescita", "indicatore": "Ore di formazione nel periodo",
                  "donne": ore["F"], "uomini": ore["M"], "nd": ore["ND"], "totale": ore_tot,
                  "pct_donne": _pct(float(ore["F"]), float(ore_tot))})
        media = {g: (ore[g] / org[g]) if org[g] else None for g in ("F", "M")}
        res.riga({"area": "Opportunità di crescita", "indicatore": "Ore medie pro capite (in forza)",
                  "donne": media["F"], "uomini": media["M"], "nd": None, "totale": None, "pct_donne": ""})

    tot_org = sum(org.values())
    tot_resp = sum(resp.values())
    tot_ass = sum(ass.values())
    res.kpis = [Kpi("Donne in organico", _pct(org["F"], tot_org), hint=f"{org['F']} su {tot_org}")]
    if "governance" in o["aree"]:
        res.kpis.append(Kpi("Donne tra i responsabili", _pct(resp["F"], tot_resp), hint=f"{resp['F']} su {tot_resp}"))
    if "processi_hr" in o["aree"]:
        res.kpis.append(Kpi("Donne tra gli assunti", _pct(ass["F"], tot_ass), hint=f"{ass['F']} su {tot_ass} nel periodo"))
    if "crescita" in o["aree"]:
        res.kpis.append(Kpi("Ore formazione medie D / U", f"{_fmt_ore(media['F'])} / {_fmt_ore(media['M'])}"))
    res.kpis.append(Kpi("Genere non registrato", org["ND"], TONE_WARN if org["ND"] else TONE_OK,
                        "completa l'anagrafica civile" if org["ND"] else ""))
    res.note = [
        "Dati aggregati per genere, nessun nominativo. Le righe con pochissime persone possono comunque "
        "rendere riconoscibile un individuo: usa la soglia di anonimato prima di diffondere il documento all'esterno.",
        "Equità remunerativa e tutela della genitorialità non sono calcolate qui: integrale con un blocco di testo.",
        "Responsabili = capi reparto e responsabili di area aziendale da catalogo.",
    ]
    if k > 1:
        res.note.append(f"Conteggi sotto {k} mostrati come «<{k}».")
    return res


_registra(Sezione(
    key="pdr125_indicatori",
    titolo="Indicatori di parità di genere",
    gruppo=GRUPPO_PDR,
    descrizione="Organico per genere nelle dimensioni scelte, responsabili, assunzioni, cessazioni, formazione.",
    builder=_parita_genere,
    riferimenti=(f"{PDR_125} – KPI delle aree di valutazione",),
    colonne=(("area", "Area PdR 125"), ("indicatore", "Indicatore"), ("donne", "Donne"), ("uomini", "Uomini"),
             ("nd", "N.D."), ("totale", "Totale"), ("pct_donne", "% donne")),
    predefinite=("area", "indicatore", "donne", "uomini", "totale", "pct_donne"),
    opzioni=(
        Opzione("dimensioni", "Distribuzioni dell'organico", MULTI, _DIMENSIONI_PDR, ("contratto", "livello", "reparto")),
        Opzione("aree", "Aree PdR 125 da calcolare", MULTI, _AREE_PDR, ("governance", "processi_hr", "crescita")),
        _OPZ_ANONIMATO,
    ),
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
        def _builder(ctx: Contesto, o: dict, _definition=definition) -> Risultato:
            params = ReportParams(date_from=ctx.date_from, date_to=ctx.date_to, today=ctx.today)
            result = _definition.build(params)
            colonne = [(f"c{i}", label) for i, label in enumerate(result.columns)]
            res = Risultato(kpis=list(result.kpis), colonne=colonne, note=list(result.notes))
            for values, tono in zip(result.rows, result.row_tones):
                res.riga({k: values[i] if i < len(values) else "" for i, (k, _l) in enumerate(colonne)}, tono)
            return res

        def _permesso(request, _code=PERM_AREA.get(definition.area)) -> bool:
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
            colonne_dinamiche=True,
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
