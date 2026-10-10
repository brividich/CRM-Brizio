"""Resolver dei requisiti di una "mansione di rischio".

Unifica in un'unica fonte i requisiti che determinano l'idoneità alla mansione —
DPI, visite mediche e formazione — come **unione** di:

1. requisiti assegnati **direttamente** alla ``Mansione``
   (``dpi_richiesti``, ``visite_richieste`` e ``TrainingRequirementRule`` con
   ``mansione`` valorizzata);
2. requisiti **ereditati** dai ``FattoreRischio`` a cui la mansione è esposta
   (``EsposizioneRischio`` attiva): ``categorie_dpi``, ``tipi_visita`` del
   fattore e i corsi delle ``CategoriaCorso`` collegate al fattore.

Il dipendente è legato alla mansione **per nome** (campo legacy ``mansione``
stringa ↔ ``Mansione.nome`` unique), come già fa ``services.onboarding``.

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
        "link_rischio__mansione_rischio",
    )


def _mansioni_rischio_prefetch():
    from ..models_mansioni_rischio import MansioneRischio
    return MansioneRischio.objects.prefetch_related(
        "visite",
        "categorie_dpi",
        "fattori__tipi_visita",
        "fattori__categorie_dpi",
        "fattori__categorie_corso",
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

    Helper condiviso fra i resolver mansione, mansione di rischio e dipendente:
    unica implementazione fattore→requisiti.
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


def _regole_obbligo(campo: str, ids: list[int]) -> dict[int, list[TrainingRequirementRule]]:
    """Regole formative obbligatorie attive per target (``mansione`` o ``mansione_rischio``)."""
    out: dict[int, list[TrainingRequirementRule]] = {}
    if ids:
        for rule in (
            TrainingRequirementRule.objects
            .filter(**{f"{campo}_id__in": ids}, is_active=True, is_mandatory=True)
            .select_related("corso", "piano")
        ):
            out.setdefault(getattr(rule, f"{campo}_id"), []).append(rule)
    return out


def _da_regole(regole) -> dict[str, list]:
    corsi, piani = [], []
    for rule in regole:
        if rule.corso_id and rule.corso:
            corsi.append(rule.corso)
        elif rule.piano_id and rule.piano:
            piani.append(rule.piano)
    return {"corsi": corsi, "piani": piani}


def collegamenti_attivi(mansione: Mansione) -> list:
    """Mansioni di rischio attive collegate a una mansione (prefetch ``link_rischio``)."""
    return [
        link.mansione_rischio for link in mansione.link_rischio.all()
        if link.mansione_rischio and link.mansione_rischio.is_active
    ]


def requisiti_mansioni_rischio(ids: Iterable[int]) -> dict[int, dict[str, list]]:
    """Requisiti per più mansioni di rischio (batch): {mansione_rischio_id: req}.

    Fattori → visite/DPI/corsi, più visite e DPI del protocollo e le regole
    formative ``TrainingRequirementRule(mansione_rischio=...)``.
    """
    voluti = {int(i) for i in ids if i}
    if not voluti:
        return {}
    oggetti = list(_mansioni_rischio_prefetch().filter(pk__in=voluti))
    categoria_ids = {
        categoria.pk
        for mr in oggetti for fattore in mr.fattori.all() if fattore.is_active
        for categoria in fattore.categorie_corso.all()
    }
    corsi_per_categoria = _corsi_per_categoria(categoria_ids)
    regole = _regole_obbligo("mansione_rischio", [mr.pk for mr in oggetti])
    out: dict[int, dict[str, list]] = {}
    for mr in oggetti:
        diretti = {"visite": list(mr.visite.all())}
        try:
            diretti["dpi"] = list(mr.categorie_dpi.all())
        except Exception:
            diretti["dpi"] = []
        out[mr.pk] = _unisci(
            diretti,
            _requisiti_da_fattori(list(mr.fattori.all()), corsi_per_categoria),
            _da_regole(regole.get(mr.pk, [])),
        )
    return out


def _profilo_legacy(mansione: Mansione, corsi_per_categoria) -> dict[str, list]:
    """Requisiti dai campi DEPRECATI della mansione (ripiego senza collegamenti)."""
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


def _categorie_legacy(mansioni: list[Mansione]) -> set[int]:
    return {
        categoria.pk
        for mansione in mansioni
        for esp in mansione.esposizioni_rischio.all()
        if esp.is_active and esp.fattore and esp.fattore.is_active
        for categoria in esp.fattore.categorie_corso.all()
    }


def _profili(mansioni: list[Mansione]) -> dict[int, dict[str, Any]]:
    """Profilo scomposto di ogni mansione, per sapere da dove viene ogni requisito.

    ``{mansione_id: {"regole": req, "legacy": req | None,
    "rischio": [(MansioneRischio, req), ...]}}``. Una mansione con almeno un
    collegamento attivo a una mansione di rischio legge **solo** quelle; senza
    collegamenti legge i campi deprecati (``legacy``): finché la migrazione
    dati non è applicata il risultato non cambia.
    """
    # Una mansione con QUALSIASI collegamento (anche a una mansione di rischio
    # disattivata) è migrata: i campi deprecati non tornano in vigore.
    senza_link = [m for m in mansioni if not list(m.link_rischio.all())]
    corsi_per_categoria = _corsi_per_categoria(_categorie_legacy(senza_link))
    regole = _regole_obbligo("mansione", [m.pk for m in mansioni])
    per_mr = requisiti_mansioni_rischio(
        mr.pk for mansione in mansioni for mr in collegamenti_attivi(mansione)
    )
    out: dict[int, dict[str, Any]] = {}
    for mansione in mansioni:
        collegate = collegamenti_attivi(mansione)
        out[mansione.pk] = {
            "regole": _unisci(_da_regole(regole.get(mansione.pk, []))),
            "legacy": _profilo_legacy(mansione, corsi_per_categoria) if mansione in senza_link else None,
            "rischio": [(mr, per_mr.get(mr.pk, requisiti_vuoti())) for mr in collegate],
        }
    return out


def _componi(profilo: dict[str, Any]) -> dict[str, list]:
    return _unisci(
        profilo["regole"],
        profilo["legacy"] or {},
        *[req for _mr, req in profilo["rischio"]],
    )


def requisiti_mansione(mansione: "Mansione | int") -> dict[str, list]:
    """Requisiti completi di una singola mansione (mansioni di rischio + regole)."""
    mansione_id = mansione.pk if isinstance(mansione, Mansione) else int(mansione)
    obj = _mansioni_prefetch().filter(pk=mansione_id).first()
    if obj is None:
        return requisiti_vuoti()
    return _componi(_profili([obj])[obj.pk])


def requisiti_mansione_legacy(mansione: "Mansione | int") -> dict[str, list]:
    """Requisiti calcolati SOLO dai campi deprecati (verifica di equivalenza)."""
    mansione_id = mansione.pk if isinstance(mansione, Mansione) else int(mansione)
    obj = _mansioni_prefetch().filter(pk=mansione_id).first()
    if obj is None:
        return requisiti_vuoti()
    regole = _regole_obbligo("mansione", [obj.pk])
    return _unisci(
        _da_regole(regole.get(obj.pk, [])),
        _profilo_legacy(obj, _corsi_per_categoria(_categorie_legacy([obj]))),
    )


def _mansioni_per_nome(nomi: Iterable[str]) -> dict[str, Mansione]:
    voluti = {str(n).strip().casefold() for n in nomi if str(n or "").strip()}
    if not voluti:
        return {}
    return {
        m.nome.strip().casefold(): m
        for m in _mansioni_prefetch().filter(is_active=True)
        if m.nome.strip().casefold() in voluti
    }


def requisiti_per_nome(nomi: Iterable[str]) -> dict[str, dict[str, list]]:
    """Requisiti per più mansioni, mappati per **nome minuscolo**.

    Numero di query costante: usato dal report conformità e dall'onboarding.
    """
    per_nome = _mansioni_per_nome(nomi)
    if not per_nome:
        return {}
    profili = _profili(list(per_nome.values()))
    return {nome: _componi(profili[m.pk]) for nome, m in per_nome.items()}


def requisiti_per_nome_mansione(nome: str) -> dict[str, list]:
    """Requisiti per una mansione individuata per nome (case-insensitive)."""
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


def requisiti_dipendente(
    legacy_id: int, *, mansione_nome: str | None = None, area_id: int | None = None,
    data=None,
) -> dict[str, list]:
    """Requisiti effettivi di un dipendente ("mansione di rischio" a vista).

    Unione di tre fonti, con dedup:
      1) requisiti della **mansione lavorativa** (resolver esistente, per nome);
      2) esposizioni di **area** (``EsposizioneRischio.area`` = area del dipendente);
      3) esposizioni **dirette** (``EsposizioneRischio.legacy_anagrafica_id``).

    ``mansione_nome`` / ``area_id`` opzionali: se assenti sono risolti dal DB
    (``DipendenteAnagraficaAziendale`` per l'area; riga legacy per la mansione).
    Passarli evita il fetch quando il chiamante li ha già. Ritorna
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
          "origini": {("dpi", pk): ["Mansione «Saldatore»", ...], ...},
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

    # Fonte 1: mansione lavorativa → regole + mansioni di rischio collegate
    # (o profilo legacy se la mansione non ha collegamenti).
    per_nome = _mansioni_per_nome({n for n in mansioni.values() if str(n or "").strip()})
    profili = _profili(list(per_nome.values())) if per_nome else {}

    # Fonte 1-bis: override individuali validi alla data.
    giorno = data or timezone.localdate()
    override_per_dip = override_validi(ids, giorno)
    aggiunte_ids = {
        o.mansione_rischio_id for gruppo in override_per_dip.values() for o in gruppo
        if o.azione == o.AZIONE_AGGIUNGI
    }
    req_aggiunte = requisiti_mansioni_rischio(aggiunte_ids)

    # Fonti 2+3: esposizioni di area + dirette, in due query per tutti.
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
        mansione = per_nome.get(nome.casefold()) if nome else None
        profilo = profili.get(mansione.pk) if mansione is not None else None
        etichetta_mansione = f"Mansione «{nome}»" if nome else "Mansione"

        override = override_per_dip.get(legacy_id, [])
        esclusi = {o.mansione_rischio_id: o for o in override if o.azione == o.AZIONE_ESCLUDI}
        effettive: list[dict[str, Any]] = []
        escluse: list[dict[str, Any]] = []

        if profilo is not None:
            _traccia(profilo["regole"], etichetta_mansione, {"tipo": "MANSIONE"})
            if profilo["legacy"] is not None:
                _traccia(profilo["legacy"], etichetta_mansione, {"tipo": "MANSIONE"})
            for mr, req in profilo["rischio"]:
                if mr.pk in esclusi:
                    escluse.append({"mansione_rischio": mr, "override": esclusi[mr.pk]})
                    continue
                effettive.append({"mansione_rischio": mr, "origine": "MANSIONE", "override": None})
                _traccia(req, f"Mansione di rischio «{mr.nome}» (da mansione «{nome}»)",
                         {"tipo": "MANSIONE_RISCHIO", "mansione_rischio_id": mr.pk})
        presenti = {e["mansione_rischio"].pk for e in effettive}
        for o in override:
            if o.azione != o.AZIONE_AGGIUNGI or o.mansione_rischio_id in presenti:
                continue
            mr = o.mansione_rischio
            if not mr.is_active:
                continue
            presenti.add(mr.pk)
            effettive.append({"mansione_rischio": mr, "origine": "OVERRIDE", "override": o})
            _traccia(req_aggiunte.get(mr.pk, requisiti_vuoti()),
                     f"Mansione di rischio «{mr.nome}» (aggiunta individuale dal {o.data_inizio:%d/%m/%Y}: {o.motivo})",
                     {"tipo": "OVERRIDE", "mansione_rischio_id": mr.pk, "override_id": o.pk})

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
