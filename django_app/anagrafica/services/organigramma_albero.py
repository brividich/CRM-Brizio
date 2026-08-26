"""Organigramma ad albero: gerarchia tra RUOLI, persone come foglie.

La gerarchia è SEMPRE tra :class:`RuoloOperativo` (campo ``riporta_a``), mai tra
persone: i dipendenti che ricoprono un ruolo sono foglie titolari del nodo di
quel ruolo, senza sotto-gerarchia. Le radici sono i ruoli con ``riporta_a IS
NULL``. La costruzione ricorsiva è protetta contro i cicli (difesa: insieme dei
ruoli già visitati lungo il percorso).
"""
from __future__ import annotations

from anagrafica.models import RuoloOperativo
from core.operational_roles import get_anagrafica_ids_for_role


def _nome_map(legacy_ids) -> dict[int, str]:
    """``legacy_anagrafica_id`` → "Cognome Nome" (best-effort dal DB legacy).

    Usa :func:`core.legacy_anagrafica.fetch_anagrafica_rows`; se la tabella
    legacy non è disponibile (es. suite di test) ritorna nomi vuoti senza
    rompere: l'albero resta valido sui soli id.
    """
    ids = sorted({int(i) for i in legacy_ids if i})
    if not ids:
        return {}
    from core.legacy_anagrafica import fetch_anagrafica_rows

    result: dict[int, str] = {}
    for row in fetch_anagrafica_rows(ids=ids):
        try:
            rid = int(row.get("id") or 0)
        except (TypeError, ValueError):
            rid = 0
        if not rid:
            continue
        nome = f"{row.get('cognome') or ''} {row.get('nome') or ''}".strip()
        result[rid] = nome
    return result


def build_ruolo_albero() -> list[dict]:
    """Albero dei ruoli: lista di nodi radice.

    Nodo: ``{"ruolo": RuoloOperativo, "titolari": [{"legacy_id", "nome"}],
    "figli": [nodo...]}``. Radici = ruoli attivi con ``riporta_a IS NULL``.
    """
    ruoli = list(RuoloOperativo.objects.filter(is_active=True).order_by("nome"))

    figli_di: dict[int | None, list[RuoloOperativo]] = {}
    for r in ruoli:
        figli_di.setdefault(r.riporta_a_id, []).append(r)

    titolari_ids: dict[int, list[int]] = {
        r.id: get_anagrafica_ids_for_role(r.id) for r in ruoli
    }
    tutti_ids = {lid for ids in titolari_ids.values() for lid in ids}
    nomi = _nome_map(tutti_ids)

    def _costruisci(ruolo: RuoloOperativo, visitati: frozenset[int]) -> dict | None:
        if ruolo.id in visitati:
            return None  # difesa anti-ciclo
        visitati = visitati | {ruolo.id}
        titolari = [
            {"legacy_id": lid, "nome": nomi.get(lid, "")}
            for lid in titolari_ids.get(ruolo.id, [])
        ]
        figli: list[dict] = []
        for figlio in figli_di.get(ruolo.id, []):
            nodo = _costruisci(figlio, visitati)
            if nodo is not None:
                figli.append(nodo)
        return {"ruolo": ruolo, "titolari": titolari, "figli": figli}

    radici: list[dict] = []
    for r in figli_di.get(None, []):
        nodo = _costruisci(r, frozenset())
        if nodo is not None:
            radici.append(nodo)
    return radici


def build_certificazione_copertura(tipo_qualifica_id: int, oggi=None) -> list[dict]:
    """Come :func:`build_ruolo_albero`, con overlay di copertura per una singola
    certificazione (``TipoQualifica``).

    Ogni titolare riceve ``stato`` ∈ ``{"posseduta_valida", "scaduta",
    "mancante"}`` (valida se la qualifica è assente di scadenza o non ancora
    scaduta; scaduta se ``data_scadenza < oggi``; mancante se non la possiede).
    Ogni nodo riceve ``n_totale`` (titolari diretti) e ``n_copertura`` (quanti
    la possiedono valida). Conteggio per-nodo diretto, non aggregato sui figli.
    """
    from anagrafica.models import DipendenteQualifica

    if oggi is None:
        from django.utils import timezone

        oggi = timezone.localdate()

    # legacy_id → stato per questa certificazione (una valida vince su scaduta
    # in caso di rinnovi multipli sullo stesso tipo).
    stato_per_id: dict[int, str] = {}
    for legacy_id, scad in (
        DipendenteQualifica.objects.filter(tipo_id=int(tipo_qualifica_id))
        .values_list("legacy_anagrafica_id", "data_scadenza")
    ):
        stato = "posseduta_valida" if (scad is None or scad >= oggi) else "scaduta"
        if stato_per_id.get(legacy_id) == "posseduta_valida":
            continue
        stato_per_id[legacy_id] = stato

    albero = build_ruolo_albero()

    def _annota(nodo: dict) -> None:
        n_cop = 0
        for titolare in nodo["titolari"]:
            st = stato_per_id.get(titolare["legacy_id"], "mancante")
            titolare["stato"] = st
            if st == "posseduta_valida":
                n_cop += 1
        nodo["n_totale"] = len(nodo["titolari"])
        nodo["n_copertura"] = n_cop
        for figlio in nodo["figli"]:
            _annota(figlio)

    for radice in albero:
        _annota(radice)
    return albero


def _ids_con_foto(legacy_ids) -> set[int]:
    """Sottoinsieme di ``legacy_ids`` che ha una foto profilo caricata.

    Serve a non emettere ``<img>`` verso ``anagrafica:foto_dipendente`` per chi
    la foto non ce l'ha (la view risponde 404): il diagramma disegna le iniziali.
    """
    ids = sorted({int(i) for i in legacy_ids if i})
    if not ids:
        return set()
    from anagrafica.models import DipendenteAnagraficaCivile

    return {
        int(lid)
        for lid in DipendenteAnagraficaCivile.objects.filter(
            legacy_anagrafica_id__in=ids
        )
        .exclude(foto="")
        .values_list("legacy_anagrafica_id", flat=True)
    }


def build_posizioni_albero() -> list[dict]:
    """Albero delle POSIZIONI: un riquadro per posizione (ruolo + persona).

    Deriva da :func:`build_ruolo_albero` espandendo i titolari, con questa
    regola (``tipo`` del nodo):

    - ``posizione`` — ruolo con un solo titolare, oppure ruolo-foglia con più
      titolari: in quest'ultimo caso genera N riquadri fratelli, uno per persona
      (è il caso tipico "5 × Project Engineer" sotto lo stesso responsabile).
    - ``condiviso`` — ruolo con più titolari **che ha ruoli subordinati**: resta
      un riquadro unico con tutte le persone, perché appendere i sottoruoli a un
      titolare scelto arbitrariamente inventerebbe una gerarchia tra persone.
    - ``vacante`` — ruolo senza titolari: il riquadro resta, la posizione è
      scoperta.

    Ogni titolare porta ``ha_foto`` per il rendering dell'avatar.
    """
    albero = build_ruolo_albero()

    tutti_ids = []

    def _raccogli(nodo: dict) -> None:
        tutti_ids.extend(t["legacy_id"] for t in nodo["titolari"])
        for figlio in nodo["figli"]:
            _raccogli(figlio)

    for radice in albero:
        _raccogli(radice)
    con_foto = _ids_con_foto(tutti_ids)

    def _espandi(nodo: dict) -> list[dict]:
        figli: list[dict] = []
        for figlio in nodo["figli"]:
            figli.extend(_espandi(figlio))

        titolari = sorted(nodo["titolari"], key=lambda t: (t["nome"] or "", t["legacy_id"]))
        for t in titolari:
            t["ha_foto"] = t["legacy_id"] in con_foto

        if not titolari:
            return [{"ruolo": nodo["ruolo"], "tipo": "vacante", "titolari": [], "figli": figli}]
        if len(titolari) == 1:
            return [{"ruolo": nodo["ruolo"], "tipo": "posizione", "titolari": titolari, "figli": figli}]
        if not figli:
            return [
                {"ruolo": nodo["ruolo"], "tipo": "posizione", "titolari": [t], "figli": []}
                for t in titolari
            ]
        return [{"ruolo": nodo["ruolo"], "tipo": "condiviso", "titolari": titolari, "figli": figli}]

    posizioni: list[dict] = []
    for radice in albero:
        posizioni.extend(_espandi(radice))
    return posizioni
