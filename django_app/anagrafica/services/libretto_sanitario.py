"""Libretto sanitario aziendale — il fascicolo leggibile di una persona.

Risponde, in una pagina sola e in ordine di lettura, alla catena che oggi è
sparsa fra più schermate:

    fattori di rischio → mansione di rischio → mansione di lavoro della persona
    → requisiti dovuti (visite / DPI / formazione) → conforme o non conforme

Non introduce una seconda verità: visite e formazione arrivano dal motore unico
``services.requisiti`` (mansione e fattori di rischio, area, esposizioni dirette,
ruoli operativi, regole in vigore, protocollo sanitario dell'ultimo certificato,
processi qualificati; stato alla data; visite per famiglia con il ricalcolo
prudente della periodicità), i DPI dal resolver ``mansionario`` + processi, e lo
stato usa la stessa soglia di preavviso del semaforo di conformità.
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


def _righe_visite(voci, oggi: date, visite_db, *, include_dettaglio: bool) -> list[Riga]:
    righe: list[Riga] = []
    for v in voci:
        etichetta = v.tipo_da_mostrare.nome if include_dettaglio else "Visita medica richiesta"
        if v.ultima is None:
            righe.append(Riga(dominio="visite", nome=etichetta, stato=STATO_MANCANTE,
                              origini=list(v.origini), nota="Mai registrata"))
            continue
        stato, giorni = _stato_da_scadenza(v.scadenza, oggi)
        # Il giudizio di idoneità è il cuore del libretto, ma è un dato
        # sanitario: esce solo con il gate sorveglianza. Le prescrizioni no, mai.
        note = []
        visita = visite_db.get(v.visita_id)
        if include_dettaglio and visita is not None:
            note.append(visita.get_esito_display())
        if v.nota:
            note.append(v.nota if include_dettaglio
                        else "Scadenza anticipata: la mansione richiede una periodicità più stretta.")
        righe.append(Riga(
            dominio="visite", nome=etichetta, stato=stato, origini=list(v.origini),
            data_ultima=v.ultima, data_scadenza=v.scadenza, giorni=giorni, nota=" · ".join(note),
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


def _righe_corsi(voci) -> list[Riga]:
    righe: list[Riga] = []
    for v in voci:
        if v.stato == "MAI_FREQUENTATO":
            righe.append(Riga(dominio="corsi", nome=v.corso.titolo, stato=STATO_MANCANTE,
                              origini=list(v.origini), nota="Mai frequentato"))
            continue
        if v.stato == "SCADUTO":
            stato = STATO_KO
        elif v.stato in ("IN_SCADENZA_30", "IN_SCADENZA_90"):
            stato = STATO_WARN
        else:
            stato = STATO_OK
        righe.append(Riga(
            dominio="corsi", nome=v.corso.titolo, stato=stato, origini=list(v.origini),
            data_ultima=v.completato, data_scadenza=v.scadenza, giorni=v.giorni,
            nota="Una tantum" if v.stato == "UNA_TANTUM" else "",
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
    from dataclasses import replace

    from . import requisiti
    from .conformita import _persone, _voci_formazione, _voci_visite

    ids = [int(i) for i in legacy_ids if int(i or 0) > 0]
    if not ids:
        return {}
    oggi = oggi or timezone.localdate()

    ctx, richiesti = _persone(ids, mansioni_per_legacy)
    if aree_per_legacy:
        richiesti = {lid: replace(p, area_aziendale_id=aree_per_legacy.get(lid, p.area_aziendale_id))
                     for lid, p in richiesti.items()}
    corsi = _voci_formazione(ctx, richiesti)
    visite = _voci_visite(ctx, richiesti)
    visite_db = VisitaMedica.objects.in_bulk(
        [v.visita_id for elenco in visite.values() for v in elenco if v.visita_id])

    # DPI, fattori di rischio e piani: resolver della mansione + processi qualificati.
    dettagli = mansionario.requisiti_dipendenti_dettaglio(
        ids, mansioni_per_legacy={lid: p.mansione for lid, p in richiesti.items()},
        aree_per_legacy={lid: p.area_aziendale_id for lid, p in richiesti.items()},
    )
    try:
        from .mpq_idoneita import requisiti_processo_dettaglio
        processi = requisiti_processo_dettaglio(ids)
    except Exception:
        processi = {}
    consegne = _consegne_dpi_batch(ids)

    persone_q = {p.id: p for p in richiesti.values()}
    correnti, _sostituite = requisiti.qualifiche_correnti(ctx, DipendenteQualifica.objects.all(), persone_q)
    qualifiche_per_pid: dict[int, list] = {}
    for (pid, _tipo), q in sorted(correnti.items(), key=lambda kv: kv[1].tipo.nome.casefold()):
        qualifiche_per_pid.setdefault(pid, []).append(q)

    out: dict[int, dict[str, Any]] = {}
    for legacy_id in ids:
        dettaglio = dettagli.get(legacy_id) or {
            "requisiti": mansionario.requisiti_vuoti(), "origini": {}, "mansione_nome": "",
        }
        requisiti_m = dettaglio["requisiti"]
        origini = dict(dettaglio["origini"])
        dpi = list(requisiti_m.get("dpi") or [])
        proc = processi.get(legacy_id)
        if proc:
            for chiave, etichette in proc["origini"].items():
                voci_o = origini.setdefault(chiave, [])
                for etichetta in etichette:
                    if etichetta not in voci_o:
                        voci_o.append(etichetta)
            dpi = _dedup_pk(dpi + list(proc["requisiti"]["dpi"]))

        righe_visite = _righe_visite(visite.get(legacy_id, []), oggi, visite_db,
                                     include_dettaglio=include_visite_dettaglio)
        righe_dpi = _righe_dpi(dpi, legacy_id, origini, oggi, consegne)
        righe_corsi = _righe_corsi(corsi.get(legacy_id, []))
        righe_qualifiche = _righe_qualifiche(qualifiche_per_pid.get(richiesti[legacy_id].id, []), oggi)

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
            "mansione_nome": dettaglio.get("mansione_nome", "") or richiesti[legacy_id].mansione,
            "fattori": requisiti_m.get("fattori") or [],
            "piani": requisiti_m.get("piani") or [],
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
