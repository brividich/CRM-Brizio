"""Contesto di generazione: periodo, perimetro di persone e dati condivisi.

Il perimetro (reparti, aree, mansioni, persone scelte, inclusione dei cessati)
vale per tutte le sezioni del documento: le persone si leggono una volta sola e
ogni sezione lavora sulla stessa lista, cosi' i totali non divergono fra una
sezione e l'altra.
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone

from core import naming

logger = logging.getLogger(__name__)


@dataclass
class Dipendente:
    id: int
    nominativo: str
    matricola: str = ""
    reparto: str = ""
    area: str = ""
    mansione: str = ""
    ruolo_aziendale: str = ""
    contratto: str = ""
    contratto_label: str = ""
    livello: str = ""
    data_assunzione: date | None = None
    data_cessazione: date | None = None
    data_nascita: date | None = None
    genere: str = ""
    titolo_studio: str = ""
    attivo_legacy: bool = True
    # Tutti gli id legacy della persona: le anagrafiche doppie vengono fuse in
    # una riga sola, ma formazione, visite e qualifiche possono essere
    # agganciate a uno qualsiasi degli id fusi. Vuoto = solo ``id``.
    ids: tuple[int, ...] = ()

    @property
    def tutti_gli_id(self) -> tuple[int, ...]:
        return self.ids or (self.id,)

    @property
    def cessazione_effettiva(self) -> date | None:
        """Cessazione del rapporto *corrente*.

        Una riassunzione lascia la vecchia data di cessazione sulla scheda: se
        l'assunzione corrente e' successiva, la cessazione appartiene al
        rapporto precedente e la persona e' in forza.
        """
        if self.data_cessazione and self.data_assunzione and self.data_assunzione > self.data_cessazione:
            return None
        return self.data_cessazione

    def in_forza_al(self, giorno: date) -> bool:
        """In forza alla data: assunto (o data ignota) e non ancora cessato.

        Il giorno di cessazione e' l'ultimo giorno di lavoro: quel giorno la
        persona e' ancora in organico. Un dipendente spento nel legacy senza
        data di cessazione non ha una storia ricostruibile: lo si considera
        fuori organico.
        """
        cessazione = self.cessazione_effettiva
        if cessazione:
            if cessazione < giorno:
                return False
        elif not self.attivo_legacy:
            return False
        if self.data_assunzione and self.data_assunzione > giorno:
            return False
        return True


def anni_compiuti(dal: date | None, al: date) -> int | None:
    """Anni compiuti fra due date (eta', anzianita'); None se manca l'inizio."""
    if not dal:
        return None
    anni = al.year - dal.year - ((al.month, al.day) < (dal.month, dal.day))
    return max(anni, 0)


def periodo_da_tipo(tipo: str, *, oggi: date, data_da: date | None = None,
                    data_a: date | None = None) -> tuple[date, date]:
    from anagrafica.models import ReportModello as M

    if tipo == M.PERIODO_ANNO_CORRENTE:
        return date(oggi.year, 1, 1), oggi
    if tipo == M.PERIODO_ANNO_PRECEDENTE:
        return date(oggi.year - 1, 1, 1), date(oggi.year - 1, 12, 31)
    if tipo == M.PERIODO_TRIMESTRE_PRECEDENTE:
        trimestre = (oggi.month - 1) // 3
        anno = oggi.year if trimestre else oggi.year - 1
        trimestre = trimestre or 4
        mese_inizio = (trimestre - 1) * 3 + 1
        mese_fine = mese_inizio + 2
        return date(anno, mese_inizio, 1), date(anno, mese_fine, calendar.monthrange(anno, mese_fine)[1])
    if tipo == M.PERIODO_MESE_PRECEDENTE:
        fine = date(oggi.year, oggi.month, 1) - timedelta(days=1)
        return date(fine.year, fine.month, 1), fine
    if tipo == M.PERIODO_PERSONALIZZATO and data_da and data_a:
        return (data_da, data_a) if data_da <= data_a else (data_a, data_da)
    return oggi - timedelta(days=365), oggi


# SQL Server accetta al massimo ~2100 parametri per query: un ``__in`` piu' lungo
# fallisce. Ogni filtro su elenchi di id si fa a blocchi.
BLOCCO_IN = 1000


def a_blocchi(valori, dimensione: int = BLOCCO_IN):
    """Elenco -> blocchi di al massimo ``dimensione`` elementi (ordine conservato)."""
    lista = list(valori)
    for i in range(0, len(lista), dimensione):
        yield lista[i:i + dimensione]


def filtra_in(qs, campo: str, valori) -> list:
    """``qs.filter(<campo>__in=valori)`` letto a blocchi; l'ordinamento finale spetta al chiamante."""
    out: list = []
    for blocco in a_blocchi(sorted(set(valori))):
        out.extend(qs.filter(**{f"{campo}__in": blocco}))
    return out


def persone_a_blocchi(persone: dict, dimensione: int = 500):
    """Sotto-dizionari di persone: tutti gli id di una persona restano nello stesso blocco."""
    chiavi = list(persone)
    for i in range(0, len(chiavi), dimensione):
        yield {k: persone[k] for k in chiavi[i:i + dimensione]}


def _interi(raw) -> list[int]:
    out = []
    for x in raw if isinstance(raw, list) else []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return sorted(set(out))


def _data(raw) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        return None


@dataclass
class Perimetro:
    reparti: list[str] = field(default_factory=list)
    aree: list[str] = field(default_factory=list)
    mansioni: list[str] = field(default_factory=list)
    contratti: list[str] = field(default_factory=list)
    livelli: list[str] = field(default_factory=list)
    persone: list[int] = field(default_factory=list)
    escludi: list[int] = field(default_factory=list)
    # Persone che possiedono almeno una di queste qualifiche (TipoQualifica) non scaduta.
    qualifiche: list[int] = field(default_factory=list)
    assunti_dal: date | None = None
    assunti_al: date | None = None
    includi_cessati: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> "Perimetro":
        data = data if isinstance(data, dict) else {}

        def _lista(key: str) -> list[str]:
            raw = data.get(key) or []
            return [str(x).strip() for x in raw if str(x).strip()] if isinstance(raw, list) else []

        return cls(
            reparti=_lista("reparti"), aree=_lista("aree"), mansioni=_lista("mansioni"),
            contratti=_lista("contratti"), livelli=_lista("livelli"),
            persone=_interi(data.get("persone")), escludi=_interi(data.get("escludi")),
            qualifiche=_interi(data.get("qualifiche")),
            assunti_dal=_data(data.get("assunti_dal")), assunti_al=_data(data.get("assunti_al")),
            includi_cessati=bool(data.get("includi_cessati")),
        )

    def as_dict(self) -> dict:
        return {
            "reparti": self.reparti, "aree": self.aree, "mansioni": self.mansioni,
            "contratti": self.contratti, "livelli": self.livelli,
            "persone": self.persone, "escludi": self.escludi, "qualifiche": self.qualifiche,
            "assunti_dal": self.assunti_dal.isoformat() if self.assunti_dal else "",
            "assunti_al": self.assunti_al.isoformat() if self.assunti_al else "",
            "includi_cessati": self.includi_cessati,
        }

    def label(self, nomi_persone: dict[int, str] | None = None) -> str:
        nomi_persone = nomi_persone or {}
        parti = []
        for etichetta, valori in (("Reparti", self.reparti), ("Aree", self.aree), ("Mansioni", self.mansioni),
                                  ("Contratti", self.contratti), ("Livelli", self.livelli)):
            if valori:
                parti.append(f"{etichetta}: " + ", ".join(valori))
        if self.persone:
            if len(self.persone) <= 6:
                parti.append("Persone: " + ", ".join(nomi_persone.get(p, f"#{p}") for p in self.persone))
            else:
                parti.append(f"Persone selezionate: {len(self.persone)}")
        if self.escludi:
            parti.append(f"Escluse: {len(self.escludi)} persone")
        if self.qualifiche:
            parti.append(f"Con qualifica valida ({len(self.qualifiche)} tipi)")
        if self.assunti_dal or self.assunti_al:
            parti.append("Assunti " + (f"dal {self.assunti_dal:%d/%m/%Y} " if self.assunti_dal else "")
                         + (f"al {self.assunti_al:%d/%m/%Y}" if self.assunti_al else "")).strip()
        parti.append("inclusi i cessati" if self.includi_cessati else "solo personale in forza")
        return " · ".join(parti)


def _id_fusi(row: dict) -> tuple[int, ...]:
    """Id principale per primo, poi gli id delle anagrafiche doppie fuse nella riga."""
    lid = int(row.get("id") or 0)
    altri = sorted({int(x) for x in (row.get("_merged_ids") or []) if int(x or 0) > 0} - {lid})
    return tuple([lid] if lid else []) + tuple(altri)


def carica_dipendenti() -> list[Dipendente]:
    """Tutti i dipendenti (deduplicati) con dati aziendali e civili essenziali."""
    from anagrafica.models import DipendenteAnagraficaAziendale, DipendenteAnagraficaCivile
    from anagrafica.services.reparto_canonico import enrich_rows_reparto_canonico
    from anagrafica.templatetags.anagrafica_extras import matricola_fmt
    from core.legacy_anagrafica import fetch_anagrafica_rows

    try:
        rows = fetch_anagrafica_rows(deduplicate=True)
    except Exception:
        logger.warning("reportistica: anagrafica legacy non leggibile", exc_info=True)
        return []
    enrich_rows_reparto_canonico(rows)
    ids = sorted({i for r in rows for i in _id_fusi(r)})
    az_map = {a.legacy_anagrafica_id: a
              for a in filtra_in(DipendenteAnagraficaAziendale.objects.all(), "legacy_anagrafica_id", ids)}
    civ_map = {
        c.legacy_anagrafica_id: c
        for c in filtra_in(DipendenteAnagraficaCivile.objects.only(
            "legacy_anagrafica_id", "data_nascita", "genere", "titolo_studio",
        ), "legacy_anagrafica_id", ids)
    }
    out: list[Dipendente] = []
    for row in rows:
        lid = int(row.get("id") or 0)
        if not lid:
            continue
        fusi = _id_fusi(row)
        # Scheda aziendale/civile: quella dell'id principale, altrimenti quella
        # di un id fuso (la scheda puo' essere stata compilata sul doppione).
        az = next((az_map[i] for i in fusi if i in az_map), None)
        civ = next((civ_map[i] for i in fusi if i in civ_map), None)
        out.append(Dipendente(
            id=lid,
            nominativo=naming.nome_completo(row.get("nome"), row.get("cognome")) or f"Dipendente #{lid}",
            matricola=matricola_fmt(row.get("matricola")),
            reparto=str(row.get("reparto") or "").strip(),
            area=str(row.get("area_aziendale_nome") or "").strip(),
            mansione=str(row.get("mansione") or "").strip(),
            ruolo_aziendale=(az.ruolo_aziendale if az else "") or "",
            contratto=(az.tipologia_contratto if az else "") or "",
            contratto_label=(az.get_tipologia_contratto_display() if az and az.tipologia_contratto else ""),
            livello=(az.livello_inquadramento if az else "") or "",
            data_assunzione=(az.data_assunzione_ultima or az.data_prima_assunzione) if az else None,
            data_cessazione=az.data_cessazione if az else None,
            data_nascita=civ.data_nascita if civ else None,
            genere=(civ.genere if civ else "") or "",
            titolo_studio=(civ.get_titolo_studio_display() if civ and civ.titolo_studio else ""),
            attivo_legacy=bool(row.get("attivo", True)),
            ids=fusi,
        ))
    out.sort(key=lambda d: d.nominativo.casefold())
    return out


@dataclass
class Contesto:
    date_from: date
    date_to: date
    perimetro: Perimetro
    request: object = None
    today: date = field(default_factory=timezone.localdate)
    _cache: dict = field(default_factory=dict)

    @property
    def periodo_label(self) -> str:
        return f"{self.date_from:%d/%m/%Y} – {self.date_to:%d/%m/%Y}"

    def _tutti(self) -> list[Dipendente]:
        if "tutti" not in self._cache:
            self._cache["tutti"] = carica_dipendenti()
        return self._cache["tutti"]

    def dipendenti_perimetro(self) -> list[Dipendente]:
        """Persone che rispettano i filtri del perimetro, cessati compresi.

        Serve agli indicatori di periodo (assunzioni, cessazioni, turnover) che
        devono vedere anche chi e' uscito.
        """
        if "perimetro" not in self._cache:
            p = self.perimetro
            reparti = {x.casefold() for x in p.reparti}
            aree = {x.casefold() for x in p.aree}
            mansioni = {x.casefold() for x in p.mansioni}
            livelli = {x.casefold() for x in p.livelli}
            contratti = set(p.contratti)
            persone = set(p.persone)
            escludi = set(p.escludi)
            con_qualifica = self._con_qualifica(p.qualifiche) if p.qualifiche else None
            out = []
            for dip in self._tutti():
                if dip.id in escludi or (persone and dip.id not in persone):
                    continue
                if reparti and dip.reparto.casefold() not in reparti:
                    continue
                if aree and dip.area.casefold() not in aree:
                    continue
                if mansioni and dip.mansione.casefold() not in mansioni:
                    continue
                if contratti and dip.contratto not in contratti:
                    continue
                if livelli and dip.livello.casefold() not in livelli:
                    continue
                if con_qualifica is not None and dip.id not in con_qualifica:
                    continue
                if p.assunti_dal and not (dip.data_assunzione and dip.data_assunzione >= p.assunti_dal):
                    continue
                if p.assunti_al and not (dip.data_assunzione and dip.data_assunzione <= p.assunti_al):
                    continue
                out.append(dip)
            self._cache["perimetro"] = out
        return self._cache["perimetro"]

    def _con_qualifica(self, tipi: list[int]) -> set[int]:
        from django.db.models import Q

        from anagrafica.models import DipendenteQualifica

        return {
            self.canonico(lid) for lid in
            DipendenteQualifica.objects.filter(tipo_id__in=tipi)
            .filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gte=self.today))
            .values_list("legacy_anagrafica_id", flat=True)
        }

    def dipendenti(self) -> list[Dipendente]:
        """Persone da elencare: in forza oggi, oppure tutte se richiesto."""
        if self.perimetro.includi_cessati:
            return self.dipendenti_perimetro()
        return [d for d in self.dipendenti_perimetro() if d.in_forza_al(self.today)]

    def ids(self) -> list[int]:
        return [d.id for d in self.dipendenti()]

    def per_id(self) -> dict[int, Dipendente]:
        return {d.id: d for d in self.dipendenti_perimetro()}

    # ── Id legacy fusi ────────────────────────────────────────────────────
    # Le query sui dati collegati (formazione, visite, qualifiche…) vanno fatte
    # su *tutti* gli id di ogni persona e ricondotte all'id principale, altrimenti
    # i record agganciati a un'anagrafica doppia spariscono dal report.

    def _alias(self) -> dict[int, int]:
        if "alias" not in self._cache:
            self._cache["alias"] = {i: d.id for d in self._tutti() for i in d.tutti_gli_id}
        return self._cache["alias"]

    def canonico(self, legacy_id: int) -> int:
        """Id principale della persona a cui appartiene ``legacy_id``."""
        return self._alias().get(legacy_id, legacy_id)

    @staticmethod
    def id_estesi(persone) -> list[int]:
        """Tutti gli id legacy (principali e fusi) di una collezione di persone."""
        valori = persone.values() if isinstance(persone, dict) else persone
        return sorted({i for p in valori for i in p.tutti_gli_id})

    # ── Avvisi ────────────────────────────────────────────────────────────
    # Un dato che non si e' potuto leggere va scritto nel documento, sotto la
    # sezione che ne dipende: il motore raccoglie gli avvisi di ogni sezione.

    def avviso(self, testo: str) -> None:
        correnti = self._cache.setdefault("avvisi_sezione", [])
        if testo not in correnti:
            correnti.append(testo)

    def raccogli_avvisi(self) -> list[str]:
        """Avvisi emessi dall'ultima chiamata; svuota l'elenco per la sezione successiva."""
        return self._cache.pop("avvisi_sezione", [])

    def segnala_esclusi(self, legacy_ids, *, incluse, cosa: str) -> None:
        """Dice perche' alcune registrazioni trovate non sono nella tabella.

        Un report non deve mai «perdere» dati in silenzio: per ogni
        registrazione esistente ma non riportata si scrive il motivo come
        avviso della sezione. ``incluse`` = id principali delle persone elencate.
        """
        incluse = set(incluse)
        alias = self._alias()
        perimetro = {d.id for d in self.dipendenti_perimetro()}
        cessate = fuori = orfane = 0
        for lid in legacy_ids:
            pid = alias.get(lid)
            if pid is None:
                orfane += 1
            elif pid in incluse:
                continue
            elif pid in perimetro:
                cessate += 1
            else:
                fuori += 1
        titolo = cosa[:1].upper() + cosa[1:]
        if cessate:
            self.avviso(f"{titolo} di persone non più in forza, non riportate: {cessate}. "
                        "Attiva «Includi il personale cessato» per vederle.")
        if fuori:
            self.avviso(f"{titolo} di persone fuori dal perimetro scelto, non riportate: {fuori}.")
        if orfane:
            self.avviso(f"{titolo} agganciate a un'anagrafica che non esiste più: {orfane}. Non si possono "
                        "attribuire a nessuno: vanno ricollegate alla persona giusta.")
