"""Collegare le scadenze generiche alle cose già presenti nel portale.

Due livelli, scelti sempre da una persona:

- **collegata**: la scheda dell'attività rimanda all'oggetto e la scheda dell'oggetto
  elenca l'attività; ognuna tiene la sua data;
- **unita** (solo se l'oggetto ha una data sua: certificazione, verifica impianto):
  resta una voce sola nel calendario, quella del modulo. L'attività conserva storico
  e destinatari degli avvisi e prende la data dal modulo. Si può separare di nuovo.

I suggerimenti confrontano i testi, quindi possono sbagliare: non collegano mai da soli.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

from django.apps import apps
from django.db.models import Q
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)

_PAROLE_VUOTE = frozenset(
    "della delle dello degli dell verifica verifiche controllo controlli scadenza rinnovo manutenzione impianto "
    "impianti contratto contratti certificato certificati certificazione certificazioni servizio servizi annuale "
    "periodica periodico corso corsi formazione aggiornamento srl spa snc sas".split()
)


def _url(nome: str, *args) -> str:
    try:
        return reverse(nome, args=args)
    except NoReverseMatch:
        return ""


@dataclass(frozen=True)
class Tipo:
    codice: str
    etichetta: str
    modello: str
    campo_ricerca: str
    testo: Callable
    url: Callable
    data: Callable | None = None  # con una data propria si può anche unire
    campo_fk: str = ""  # asset e fornitore usano le colonne già esistenti
    filtro: tuple = ()

    @property
    def si_unisce(self) -> bool:
        return self.data is not None

    def oggetti(self):
        return apps.get_model(self.modello).objects.filter(**dict(self.filtro))


TIPI: dict[str, Tipo] = {t.codice: t for t in (
    Tipo("certificazione", "Certificazione", "sistema_gestione.Certificazione", "descrizione ente norma numero",
         lambda o: " ".join(p for p in (o.get_norma_display(), o.descrizione, o.ente) if p),
         lambda o: _url("sistema_gestione:esterni_certificazione", o.pk),
         data=lambda o: o.scade_il, filtro=(("attiva", True),)),
    Tipo("verifica", "Verifica impianto", "assets.PeriodicCheckType", "name",
         lambda o: o.name, lambda o: _url("assets:periodic_check_type_detail", o.pk),
         data=lambda o: o.next_due_date, filtro=(("is_active", True),)),
    Tipo("asset", "Asset", "assets.Asset", "name",
         lambda o: o.name, lambda o: _url("assets:asset_view", o.pk), campo_fk="asset"),
    Tipo("fornitore", "Fornitore", "anagrafica.Fornitore", "ragione_sociale",
         lambda o: o.ragione_sociale, lambda o: _url("fornitori:fornitore_detail", o.pk),
         campo_fk="fornitore", filtro=(("is_active", True),)),
    Tipo("qualifica", "Tipo di qualifica", "anagrafica.TipoQualifica", "nome",
         lambda o: o.nome, lambda o: _url("anagrafica:qualifiche_dashboard")),
    Tipo("corso", "Corso", "anagrafica.TrainingCourse", "titolo",
         lambda o: o.titolo, lambda o: _url("anagrafica:formazione_corso_detail", o.pk)),
)}


def _oggetto(tipo: Tipo, oggetto_id):
    return apps.get_model(tipo.modello).objects.filter(pk=oggetto_id).first()


def collegamenti_di(s) -> list[dict]:
    """Ciò a cui è collegata l'attività, per la scheda."""
    esito = []
    for tipo in TIPI.values():
        if tipo.campo_fk:
            oggetto_id = getattr(s, f"{tipo.campo_fk}_id")
        else:
            oggetto_id = s.collegata_id if s.collegata_tipo == tipo.codice else None
        if not oggetto_id:
            continue
        oggetto = _oggetto(tipo, oggetto_id)
        if oggetto is None:
            continue
        esito.append({
            "tipo": tipo.codice, "etichetta": tipo.etichetta, "testo": tipo.testo(oggetto), "url": tipo.url(oggetto),
            "unita": bool(s.unita and not tipo.campo_fk), "si_unisce": tipo.si_unisce,
        })
    return esito


def collega(s, codice: str, oggetto_id, *, unisci: bool = False) -> None:
    """Salva il collegamento. ``ValueError`` con un testo da mostrare se non si può."""
    tipo = TIPI.get(codice)
    if tipo is None:
        raise ValueError("Tipo di collegamento non valido.")
    oggetto = _oggetto(tipo, oggetto_id)
    if oggetto is None:
        raise ValueError("L'elemento scelto non esiste più.")
    if unisci and not tipo.si_unisce:
        raise ValueError(f"{tipo.etichetta}: si può collegare ma non unire, perché non ha una data sola.")
    campi = ["aggiornato_il"]
    if tipo.campo_fk:
        setattr(s, tipo.campo_fk, oggetto)
        campi.append(tipo.campo_fk)
    else:
        s.collegata_tipo, s.collegata_id = tipo.codice, oggetto.pk
        s.unita = False
        campi += ["collegata_tipo", "collegata_id", "unita"]
    if unisci:
        data = tipo.data(oggetto)
        if not data:
            raise ValueError(f"{tipo.etichetta}: non ha ancora una data, si può solo collegare.")
        s.unita, s.data_scadenza = True, data
        campi.append("data_scadenza")
    s.save(update_fields=sorted(set(campi)))


def scollega(s, codice: str) -> None:
    tipo = TIPI.get(codice)
    if tipo is None:
        raise ValueError("Tipo di collegamento non valido.")
    if tipo.campo_fk:
        setattr(s, tipo.campo_fk, None)
        s.save(update_fields=[tipo.campo_fk, "aggiornato_il"])
    elif s.collegata_tipo == codice:
        s.collegata_tipo, s.collegata_id, s.unita = "", None, False
        s.save(update_fields=["collegata_tipo", "collegata_id", "unita", "aggiornato_il"])


def separa(s) -> None:
    """Toglie l'unione: l'attività torna una voce a sé con l'ultima data, resta collegata."""
    s.unita = False
    s.save(update_fields=["unita", "aggiornato_il"])


def allinea_unite() -> int:
    """Porta sulle attività unite la data del modulo. Una data sparita non cancella la precedente."""
    from .models import ScadenzaGenerica

    cambiate = 0
    for s in ScadenzaGenerica.objects.filter(unita=True):
        tipo = TIPI.get(s.collegata_tipo)
        oggetto = _oggetto(tipo, s.collegata_id) if tipo and tipo.si_unisce else None
        data = tipo.data(oggetto) if oggetto is not None else None
        if data and data != s.data_scadenza:
            ScadenzaGenerica.objects.filter(pk=s.pk).update(data_scadenza=data)
            cambiate += 1
    return cambiate


def cerca(codice: str, testo: str, limite: int = 20) -> list[dict]:
    tipo = TIPI.get(codice)
    testo = (testo or "").strip()
    if tipo is None or len(testo) < 2:
        return []
    filtro = Q()
    for campo in tipo.campo_ricerca.split():
        filtro |= Q(**{f"{campo}__icontains": testo})
    righe = tipo.oggetti().filter(filtro)[:limite]
    return [{"tipo": tipo.codice, "etichetta": tipo.etichetta, "id": o.pk, "testo": tipo.testo(o), "si_unisce": tipo.si_unisce}
            for o in righe]


def attivita_collegate(codice: str, oggetto_id):
    """Le attività collegate a un oggetto, per il riquadro nella sua scheda."""
    from .models import ScadenzaGenerica

    tipo = TIPI.get(codice)
    if tipo is None or not oggetto_id:
        return ScadenzaGenerica.objects.none()
    qs = ScadenzaGenerica.objects.filter(is_active=True).select_related("categoria")
    if tipo.campo_fk:
        return qs.filter(**{f"{tipo.campo_fk}_id": oggetto_id})
    return qs.filter(collegata_tipo=codice, collegata_id=oggetto_id)


def _parole(testo: str) -> set[str]:
    return {p for p in re.findall(r"[a-z0-9]{3,}", (testo or "").lower()) if p not in _PAROLE_VUOTE}


def suggerimenti(attivita, *, limite: int = 3) -> dict[int, list[dict]]:
    """Per ogni attività i possibili collegamenti, dal più probabile: tutti da confermare."""
    catalogo = []
    for tipo in TIPI.values():
        for oggetto in tipo.oggetti():
            testo = tipo.testo(oggetto)
            parole = _parole(testo)
            if parole:
                catalogo.append((tipo, oggetto.pk, testo, parole))
    esito: dict[int, list[dict]] = {}
    for s in attivita:
        testo_s = _parole(f"{s.titolo} {s.ubicazione or ''}")
        trovati = []
        for tipo, oggetto_id, testo, parole in catalogo:
            comuni = testo_s & parole
            if len(comuni) >= 2 or (comuni == parole and any(len(p) >= 5 for p in comuni)):
                punti = len(comuni) / len(parole)
                trovati.append((punti, len(comuni), tipo, oggetto_id, testo))
        trovati.sort(key=lambda t: (-t[0], -t[1], t[4]))
        if trovati:
            esito[s.pk] = [{"tipo": t[2].codice, "etichetta": t[2].etichetta, "id": t[3], "testo": t[4],
                            "si_unisce": t[2].si_unisce} for t in trovati[:limite]]
    return esito
