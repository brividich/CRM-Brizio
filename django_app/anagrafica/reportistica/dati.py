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

    def in_forza_al(self, giorno: date) -> bool:
        """In forza alla data: assunto (o data ignota) e non ancora cessato.

        Un dipendente spento nel legacy senza data di cessazione non ha una
        storia ricostruibile: lo si considera fuori organico.
        """
        if self.data_cessazione:
            if self.data_cessazione <= giorno:
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
    ids = [int(r.get("id") or 0) for r in rows if int(r.get("id") or 0)]
    az_map = {a.legacy_anagrafica_id: a for a in DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=ids)}
    civ_map = {
        c.legacy_anagrafica_id: c
        for c in DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id__in=ids).only(
            "legacy_anagrafica_id", "data_nascita", "genere", "titolo_studio",
        )
    }
    out: list[Dipendente] = []
    for row in rows:
        lid = int(row.get("id") or 0)
        if not lid:
            continue
        az = az_map.get(lid)
        civ = civ_map.get(lid)
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

        return set(
            DipendenteQualifica.objects.filter(tipo_id__in=tipi)
            .filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gte=self.today))
            .values_list("legacy_anagrafica_id", flat=True)
        )

    def dipendenti(self) -> list[Dipendente]:
        """Persone da elencare: in forza oggi, oppure tutte se richiesto."""
        if self.perimetro.includi_cessati:
            return self.dipendenti_perimetro()
        return [d for d in self.dipendenti_perimetro() if d.in_forza_al(self.today)]

    def ids(self) -> list[int]:
        return [d.id for d in self.dipendenti()]

    def per_id(self) -> dict[int, Dipendente]:
        return {d.id: d for d in self.dipendenti_perimetro()}
