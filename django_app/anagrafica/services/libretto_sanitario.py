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


def _consegne_dpi_batch(legacy_ids: list[int]) -> dict[tuple[int, int], Any]:
    """Consegna più recente per ``(legacy_id, categoria)``. ``{}`` se il modulo manca."""
    try:
        from dpi.models import ConsegnaDPI, StatoRichiesta
    except Exception:
        return {}
    out: dict[tuple[int, int], Any] = {}
    for consegna in (
        ConsegnaDPI.objects
        .filter(
            richiesta__richiedente_legacy_id__in=legacy_ids,
            richiesta__stato=StatoRichiesta.CONSEGNATA,
        )
        .select_related("richiesta")
        .order_by("-data_consegna", "-created_at")
    ):
        out.setdefault(
            (consegna.richiesta.richiedente_legacy_id, consegna.richiesta.categoria_id),
            consegna,
        )
    return out


def _ultime_visite_batch(legacy_ids: list[int]) -> dict[tuple[int, int], VisitaMedica]:
    """Ultima visita registrata per ``(legacy_id, tipo)``."""
    out: dict[tuple[int, int], VisitaMedica] = {}
    for visita in (
        VisitaMedica.objects
        .filter(legacy_anagrafica_id__in=legacy_ids)
        .order_by("-data_svolgimento", "-pk")
    ):
        out.setdefault((visita.legacy_anagrafica_id, visita.tipo_id), visita)
    return out


def _deadline_batch(
    legacy_ids: list[int], corso_ids: set[int]
) -> dict[tuple[int, int], TrainingDeadline]:
    if not corso_ids:
        return {}
    return {
        (d.legacy_anagrafica_id, d.corso_id): d
        for d in TrainingDeadline.objects.filter(
            legacy_anagrafica_id__in=legacy_ids, corso_id__in=corso_ids
        )
    }


def _qualifiche_batch(legacy_ids: list[int]) -> dict[int, list[DipendenteQualifica]]:
    out: dict[int, list[DipendenteQualifica]] = {}
    for q in (
        DipendenteQualifica.objects
        .filter(legacy_anagrafica_id__in=legacy_ids)
        .select_related("tipo")
        .order_by("tipo__nome")
    ):
        out.setdefault(q.legacy_anagrafica_id, []).append(q)
    return out


def _righe_visite(
    tipi, legacy_id: int, origini, oggi: date, ultime, *, include_dettaglio: bool
) -> list[Riga]:
    righe: list[Riga] = []
    for tipo in tipi:
        etichetta = tipo.nome if include_dettaglio else "Visita medica richiesta"
        ultima = ultime.get((legacy_id, tipo.pk))
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


def _righe_dpi(categorie, legacy_id: int, origini, oggi: date, consegne) -> list[Riga]:
    righe: list[Riga] = []
    for categoria in categorie:
        consegna = consegne.get((legacy_id, categoria.pk))
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


def _righe_corsi(corsi, legacy_id: int, origini, oggi: date, deadlines) -> list[Riga]:
    righe: list[Riga] = []
    for corso in corsi:
        d = deadlines.get((legacy_id, corso.pk))
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


def _righe_qualifiche(qualifiche, oggi: date) -> list[Riga]:
    """Abilitazioni possedute: non sono un obbligo di mansione, ma un titolo
    che scade — nel libretto vanno lette accanto al resto, non altrove."""
    righe: list[Riga] = []
    for q in qualifiche:
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


def _sezioni(righe_visite, righe_dpi, righe_corsi, righe_qualifiche) -> list[dict]:
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
    return sezioni


def libretto_batch(
    legacy_ids,
    *,
    mansioni_per_legacy: dict[int, str] | None = None,
    aree_per_legacy: dict[int, int | None] | None = None,
    include_visite_dettaglio: bool = False,
    oggi: date | None = None,
) -> dict[int, dict[str, Any]]:
    """Libretto di più persone con un numero di query costante.

    Stessa struttura di :func:`libretto` per ogni ``legacy_id``. È la forma che
    serve alla vista generale (tutto il personale in una schermata): chiamare la
    versione singola in un ciclo farebbe una manciata di query a testa.
    """
    ids = [int(i) for i in legacy_ids if int(i or 0) > 0]
    if not ids:
        return {}
    oggi = oggi or timezone.localdate()

    dettagli = mansionario.requisiti_dipendenti_dettaglio(
        ids, mansioni_per_legacy=mansioni_per_legacy, aree_per_legacy=aree_per_legacy
    )

    # Requisiti aggiuntivi dei processi qualificati (MOD.128): stessa somma che
    # fa il semaforo di conformità, così le due viste non divergono mai.
    try:
        from .mpq_idoneita import requisiti_processo_dettaglio
        processi = requisiti_processo_dettaglio(ids)
    except Exception:
        processi = {}

    requisiti_per_legacy: dict[int, dict[str, list]] = {}
    origini_per_legacy: dict[int, dict] = {}
    for legacy_id in ids:
        dettaglio = dettagli.get(legacy_id) or {
            "requisiti": mansionario.requisiti_vuoti(), "origini": {}, "mansione_nome": "",
        }
        requisiti = dict(dettaglio["requisiti"])
        origini = dict(dettaglio["origini"])
        proc = processi.get(legacy_id)
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
        requisiti_per_legacy[legacy_id] = requisiti
        origini_per_legacy[legacy_id] = origini

    consegne = _consegne_dpi_batch(ids)
    ultime_visite = _ultime_visite_batch(ids)
    corso_ids = {
        c.pk for requisiti in requisiti_per_legacy.values() for c in requisiti["corsi"]
    }
    deadlines = _deadline_batch(ids, corso_ids)
    qualifiche = _qualifiche_batch(ids)

    out: dict[int, dict[str, Any]] = {}
    for legacy_id in ids:
        requisiti = requisiti_per_legacy[legacy_id]
        origini = origini_per_legacy[legacy_id]

        righe_visite = _righe_visite(
            requisiti["visite"], legacy_id, origini, oggi, ultime_visite,
            include_dettaglio=include_visite_dettaglio,
        )
        righe_dpi = _righe_dpi(requisiti["dpi"], legacy_id, origini, oggi, consegne)
        righe_corsi = _righe_corsi(requisiti["corsi"], legacy_id, origini, oggi, deadlines)
        righe_qualifiche = _righe_qualifiche(qualifiche.get(legacy_id, []), oggi)

        # Il verdetto pesa solo gli **obblighi** di mansione: una qualifica scaduta
        # che nessun requisito impone non rende la persona non idonea.
        righe_obbligo = righe_visite + righe_dpi + righe_corsi
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

        out[legacy_id] = {
            "mansione_nome": (dettagli.get(legacy_id) or {}).get("mansione_nome", ""),
            "fattori": requisiti["fattori"],
            "piani": requisiti["piani"],
            "sezioni": _sezioni(righe_visite, righe_dpi, righe_corsi, righe_qualifiche),
            "righe": righe_obbligo + righe_qualifiche,
            "righe_obbligo": righe_obbligo,
            "conteggi": conteggi,
            "verdetto": verdetto,
            "verdetto_label": VERDETTO_LABEL.get(verdetto, "—"),
            "criticita": criticita,
            "aggiornato_al": oggi,
        }
    return out


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
    return libretto_batch(
        [legacy_id],
        mansioni_per_legacy=({int(legacy_id): mansione_nome}
                             if mansione_nome is not None else None),
        aree_per_legacy=({int(legacy_id): area_id} if area_id is not None else None),
        include_visite_dettaglio=include_visite_dettaglio,
    )[int(legacy_id)]


# ---------------------------------------------------------------------------
# Quadro generale — la stessa lista per la pagina, il PDF e l'Excel
# ---------------------------------------------------------------------------

DOMINIO_LABEL = {
    "visite": "Sorveglianza sanitaria",
    "dpi": "DPI",
    "corsi": "Formazione",
}

VERDETTO_FILTRO_LABEL = {
    STATO_KO: "Non conformi",
    STATO_MANCANTE: "Incompleti",
    STATO_WARN: "Con scadenze imminenti",
    STATO_OK: "Conformi",
    ESITO_NA: "Senza requisiti",
}

_ORDINE_STATO = {STATO_KO: 0, STATO_MANCANTE: 1, STATO_WARN: 2, STATO_OK: 3}
_ORDINE_VERDETTO = {**_ORDINE_STATO, ESITO_NA: 4}


def quadro_generale(
    dip_rows,
    *,
    filtri: dict | None = None,
    include_visite_dettaglio: bool = False,
    mansioni_map: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Il quadro aziendale: persone, adempimenti e conteggi, già filtrati.

    Sede unica del filtro e dell'ordinamento della vista generale: la pagina, il
    PDF e l'Excel chiamano questa funzione, così il documento esportato non può
    dire una cosa diversa dallo schermo (è il documento che si porta a
    un'ispezione). ``dip_rows`` sono le righe legacy dei dipendenti attivi.

    ``filtri``: ``reparto``, ``mansione``, ``verdetto`` (esito persona),
    ``dominio`` e ``stato`` (questi ultimi due filtrano i singoli adempimenti).
    """
    filtri = filtri or {}
    f_reparto = (filtri.get("reparto") or "").strip()
    f_mansione = (filtri.get("mansione") or "").strip()
    f_verdetto = (filtri.get("verdetto") or "").strip()
    f_dominio = (filtri.get("dominio") or "").strip()
    f_stato = (filtri.get("stato") or "").strip()
    mansioni_map = mansioni_map or {}

    dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}
    mansioni_per_legacy = {
        legacy_id: str(dip.get("mansione") or "").strip()
        for legacy_id, dip in dip_map.items()
    }
    libretti = libretto_batch(
        list(dip_map.keys()),
        mansioni_per_legacy=mansioni_per_legacy,
        include_visite_dettaglio=include_visite_dettaglio,
    )

    persone: list[dict] = []
    adempimenti: list[dict] = []
    for legacy_id, dip in dip_map.items():
        reparto = str(dip.get("reparto") or "").strip()
        mansione_nome = mansioni_per_legacy.get(legacy_id, "")
        if f_reparto and reparto.casefold() != f_reparto.casefold():
            continue
        if f_mansione and mansione_nome.casefold() != f_mansione.casefold():
            continue
        dati = libretti.get(legacy_id)
        if not dati:
            continue
        if f_verdetto and dati["verdetto"] != f_verdetto:
            continue
        persona = {
            "legacy_id": legacy_id,
            "cognome": str(dip.get("cognome") or f"ID {legacy_id}").strip(),
            "nome": str(dip.get("nome") or "").strip(),
            "reparto": reparto,
            "mansione": mansione_nome,
            "mansione_id": mansioni_map.get(mansione_nome.casefold()),
        }
        persone.append({**persona, "libretto": dati})
        for riga in dati["righe_obbligo"]:
            if f_dominio and riga.dominio != f_dominio:
                continue
            if f_stato and riga.stato != f_stato:
                continue
            adempimenti.append({**persona, "riga": riga})

    persone.sort(key=lambda p: (
        _ORDINE_VERDETTO.get(p["libretto"]["verdetto"], 9),
        p["cognome"].casefold(), p["nome"].casefold(),
    ))
    adempimenti.sort(key=lambda a: (
        _ORDINE_STATO.get(a["riga"].stato, 9),
        a["riga"].data_scadenza or date.max,
        a["cognome"].casefold(), a["nome"].casefold(),
    ))

    # Le persone si contano per verdetto, gli adempimenti per stato: sono due
    # domande diverse ("chi è fermo?" / "quanto lavoro c'è?").
    tutti_obblighi = [r for p in persone for r in p["libretto"]["righe_obbligo"]]
    conta_stato = {
        stato: sum(1 for r in tutti_obblighi if r.stato == stato)
        for stato in (STATO_OK, STATO_WARN, STATO_KO, STATO_MANCANTE)
    }
    n_obblighi = len(tutti_obblighi)

    per_dominio = [
        {
            "chiave": chiave,
            "titolo": titolo,
            "totale": sum(1 for r in tutti_obblighi if r.dominio == chiave),
            **{
                stato: sum(
                    1 for r in tutti_obblighi if r.dominio == chiave and r.stato == stato
                )
                for stato in (STATO_OK, STATO_WARN, STATO_KO, STATO_MANCANTE)
            },
        }
        for chiave, titolo in (
            ("visite", "🏥 Sorveglianza sanitaria"),
            ("dpi", "🦺 DPI"),
            ("corsi", "📚 Formazione"),
        )
    ]

    return {
        "persone": persone,
        "adempimenti": adempimenti,
        "conta_stato": conta_stato,
        "n_obblighi": n_obblighi,
        "copertura": (
            round(100 * conta_stato[STATO_OK] / n_obblighi) if n_obblighi else 0
        ),
        "n_persone": len(persone),
        "n_persone_ko": sum(1 for p in persone if p["libretto"]["verdetto"] == STATO_KO),
        "n_persone_incomplete": sum(
            1 for p in persone if p["libretto"]["verdetto"] == STATO_MANCANTE
        ),
        "n_persone_ok": sum(
            1 for p in persone
            if p["libretto"]["verdetto"] in (STATO_OK, STATO_WARN)
        ),
        "per_dominio": per_dominio,
        "reparti": sorted({p["reparto"] for p in persone if p["reparto"]}),
        "mansioni": sorted({p["mansione"] for p in persone if p["mansione"]}),
    }


def descrizione_filtri(filtri: dict | None) -> str:
    """Filtri attivi in chiaro — finisce in testa al PDF e nell'Excel."""
    filtri = filtri or {}
    parti: list[str] = []
    if (filtri.get("reparto") or "").strip():
        parti.append(f"Reparto: {filtri['reparto'].strip()}")
    if (filtri.get("mansione") or "").strip():
        parti.append(f"Mansione: {filtri['mansione'].strip()}")
    verdetto = (filtri.get("verdetto") or "").strip()
    if verdetto in VERDETTO_FILTRO_LABEL:
        parti.append(f"Esito: {VERDETTO_FILTRO_LABEL[verdetto]}")
    dominio = (filtri.get("dominio") or "").strip()
    if dominio in DOMINIO_LABEL:
        parti.append(f"Ambito: {DOMINIO_LABEL[dominio]}")
    stato = (filtri.get("stato") or "").strip()
    if stato in STATO_LABEL:
        parti.append(f"Stato: {STATO_LABEL[stato]}")
    return " · ".join(parti)
