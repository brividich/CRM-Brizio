"""Libretto sanitario aziendale — il fascicolo leggibile di una persona.

Risponde, in una pagina sola e in ordine di lettura, alla catena che oggi è
sparsa fra più schermate:

    fattori di rischio → mansione di rischio → mansione di lavoro della persona
    → requisiti dovuti (visite / DPI / formazione) → conforme o non conforme

Non introduce una seconda verità: i requisiti arrivano dal resolver unico
(``services.mansionario.requisiti_dipendente_dettaglio``, che include mansione +
area + esposizioni diritte) sommati a quelli dei processi qualificati
(``services.mpq_idoneita``), e lo stato è calcolato con le stesse regole e la
stessa soglia di preavviso del semaforo di conformità (``services.conformita``).
La differenza è la **granularità**: qui ogni obbligo è una riga con la sua data,
la sua scadenza e la sua origine, perché un elenco di adempimenti che non dice
"perché è dovuto" e "quando scade" non è verificabile — e questa è la parte del
portale che in un'ispezione fa la differenza fra una sanzione e una risposta.

Privacy (dati sanitari, art. 9 GDPR): i nomi delle tipologie di visita e il
giudizio di idoneità sono inclusi **solo** se ``include_visite_dettaglio=True``
— il chiamante deve passarci l'esito del gate ``_can_view_visite_mediche``.
Le prescrizioni del medico competente non sono MAI esposte qui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from django.utils import timezone

from . import mansionario
from ..models import DipendenteQualifica, VisitaMedica
from ..models_formazione import TrainingDeadline
from .conformita import (
    ESITO_KO,
    ESITO_NA,
    ESITO_OK,
    ESITO_WARN,
    SOGLIA_WARN_GIORNI,
)

# Stato di una singola riga del libretto. "mancante" non è "scaduto": un
# requisito mai registrato è un adempimento da fare, non una violazione in atto
# — la distinzione è la stessa già adottata dal semaforo di conformità.
STATO_OK = ESITO_OK
STATO_WARN = ESITO_WARN
STATO_KO = ESITO_KO
STATO_MANCANTE = "mancante"

_PESO_STATO = {STATO_OK: 0, STATO_MANCANTE: 1, STATO_WARN: 2, STATO_KO: 3}

STATO_LABEL = {
    STATO_OK: "Conforme",
    STATO_WARN: "In scadenza",
    STATO_KO: "Scaduto",
    STATO_MANCANTE: "Da acquisire",
}

VERDETTO_LABEL = {
    STATO_OK: "Conforme",
    STATO_WARN: "Conforme, con scadenze imminenti",
    STATO_MANCANTE: "Incompleto — adempimenti da acquisire",
    STATO_KO: "NON conforme",
    ESITO_NA: "Nessun requisito applicabile",
}


@dataclass
class Riga:
    """Un obbligo della persona, con la sua evidenza e la sua origine."""

    dominio: str  # "visite" | "dpi" | "corsi"
    nome: str
    stato: str
    origini: list[str] = field(default_factory=list)
    data_ultima: date | None = None
    data_scadenza: date | None = None
    giorni: int | None = None
    nota: str = ""

    @property
    def stato_label(self) -> str:
        return STATO_LABEL.get(self.stato, "—")

    @property
    def conforme(self) -> bool:
        return self.stato in (STATO_OK, STATO_WARN)


def _stato_da_scadenza(
    data_scadenza: date | None, oggi: date
) -> tuple[str, int | None]:
    """Regola unica scadenza→stato (stessa soglia del semaforo conformità)."""
    if data_scadenza is None:
        return STATO_OK, None
    giorni = (data_scadenza - oggi).days
    if giorni < 0:
        return STATO_KO, giorni
    if giorni <= SOGLIA_WARN_GIORNI:
        return STATO_WARN, giorni
    return STATO_OK, giorni


def _peggiore(stati: list[str]) -> str:
    if not stati:
        return ESITO_NA
    return max(stati, key=lambda s: _PESO_STATO.get(s, 0))


def _dedup_pk(items: list) -> list:
    visti, out = set(), []
    for obj in items:
        if obj is not None and obj.pk not in visti:
            visti.add(obj.pk)
            out.append(obj)
    return out


def _consegne_dpi(legacy_id: int) -> dict[int, Any]:
    """Consegna più recente per categoria DPI. ``{}`` se il modulo manca."""
    try:
        from dpi.models import ConsegnaDPI, StatoRichiesta
    except Exception:
        return {}
    out: dict[int, Any] = {}
    for consegna in (
        ConsegnaDPI.objects
        .filter(
            richiesta__richiedente_legacy_id=legacy_id,
            richiesta__stato=StatoRichiesta.CONSEGNATA,
        )
        .select_related("richiesta")
        .order_by("-data_consegna", "-created_at")
    ):
        out.setdefault(consegna.richiesta.categoria_id, consegna)
    return out


def _ultime_visite(legacy_id: int) -> dict[int, VisitaMedica]:
    """Ultima visita registrata per tipologia."""
    out: dict[int, VisitaMedica] = {}
    for visita in (
        VisitaMedica.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .order_by("-data_svolgimento", "-pk")
    ):
        out.setdefault(visita.tipo_id, visita)
    return out


def _righe_visite(
    tipi, legacy_id: int, origini, oggi: date, *, include_dettaglio: bool
) -> list[Riga]:
    ultime = _ultime_visite(legacy_id) if tipi else {}
    righe: list[Riga] = []
    for tipo in tipi:
        etichetta = tipo.nome if include_dettaglio else "Visita medica richiesta"
        ultima = ultime.get(tipo.pk)
        if ultima is None:
            righe.append(Riga(
                dominio="visite", nome=etichetta, stato=STATO_MANCANTE,
                origini=origini.get(("visite", tipo.pk), []),
                nota="Mai registrata",
            ))
            continue
        stato, giorni = _stato_da_scadenza(ultima.data_scadenza, oggi)
        # Il giudizio di idoneità è il cuore del libretto, ma è un dato
        # sanitario: esce solo con il gate sorveglianza. Le prescrizioni no, mai.
        nota = ultima.get_esito_display() if include_dettaglio else ""
        righe.append(Riga(
            dominio="visite", nome=etichetta, stato=stato,
            origini=origini.get(("visite", tipo.pk), []),
            data_ultima=ultima.data_svolgimento,
            data_scadenza=ultima.data_scadenza,
            giorni=giorni, nota=nota,
        ))
    return righe


def _righe_dpi(categorie, legacy_id: int, origini, oggi: date) -> list[Riga]:
    consegne = _consegne_dpi(legacy_id) if categorie else {}
    righe: list[Riga] = []
    for categoria in categorie:
        consegna = consegne.get(categoria.pk)
        if consegna is None:
            righe.append(Riga(
                dominio="dpi", nome=categoria.nome, stato=STATO_MANCANTE,
                origini=origini.get(("dpi", categoria.pk), []),
                nota="Nessuna consegna registrata",
            ))
            continue
        stato, giorni = _stato_da_scadenza(consegna.data_scadenza_stimata, oggi)
        righe.append(Riga(
            dominio="dpi", nome=categoria.nome, stato=stato,
            origini=origini.get(("dpi", categoria.pk), []),
            data_ultima=consegna.data_consegna,
            data_scadenza=consegna.data_scadenza_stimata,
            giorni=giorni,
        ))
    return righe


def _righe_corsi(corsi, legacy_id: int, origini, oggi: date) -> list[Riga]:
    if not corsi:
        return []
    deadlines = {
        d.corso_id: d
        for d in TrainingDeadline.objects.filter(
            legacy_anagrafica_id=legacy_id,
            corso_id__in=[c.pk for c in corsi],
        )
    }
    righe: list[Riga] = []
    for corso in corsi:
        d = deadlines.get(corso.pk)
        if d is None or d.stato_scadenza == "MAI_FREQUENTATO":
            righe.append(Riga(
                dominio="corsi", nome=corso.titolo, stato=STATO_MANCANTE,
                origini=origini.get(("corsi", corso.pk), []),
                nota="Mai frequentato",
            ))
            continue
        if d.stato_scadenza == "SCADUTO":
            stato = STATO_KO
        elif d.stato_scadenza in ("IN_SCADENZA_30", "IN_SCADENZA_90"):
            stato = STATO_WARN
        else:
            stato = STATO_OK
        righe.append(Riga(
            dominio="corsi", nome=corso.titolo, stato=stato,
            origini=origini.get(("corsi", corso.pk), []),
            data_ultima=d.data_ultimo_completamento,
            data_scadenza=d.data_scadenza,
            giorni=d.giorni_alla_scadenza,
            nota="Una tantum" if d.stato_scadenza == "UNA_TANTUM" else "",
        ))
    return righe


def _righe_qualifiche(legacy_id: int, oggi: date) -> list[Riga]:
    """Abilitazioni possedute: non sono un obbligo di mansione, ma un titolo
    che scade — nel libretto vanno lette accanto al resto, non altrove."""
    righe: list[Riga] = []
    for q in (
        DipendenteQualifica.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .select_related("tipo")
        .order_by("tipo__nome")
    ):
        stato, giorni = _stato_da_scadenza(q.data_scadenza, oggi)
        righe.append(Riga(
            dominio="qualifiche", nome=q.tipo.nome, stato=stato,
            origini=["Titolo posseduto"],
            data_ultima=q.data_conseguimento,
            data_scadenza=q.data_scadenza,
            giorni=giorni,
            nota=q.livello or "",
        ))
    return righe


def libretto(
    legacy_id: int,
    *,
    mansione_nome: str | None = None,
    area_id: int | None = None,
    include_visite_dettaglio: bool = False,
) -> dict[str, Any]:
    """Libretto sanitario completo di una persona.

    Ritorna::

        {
          "mansione_nome": str,
          "fattori": [FattoreRischio, ...],      # la "mansione di rischio"
          "sezioni": [{"chiave", "titolo", "icona", "descrizione",
                       "righe": [Riga], "stato"}],
          "righe": [Riga, ...],                  # tutte, per i conteggi
          "conteggi": {"ok", "warn", "ko", "mancante", "totale"},
          "verdetto": "ok"|"warn"|"mancante"|"ko"|"na",
          "verdetto_label": str,
          "criticita": [Riga, ...],              # scaduti + mancanti, in testa
          "aggiornato_al": date,
        }
    """
    oggi = timezone.localdate()

    dettaglio = mansionario.requisiti_dipendente_dettaglio(
        legacy_id, mansione_nome=mansione_nome, area_id=area_id
    )
    requisiti = dettaglio["requisiti"]
    origini: dict[tuple[str, Any], list[str]] = dict(dettaglio["origini"])

    # Requisiti aggiuntivi dei processi qualificati (MOD.128): stessa somma che
    # fa il semaforo di conformità, così le due viste non divergono mai.
    try:
        from .mpq_idoneita import requisiti_processo_dettaglio
        proc = requisiti_processo_dettaglio([legacy_id]).get(legacy_id)
    except Exception:
        proc = None
    if proc:
        for chiave, etichette in proc["origini"].items():
            voci = origini.setdefault(chiave, [])
            for etichetta in etichette:
                if etichetta not in voci:
                    voci.append(etichetta)
        for dominio in ("dpi", "visite", "corsi"):
            requisiti[dominio] = _dedup_pk(
                list(requisiti[dominio]) + list(proc["requisiti"][dominio])
            )

    righe_visite = _righe_visite(
        requisiti["visite"], legacy_id, origini, oggi,
        include_dettaglio=include_visite_dettaglio,
    )
    righe_dpi = _righe_dpi(requisiti["dpi"], legacy_id, origini, oggi)
    righe_corsi = _righe_corsi(requisiti["corsi"], legacy_id, origini, oggi)
    righe_qualifiche = _righe_qualifiche(legacy_id, oggi)

    sezioni = [
        {
            "chiave": "visite",
            "titolo": "Sorveglianza sanitaria",
            "icona": "🏥",
            "descrizione": "Visite mediche dovute per la mansione e i rischi a cui la persona è esposta.",
            "righe": righe_visite,
        },
        {
            "chiave": "dpi",
            "titolo": "Dispositivi di protezione individuale",
            "icona": "🦺",
            "descrizione": "DPI da consegnare e da sostituire alla scadenza.",
            "righe": righe_dpi,
        },
        {
            "chiave": "corsi",
            "titolo": "Formazione obbligatoria",
            "icona": "📚",
            "descrizione": "Corsi richiesti dalla mansione, dai rischi e dai processi qualificati.",
            "righe": righe_corsi,
        },
        {
            "chiave": "qualifiche",
            "titolo": "Abilitazioni e qualifiche",
            "icona": "🎓",
            "descrizione": "Titoli posseduti dalla persona, con la loro validità.",
            "righe": righe_qualifiche,
        },
    ]
    for sezione in sezioni:
        sezione["stato"] = _peggiore([r.stato for r in sezione["righe"]])

    # Il verdetto pesa solo gli **obblighi** di mansione: una qualifica scaduta
    # che nessun requisito impone non rende la persona non idonea.
    righe_obbligo = righe_visite + righe_dpi + righe_corsi
    tutte = righe_obbligo + righe_qualifiche
    verdetto = _peggiore([r.stato for r in righe_obbligo])

    conteggi = {
        stato: sum(1 for r in righe_obbligo if r.stato == stato)
        for stato in (STATO_OK, STATO_WARN, STATO_KO, STATO_MANCANTE)
    }
    conteggi["totale"] = len(righe_obbligo)

    criticita = sorted(
        [r for r in righe_obbligo if r.stato in (STATO_KO, STATO_MANCANTE)],
        key=lambda r: (_PESO_STATO.get(r.stato, 0) * -1, r.dominio, r.nome),
    )

    return {
        "mansione_nome": dettaglio["mansione_nome"],
        "fattori": requisiti["fattori"],
        "piani": requisiti["piani"],
        "sezioni": sezioni,
        "righe": tutte,
        "conteggi": conteggi,
        "verdetto": verdetto,
        "verdetto_label": VERDETTO_LABEL.get(verdetto, "—"),
        "criticita": criticita,
        "aggiornato_al": oggi,
    }
