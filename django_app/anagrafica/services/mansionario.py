"""Resolver dei requisiti delle mansioni di rischio e di una persona.

Le mansioni di rischio sono il catalogo ``Mansione`` (DVR e medico competente).
I requisiti di una mansione di rischio (DPI, visite mediche e formazione) sono
l'**unione** di:

1. requisiti assegnati **direttamente** (``dpi_richiesti``, ``visite_richieste``
   e ``TrainingRequirementRule`` con ``mansione`` valorizzata);
2. requisiti **ereditati** dai ``FattoreRischio`` a cui la mansione è esposta
   (``EsposizioneRischio`` attiva): ``categorie_dpi``, ``tipi_visita`` del
   fattore e i corsi delle ``CategoriaCorso`` collegate al fattore.

Le mansioni di rischio di una **persona** sono quella scritta in anagrafica
(campo legacy ``mansione``, per nome) più quelle ricavate dalle mansioni che
svolge (Mansionario: colonne della skill matrix con le loro mansioni di
rischio), più le aggiunte individuali, meno le esclusioni individuali. Nessuna
fonte toglie ciò che dà l'anagrafica, salvo un'esclusione individuale motivata.

L'accesso ai modelli ``dpi`` è **difensivo**: se il modulo non è migrato i DPI
risultano semplicemente vuoti (stesso pattern di ``conformita``/``onboarding``).
"""

from __future__ import annotations

from typing import Any, Iterable

from django.utils import timezone

from ..models import Mansione
from ..models_formazione import TrainingCourse, TrainingRequirementRule


def requisiti_vuoti() -> dict[str, list]:
    return {"dpi": [], "visite": [], "corsi": [], "piani": [], "fattori": []}


def _mansioni_prefetch():
    """Queryset Mansione con i prefetch necessari a risolvere i requisiti."""
    return Mansione.objects.prefetch_related(
        "dpi_richiesti",
        "visite_richieste",
        "esposizioni_rischio__fattore__tipi_visita",
        "esposizioni_rischio__fattore__categorie_dpi",
        "esposizioni_rischio__fattore__categorie_corso",
    )


def _dedup(seq: Iterable[Any]) -> list[Any]:
    out, seen = [], set()
    for obj in seq:
        pk = getattr(obj, "pk", obj)
        if pk not in seen:
            seen.add(pk)
            out.append(obj)
    return out


def _corsi_per_categoria(categoria_ids: set[int]) -> dict[int, list[TrainingCourse]]:
    """Corsi attivi raggruppati per categoria (per derivare i corsi dai fattori)."""
    out: dict[int, list[TrainingCourse]] = {}
    if categoria_ids:
        for corso in (
            TrainingCourse.objects
            .filter(categoria_id__in=categoria_ids, is_active=True)
            .select_related("piano")
        ):
            out.setdefault(corso.categoria_id, []).append(corso)
    return out


def _requisiti_da_fattori(fattori, corsi_per_categoria) -> dict[str, list]:
    """DPI/visite/corsi/fattori derivati da una lista di FattoreRischio attivi.

    Helper condiviso fra i resolver mansione e dipendente: unica
    implementazione fattore→requisiti.
    """
    dpi, visite, corsi, out_fattori = [], [], [], []
    for fattore in fattori:
        if fattore is None or not fattore.is_active:
            continue
        out_fattori.append(fattore)
        visite.extend(fattore.tipi_visita.all())
        try:
            dpi.extend(fattore.categorie_dpi.all())
        except Exception:
            pass
        for categoria in fattore.categorie_corso.all():
            corsi.extend(corsi_per_categoria.get(categoria.pk, []))
    return {"dpi": dpi, "visite": visite, "corsi": corsi, "fattori": out_fattori}


def _unisci(*parziali: dict[str, list]) -> dict[str, list]:
    out = requisiti_vuoti()
    for parziale in parziali:
        for dominio in out:
            out[dominio].extend(parziale.get(dominio, []))
    return {dominio: _dedup(voci) for dominio, voci in out.items()}


def _regole_obbligo(ids: list[int]) -> dict[int, list[TrainingRequirementRule]]:
    """Regole formative obbligatorie attive per mansione di rischio."""
    out: dict[int, list[TrainingRequirementRule]] = {}
    if ids:
        for rule in (
            TrainingRequirementRule.objects
            .filter(mansione_id__in=ids, is_active=True, is_mandatory=True)
            .select_related("corso", "piano")
        ):
            out.setdefault(rule.mansione_id, []).append(rule)
    return out


def _da_regole(regole) -> dict[str, list]:
    corsi, piani = [], []
    for rule in regole:
        if rule.corso_id and rule.corso:
            corsi.append(rule.corso)
        elif rule.piano_id and rule.piano:
            piani.append(rule.piano)
    return {"corsi": corsi, "piani": piani}


def _profilo(mansione: Mansione, corsi_per_categoria) -> dict[str, list]:
    """Profilo della mansione di rischio: DPI, visite e fattori esposti."""
    diretti = {"visite": list(mansione.visite_richieste.all())}
    try:
        diretti["dpi"] = list(mansione.dpi_richiesti.all())
    except Exception:
        diretti["dpi"] = []
    fattori_esposti = [
        esp.fattore for esp in mansione.esposizioni_rischio.all()
        if esp.is_active and esp.fattore and esp.fattore.is_active
    ]
    return _unisci(diretti, _requisiti_da_fattori(fattori_esposti, corsi_per_categoria))


def _categorie_fattori(mansioni: list[Mansione]) -> set[int]:
    return {
        categoria.pk
        for mansione in mansioni
        for esp in mansione.esposizioni_rischio.all()
        if esp.is_active and esp.fattore and esp.fattore.is_active
        for categoria in esp.fattore.categorie_corso.all()
    }


def _requisiti_batch(mansioni: list[Mansione]) -> dict[int, dict[str, list]]:
    """Requisiti completi di più mansioni di rischio: {mansione_id: req}."""
    if not mansioni:
        return {}
    corsi_per_categoria = _corsi_per_categoria(_categorie_fattori(mansioni))
    regole = _regole_obbligo([m.pk for m in mansioni])
    return {
        m.pk: _unisci(_da_regole(regole.get(m.pk, [])), _profilo(m, corsi_per_categoria))
        for m in mansioni
    }


def requisiti_mansioni_rischio(ids: Iterable[int]) -> dict[int, dict[str, list]]:
    """Requisiti per più mansioni di rischio (catalogo ``Mansione``), in batch."""
    voluti = {int(i) for i in ids if i}
    if not voluti:
        return {}
    return _requisiti_batch(list(_mansioni_prefetch().filter(pk__in=voluti)))


def requisiti_mansione(mansione: "Mansione | int") -> dict[str, list]:
    """Requisiti completi di una singola mansione di rischio (profilo + regole)."""
    mansione_id = mansione.pk if isinstance(mansione, Mansione) else int(mansione)
    return requisiti_mansioni_rischio([mansione_id]).get(mansione_id, requisiti_vuoti())


def nomi_precedenti(mansione: Mansione) -> list[str]:
    return [r.strip() for r in (mansione.nomi_precedenti or "").splitlines() if r.strip()]


def _indice_nomi(mansioni: Iterable[Mansione]) -> dict[str, Mansione]:
    """Nome minuscolo -> mansione. I nomi attuali vincono sui nomi precedenti."""
    indice: dict[str, Mansione] = {}
    mansioni = list(mansioni)
    for m in mansioni:
        for vecchio in nomi_precedenti(m):
            indice.setdefault(vecchio.casefold(), m)
    for m in mansioni:
        indice[m.nome.strip().casefold()] = m
    return indice


def _mansioni_per_nome(nomi: Iterable[str]) -> dict[str, Mansione]:
    voluti = {str(n).strip().casefold() for n in nomi if str(n or "").strip()}
    if not voluti:
        return {}
    indice = _indice_nomi(_mansioni_prefetch().filter(is_active=True))
    return {nome: indice[nome] for nome in voluti if nome in indice}


def mansione_per_nome(nome: str, *, solo_attive: bool = False) -> Mansione | None:
    """Mansione di rischio dal testo «mansione» dell'anagrafica, anche se rinominata.

    Unico punto di ricerca per nome: le attive prima, poi le spente.
    """
    nome = (nome or "").strip().casefold()
    if not nome:
        return None
    qs = Mansione.objects.all() if not solo_attive else Mansione.objects.filter(is_active=True)
    candidate = list(qs.order_by("-is_active", "pk"))
    attive = [m for m in candidate if m.is_active]
    return _indice_nomi(attive).get(nome) or _indice_nomi(candidate).get(nome)


def rinomina(mansione: Mansione, nuovo_nome: str) -> bool:
    """Rinomina conservando il vecchio nome fra i precedenti (le persone restano legate)."""
    nuovo_nome = " ".join((nuovo_nome or "").split())[:100]
    if not nuovo_nome:
        raise ValueError("Il nome della mansione è obbligatorio.")
    vecchio = mansione.nome
    if vecchio == nuovo_nome:
        return False
    if Mansione.objects.filter(nome__iexact=nuovo_nome).exclude(pk=mansione.pk).exists():
        raise ValueError(f"Esiste già una mansione «{nuovo_nome}».")
    righe = [r for r in nomi_precedenti(mansione) if r.casefold() != nuovo_nome.casefold()]
    if vecchio.casefold() != nuovo_nome.casefold() and vecchio.casefold() not in {r.casefold() for r in righe}:
        righe.append(vecchio)
    mansione.nome = nuovo_nome
    mansione.nomi_precedenti = "\n".join(righe)
    return True


def requisiti_per_nome(nomi: Iterable[str]) -> dict[str, dict[str, list]]:
    """Requisiti per più mansioni di rischio, mappati per **nome minuscolo**.

    Numero di query costante: usato dall'onboarding (mansione ipotizzata) e, con
    i nomi di :func:`nomi_mansioni_rischio`, da chi lavora per persona.
    """
    per_nome = _mansioni_per_nome(nomi)
    if not per_nome:
        return {}
    req = _requisiti_batch(list(per_nome.values()))
    return {nome: req[m.pk] for nome, m in per_nome.items()}


def requisiti_per_nome_mansione(nome: str) -> dict[str, list]:
    """Requisiti per una mansione di rischio individuata per nome (case-insensitive)."""
    return requisiti_per_nome([nome]).get(
        str(nome or "").strip().casefold(), requisiti_vuoti()
    )


def _mansioni_nome_legacy(legacy_ids: Iterable[int]) -> dict[int, str]:
    """Nome mansione dalle righe legacy anagrafica, per più dipendenti (1 fetch)."""
    voluti = {int(i) for i in legacy_ids}
    out: dict[int, str] = {}
    if not voluti:
        return out
    try:
        from core.legacy_anagrafica import fetch_anagrafica_rows
        for row in fetch_anagrafica_rows(deduplicate=True):
            rid = int(row.get("id") or 0)
            if rid in voluti:
                out[rid] = str(row.get("mansione") or "").strip()
    except Exception:
        pass
    return out


def _mansione_nome_legacy(legacy_id: int) -> str:
    """Nome mansione dalla riga legacy anagrafica (campo stringa ``mansione``)."""
    return _mansioni_nome_legacy([legacy_id]).get(int(legacy_id), "")


def mansioni_rischio_ricavate(legacy_ids: Iterable[int]) -> dict[int, list[tuple[Mansione, list[str]]]]:
    """Mansioni di rischio che vengono dalle mansioni svolte (Mansionario).

    Per ogni persona: ``[(Mansione di rischio, [nomi delle mansioni che la
    generano]), ...]``. Contano le mansioni attive su cui la persona è in lista,
    a qualsiasi livello: chi è in formazione è esposto come gli altri.
    """
    from ..models_skillmatrix import AbilitazioneMacchina

    ids = {int(i) for i in legacy_ids if int(i or 0) > 0}
    out: dict[int, list[tuple[Mansione, list[str]]]] = {}
    if not ids:
        return out
    per_persona: dict[int, dict[int, tuple[Mansione, list[str]]]] = {}
    for ab in (
        AbilitazioneMacchina.objects
        .filter(legacy_anagrafica_id__in=ids, in_lista=True, competenza__isnull=False,
                competenza__attiva=True)
        .select_related("competenza__asset")
        .prefetch_related("competenza__mansioni_rischio")
    ):
        nome_mansione = ab.competenza.nome
        voci = per_persona.setdefault(ab.legacy_anagrafica_id, {})
        for m in ab.competenza.mansioni_rischio.all():
            if not m.is_active:
                continue
            _m, da = voci.setdefault(m.pk, (m, []))
            if nome_mansione not in da:
                da.append(nome_mansione)
    for lid, voci in per_persona.items():
        out[lid] = sorted(voci.values(), key=lambda v: v[0].nome.casefold())
    return out


def nomi_mansioni_rischio(
    legacy_ids: Iterable[int], *, mansioni_per_legacy: dict[int, str] | None = None, data=None,
) -> dict[int, list[str]]:
    """Nomi delle mansioni di rischio effettive di ogni persona.

    Mansione di rischio scritta in anagrafica (quella del medico competente) +
    quelle ricavate dalle mansioni svolte + aggiunte individuali − esclusioni
    individuali. Per i moduli che lavorano per nome (schede di sicurezza,
    formazione, DPI).
    """
    ids = [int(i) for i in legacy_ids if int(i or 0) > 0]
    if not ids:
        return {}
    testo = dict(mansioni_per_legacy or {})
    mancanti = [i for i in ids if i not in testo]
    if mancanti:
        testo.update(_mansioni_nome_legacy(mancanti))
    ricavate = mansioni_rischio_ricavate(ids)
    override = override_validi(ids, data or timezone.localdate())
    out: dict[int, list[str]] = {}
    for lid in ids:
        nomi: list[str] = []
        visti: set[str] = set()
        candidati = [testo.get(lid, "")] + [m.nome for m, _da in ricavate.get(lid, [])]
        esclusi: set[str] = set()
        for o in override.get(lid, []):
            if o.azione == o.AZIONE_AGGIUNGI and o.mansione_rischio.is_active:
                candidati.append(o.mansione_rischio.nome)
            elif o.azione == o.AZIONE_ESCLUDI:
                esclusi.add(o.mansione_rischio.nome.strip().casefold())
        for nome in candidati:
            nome = (nome or "").strip()
            if nome and nome.casefold() not in visti and nome.casefold() not in esclusi:
                visti.add(nome.casefold())
                nomi.append(nome)
        out[lid] = nomi
    return out


def requisiti_dipendente(
    legacy_id: int, *, mansione_nome: str | None = None, area_id: int | None = None,
    data=None,
) -> dict[str, list]:
    """Requisiti effettivi di un dipendente.

    Unione, con dedup, di: mansioni di rischio della persona (anagrafica,
    mansioni svolte, aggiunte individuali, meno le esclusioni), esposizioni di
    **area** e esposizioni **dirette**. ``mansione_nome`` / ``area_id``
    opzionali: se assenti sono risolti dal DB. Ritorna
    ``{dpi, visite, corsi, piani, fattori}``.
    """
    return requisiti_dipendente_dettaglio(
        legacy_id, mansione_nome=mansione_nome, area_id=area_id, data=data,
    )["requisiti"]


def requisiti_dipendente_dettaglio(
    legacy_id: int, *, mansione_nome: str | None = None, area_id: int | None = None,
    data=None,
) -> dict[str, Any]:
    """Come :func:`requisiti_dipendente`, ma dice **da dove viene** ogni requisito.

    Il libretto sanitario deve poter rispondere a "perché questo DPI è dovuto?":
    senza l'origine un elenco di obblighi non è verificabile da chi lo legge (né
    in un'ispezione). Ritorna::

        {
          "requisiti": {dpi, visite, corsi, piani, fattori},   # come sopra
          "origini": {("dpi", pk): ["Mansione di rischio «Saldatore» (anagrafica)", ...], ...},
          "mansioni_rischio": [{"mansione_rischio", "origine", "override", "da"}, ...],
          "mansione_nome": "...",
          "area_id": 12 | None,
        }

    Le chiavi di ``origini`` sono ``(dominio, pk)`` con dominio in
    ``dpi``/``visite``/``corsi``/``piani``/``fattori``.
    """
    return requisiti_dipendenti_dettaglio(
        [legacy_id],
        mansioni_per_legacy=({int(legacy_id): mansione_nome}
                             if mansione_nome is not None else None),
        aree_per_legacy=({int(legacy_id): area_id} if area_id is not None else None),
        data=data,
    )[int(legacy_id)]


def requisiti_dipendenti_dettaglio(
    legacy_ids: Iterable[int],
    *,
    mansioni_per_legacy: dict[int, str] | None = None,
    aree_per_legacy: dict[int, int | None] | None = None,
    data=None,
) -> dict[int, dict[str, Any]]:
    """Versione batch di :func:`requisiti_dipendente_dettaglio`.

    Numero di query costante rispetto al numero di dipendenti: serve alla vista
    generale del libretto sanitario, che risolve i requisiti di tutto il
    personale attivo in una schermata sola. Ciò che non viene passato
    (``mansioni_per_legacy`` / ``aree_per_legacy``) è risolto con una query
    sola per l'intero insieme.

    Mansioni di rischio della persona (Mansionario, fasi 5-6): quella scritta in
    **anagrafica** (del medico competente), quelle **ricavate dalle mansioni
    svolte** e le **aggiunte individuali**, meno le **esclusioni individuali**.
    Origine di ogni voce in ``mansioni_rischio[i]["origine"]``:
    ``ANAGRAFICA`` / ``MANSIONARIO`` / ``OVERRIDE``.
    """
    from ..models_rischi import EsposizioneRischio

    ids = [int(i) for i in legacy_ids if int(i or 0) > 0]
    if not ids:
        return {}

    mansioni = dict(mansioni_per_legacy or {})
    aree: dict[int, int | None] = dict(aree_per_legacy or {})

    mancanti_area = [i for i in ids if i not in aree]
    if mancanti_area:
        from ..models import DipendenteAnagraficaAziendale
        trovate = dict(
            DipendenteAnagraficaAziendale.objects
            .filter(legacy_anagrafica_id__in=mancanti_area)
            .values_list("legacy_anagrafica_id", "area_aziendale_id")
        )
        for legacy_id in mancanti_area:
            aree[legacy_id] = trovate.get(legacy_id)

    mancanti_mansione = [i for i in ids if i not in mansioni]
    if mancanti_mansione:
        mansioni.update(_mansioni_nome_legacy(mancanti_mansione))

    giorno = data or timezone.localdate()
    ricavate = mansioni_rischio_ricavate(ids)
    override_per_dip = override_validi(ids, giorno)

    # Tutte le mansioni di rischio coinvolte, risolte in batch una volta sola.
    per_nome = _mansioni_per_nome({n for n in mansioni.values() if str(n or "").strip()})
    coinvolte_ids = {m.pk for m in per_nome.values()}
    coinvolte_ids |= {m.pk for voci in ricavate.values() for m, _da in voci}
    coinvolte_ids |= {o.mansione_rischio_id for gruppo in override_per_dip.values() for o in gruppo
                      if o.azione == o.AZIONE_AGGIUNGI}
    req_per_mansione = requisiti_mansioni_rischio(coinvolte_ids)

    # Esposizioni di area e dirette, in due query per tutti.
    esposizioni = (
        EsposizioneRischio.objects
        .filter(is_active=True)
        .select_related("fattore")
        .prefetch_related(
            "fattore__tipi_visita", "fattore__categorie_dpi", "fattore__categorie_corso",
        )
    )
    area_ids = {a for a in aree.values() if a}
    per_area: dict[int, list] = {}
    if area_ids:
        for esp in esposizioni.filter(area_id__in=area_ids):
            per_area.setdefault(esp.area_id, []).append(esp)
    per_dipendente: dict[int, list] = {}
    for esp in esposizioni.filter(legacy_anagrafica_id__in=ids):
        per_dipendente.setdefault(esp.legacy_anagrafica_id, []).append(esp)

    # Un'unica risoluzione categoria corso → corsi per tutti i fattori coinvolti.
    categoria_ids: set[int] = set()
    for gruppo in list(per_area.values()) + list(per_dipendente.values()):
        for esp in gruppo:
            if esp.fattore and esp.fattore.is_active:
                for categoria in esp.fattore.categorie_corso.all():
                    categoria_ids.add(categoria.pk)
    corsi_per_categoria = _corsi_per_categoria(categoria_ids)

    out: dict[int, dict[str, Any]] = {}
    for legacy_id in ids:
        origini: dict[tuple[str, Any], list[str]] = {}
        # Origine strutturata (per il piano di cambio mansione): la prima fonte
        # che porta il requisito, con la mansione di rischio / l'override.
        origini_strutturate: dict[tuple[str, Any], dict[str, Any]] = {}
        parziali: list[dict[str, list]] = []

        def _traccia(parziale: dict[str, list], etichetta: str, origine: dict[str, Any]) -> None:
            parziali.append(parziale)
            for dominio, voci in parziale.items():
                for obj in voci:
                    chiave = (dominio, getattr(obj, "pk", obj))
                    voci_origine = origini.setdefault(chiave, [])
                    if etichetta not in voci_origine:
                        voci_origine.append(etichetta)
                    origini_strutturate.setdefault(chiave, origine)

        nome = str(mansioni.get(legacy_id) or "").strip()
        override = override_per_dip.get(legacy_id, [])
        esclusi = {o.mansione_rischio_id: o for o in override if o.azione == o.AZIONE_ESCLUDI}

        # Candidate in ordine: anagrafica, mansioni svolte, aggiunte individuali.
        candidate: list[dict[str, Any]] = []
        principale = per_nome.get(nome.casefold()) if nome else None
        if principale is not None:
            candidate.append({"mansione_rischio": principale, "origine": "ANAGRAFICA",
                              "override": None, "da": []})
        for m, da in ricavate.get(legacy_id, []):
            candidate.append({"mansione_rischio": m, "origine": "MANSIONARIO", "override": None, "da": da})
        for o in override:
            if o.azione == o.AZIONE_AGGIUNGI and o.mansione_rischio.is_active:
                candidate.append({"mansione_rischio": o.mansione_rischio, "origine": "OVERRIDE",
                                  "override": o, "da": []})

        effettive: list[dict[str, Any]] = []
        escluse: list[dict[str, Any]] = []
        presenti: dict[int, dict[str, Any]] = {}
        for c in candidate:
            m = c["mansione_rischio"]
            if m.pk in esclusi:
                if all(e["mansione_rischio"].pk != m.pk for e in escluse):
                    escluse.append({"mansione_rischio": m, "override": esclusi[m.pk]})
                continue
            if m.pk in presenti:
                # Stessa mansione di rischio da più fonti: una voce, con tutte le provenienze.
                for nome_mansione in c["da"]:
                    if nome_mansione not in presenti[m.pk]["da"]:
                        presenti[m.pk]["da"].append(nome_mansione)
                continue
            voce = dict(c, da=list(c["da"]))
            presenti[m.pk] = voce
            effettive.append(voce)

        for voce in effettive:
            m = voce["mansione_rischio"]
            if voce["origine"] == "OVERRIDE":
                o = voce["override"]
                etichetta = (f"Mansione di rischio «{m.nome}» (aggiunta individuale dal "
                             f"{o.data_inizio:%d/%m/%Y}: {o.motivo})")
                origine = {"tipo": "OVERRIDE", "mansione_rischio_id": m.pk, "override_id": o.pk}
            elif voce["origine"] == "MANSIONARIO":
                etichetta = f"Mansione di rischio «{m.nome}» (da mansione {', '.join(voce['da'])})"
                origine = {"tipo": "MANSIONE_RISCHIO", "mansione_rischio_id": m.pk}
            else:
                anche = f"; anche da mansione {', '.join(voce['da'])}" if voce["da"] else ""
                etichetta = f"Mansione di rischio «{m.nome}» (anagrafica{anche})"
                origine = {"tipo": "MANSIONE_RISCHIO", "mansione_rischio_id": m.pk}
            _traccia(req_per_mansione.get(m.pk, requisiti_vuoti()), etichetta, origine)

        gruppi = (
            (per_area.get(aree.get(legacy_id) or 0, []), "Area aziendale", "AREA"),
            (per_dipendente.get(legacy_id, []), "Esposizione diretta", "DIRETTA"),
        )
        for esposizioni_gruppo, etichetta, tipo in gruppi:
            _traccia(
                _requisiti_da_fattori([e.fattore for e in esposizioni_gruppo], corsi_per_categoria),
                etichetta, {"tipo": tipo},
            )

        out[legacy_id] = {
            "requisiti": _unisci(*parziali),
            "origini": origini,
            "origini_strutturate": origini_strutturate,
            "mansioni_rischio": effettive,
            "mansioni_rischio_escluse": escluse,
            "mansione_nome": nome,
            "area_id": aree.get(legacy_id),
        }
    return out


def override_validi(legacy_ids: Iterable[int], giorno) -> dict[int, list]:
    """Override individuali attivi e validi a ``giorno``, per dipendente."""
    from ..models_mansioni_rischio import DipendenteMansioneRischioOverride

    out: dict[int, list] = {}
    ids = [int(i) for i in legacy_ids]
    if not ids:
        return out
    for o in (
        DipendenteMansioneRischioOverride.objects
        .filter(legacy_anagrafica_id__in=ids, attivo=True, data_inizio__lte=giorno)
        .select_related("mansione_rischio")
        .order_by("legacy_anagrafica_id", "data_inizio", "pk")
    ):
        if o.data_fine is None or o.data_fine >= giorno:
            out.setdefault(o.legacy_anagrafica_id, []).append(o)
    return out
