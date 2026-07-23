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

    Helper condiviso fra il resolver mansione (``_resolve``) e il resolver
    dipendente (``requisiti_dipendente``): unica implementazione fattore→requisiti.
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


def _resolve(
    mansioni: list[Mansione],
    *,
    corsi_per_categoria: dict[int, list[TrainingCourse]],
    rules_per_mansione: dict[int, list[TrainingRequirementRule]],
) -> dict[int, dict[str, list]]:
    """Risolve i requisiti per Mansione già prefetchate. Ritorna {mansione_id: req}."""
    out: dict[int, dict[str, list]] = {}
    for mansione in mansioni:
        dpi: list = []
        visite: list = []
        corsi: list = []
        piani: list = []
        fattori: list = []

        # 1) requisiti diretti sulla mansione
        try:
            dpi.extend(mansione.dpi_richiesti.all())
        except Exception:
            pass
        visite.extend(mansione.visite_richieste.all())

        # 2) requisiti ereditati dai fattori di rischio esposti (helper condiviso)
        fattori_esposti = [
            esp.fattore for esp in mansione.esposizioni_rischio.all()
            if esp.is_active and esp.fattore and esp.fattore.is_active
        ]
        parziale = _requisiti_da_fattori(fattori_esposti, corsi_per_categoria)
        dpi.extend(parziale["dpi"])
        visite.extend(parziale["visite"])
        corsi.extend(parziale["corsi"])
        fattori.extend(parziale["fattori"])

        # 3) formazione obbligatoria diretta (corso o piano)
        for rule in rules_per_mansione.get(mansione.pk, []):
            if rule.corso_id and rule.corso:
                corsi.append(rule.corso)
            elif rule.piano_id and rule.piano:
                piani.append(rule.piano)

        out[mansione.pk] = {
            "dpi": _dedup(dpi),
            "visite": _dedup(visite),
            "corsi": _dedup(corsi),
            "piani": _dedup(piani),
            "fattori": _dedup(fattori),
        }
    return out


def _supplementi(mansioni: list[Mansione]) -> tuple[dict[int, list], dict[int, list]]:
    """Query batch ausiliarie: corsi per categoria e regole per mansione."""
    categoria_ids: set[int] = set()
    for mansione in mansioni:
        for esp in mansione.esposizioni_rischio.all():
            if esp.is_active and esp.fattore and esp.fattore.is_active:
                for categoria in esp.fattore.categorie_corso.all():
                    categoria_ids.add(categoria.pk)

    corsi_per_categoria = _corsi_per_categoria(categoria_ids)

    mansione_ids = [m.pk for m in mansioni]
    rules_per_mansione: dict[int, list[TrainingRequirementRule]] = {}
    if mansione_ids:
        for rule in (
            TrainingRequirementRule.objects
            .filter(mansione_id__in=mansione_ids, is_active=True, is_mandatory=True)
            .select_related("corso", "piano")
        ):
            rules_per_mansione.setdefault(rule.mansione_id, []).append(rule)

    return corsi_per_categoria, rules_per_mansione


def requisiti_mansione(mansione: "Mansione | int") -> dict[str, list]:
    """Requisiti completi di una singola mansione (diretti + ereditati)."""
    mansione_id = mansione.pk if isinstance(mansione, Mansione) else int(mansione)
    obj = _mansioni_prefetch().filter(pk=mansione_id).first()
    if obj is None:
        return requisiti_vuoti()
    corsi_per_categoria, rules_per_mansione = _supplementi([obj])
    return _resolve(
        [obj],
        corsi_per_categoria=corsi_per_categoria,
        rules_per_mansione=rules_per_mansione,
    )[obj.pk]


def requisiti_per_nome(nomi: Iterable[str]) -> dict[str, dict[str, list]]:
    """Requisiti per più mansioni, mappati per **nome minuscolo**.

    Numero di query costante: usato dal report conformità e dall'onboarding.
    """
    voluti = {str(n).strip().casefold() for n in nomi if str(n or "").strip()}
    if not voluti:
        return {}
    mansioni = [
        m for m in _mansioni_prefetch().filter(is_active=True)
        if m.nome.strip().casefold() in voluti
    ]
    if not mansioni:
        return {}
    corsi_per_categoria, rules_per_mansione = _supplementi(mansioni)
    per_id = _resolve(
        mansioni,
        corsi_per_categoria=corsi_per_categoria,
        rules_per_mansione=rules_per_mansione,
    )
    return {m.nome.strip().casefold(): per_id[m.pk] for m in mansioni}


def requisiti_per_nome_mansione(nome: str) -> dict[str, list]:
    """Requisiti per una mansione individuata per nome (case-insensitive)."""
    return requisiti_per_nome([nome]).get(
        str(nome or "").strip().casefold(), requisiti_vuoti()
    )


def _mansione_nome_legacy(legacy_id: int) -> str:
    """Nome mansione dalla riga legacy anagrafica (campo stringa ``mansione``)."""
    try:
        from core.legacy_anagrafica import fetch_anagrafica_rows
        for row in fetch_anagrafica_rows(deduplicate=True):
            if int(row.get("id") or 0) == int(legacy_id):
                return str(row.get("mansione") or "").strip()
    except Exception:
        pass
    return ""


def requisiti_dipendente(
    legacy_id: int, *, mansione_nome: str | None = None, area_id: int | None = None
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
    from ..models_rischi import EsposizioneRischio

    if area_id is None or mansione_nome is None:
        from ..models import DipendenteAnagraficaAziendale
        az = DipendenteAnagraficaAziendale.objects.filter(
            legacy_anagrafica_id=legacy_id
        ).first()
        if area_id is None and az is not None:
            area_id = az.area_aziendale_id
        if mansione_nome is None:
            mansione_nome = _mansione_nome_legacy(legacy_id)

    # Fonte 1: mansione lavorativa.
    base = (
        requisiti_per_nome_mansione(mansione_nome) if mansione_nome else requisiti_vuoti()
    )

    # Fonti 2+3: esposizioni di area + dirette al dipendente.
    esposizioni = (
        EsposizioneRischio.objects
        .filter(is_active=True)
        .select_related("fattore")
        .prefetch_related(
            "fattore__tipi_visita", "fattore__categorie_dpi", "fattore__categorie_corso",
        )
    )
    q_area = esposizioni.filter(area_id=area_id) if area_id else esposizioni.none()
    q_dir = esposizioni.filter(legacy_anagrafica_id=legacy_id)
    fattori = [e.fattore for e in list(q_area) + list(q_dir)]

    categoria_ids = {
        c.pk for f in fattori if f and f.is_active for c in f.categorie_corso.all()
    }
    extra = _requisiti_da_fattori(fattori, _corsi_per_categoria(categoria_ids))

    return {
        "dpi": _dedup(base["dpi"] + extra["dpi"]),
        "visite": _dedup(base["visite"] + extra["visite"]),
        "corsi": _dedup(base["corsi"] + extra["corsi"]),
        "piani": _dedup(base["piani"]),
        "fattori": _dedup(base["fattori"] + extra["fattori"]),
    }
