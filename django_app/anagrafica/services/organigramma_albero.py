"""Organigramma ad albero: gerarchia tra RUOLI, persone come foglie.

La gerarchia è SEMPRE tra :class:`RuoloOperativo` (campo ``riporta_a``), mai tra
persone: i dipendenti che ricoprono un ruolo sono foglie titolari del nodo di
quel ruolo, senza sotto-gerarchia. Le radici sono i ruoli con ``riporta_a IS
NULL``. La costruzione ricorsiva è protetta contro i cicli (difesa: insieme dei
ruoli già visitati lungo il percorso).

Con ``ambito`` si disegna **un organigramma per ambito**: quello produttivo,
quello della sicurezza ISO 45001, quello ISO 27001. È lo stesso albero
ristretto ai ruoli di quell'ambito — un ruolo il cui sovraordinato resta fuori
dal filtro diventa radice, perché la sua gerarchia in quell'organigramma
comincia da lui.
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


def build_ruolo_albero(ambito_id: int | None = None) -> list[dict]:
    """Albero dei ruoli: lista di nodi radice.

    Nodo: ``{"ruolo": RuoloOperativo, "titolari": [{"legacy_id", "nome"}],
    "figli": [nodo...]}``. Radici = ruoli attivi con ``riporta_a IS NULL``.

    ``ambito_id`` restringe l'albero a un solo ambito (organigramma della
    sicurezza, delle informazioni, …); ``0`` seleziona i ruoli **senza ambito**.
    """
    qs = RuoloOperativo.objects.filter(is_active=True).select_related("ambito")
    if ambito_id is not None:
        qs = qs.filter(ambito_id=None) if ambito_id == 0 else qs.filter(ambito_id=ambito_id)
    ruoli = list(qs.order_by("nome"))

    presenti = {r.id for r in ruoli}
    figli_di: dict[int | None, list[RuoloOperativo]] = {}
    for r in ruoli:
        # Sovraordinato fuori dal filtro: dentro questo organigramma il ruolo è
        # una radice, non un orfano da buttare via.
        padre = r.riporta_a_id if r.riporta_a_id in presenti else None
        figli_di.setdefault(padre, []).append(r)

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


def build_certificazione_copertura(tipo_qualifica_id: int, oggi=None, ambito_id: int | None = None) -> list[dict]:
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

    albero = build_ruolo_albero(ambito_id)

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


#: oltre questo numero di riporti diretti tutti-foglia la colonna verticale si
#: spezza in più colonne, per non far scorrere all'infinito la pagina.
SOGLIA_COLONNE = 5
#: colonne massime affiancate sotto lo stesso riquadro.
MAX_COLONNE = 3


def griglia_riporti(figli: list[dict]) -> bool:
    """True se i riporti diretti vanno disposti su più colonne.

    Solo quando sono tanti (> :data:`SOGLIA_COLONNE`) **e** nessuno di loro ha a
    sua volta dei riporti: un sotto-albero dentro una colonna sarebbe illeggibile.
    """
    return len(figli) > SOGLIA_COLONNE and all(not f["figli"] for f in figli)


def spezza_in_colonne(figli: list[dict]) -> list[list[dict]]:
    """I riporti diretti divisi nelle colonne da disegnare sotto il riquadro.

    Una sola colonna nel caso normale — i riquadri scendono in verticale sotto
    il genitore. Quando :func:`griglia_riporti` lo consente si affiancano fino a
    :data:`MAX_COLONNE` colonne, riempite dall'alto verso il basso.
    """
    if not figli:
        return []
    if not griglia_riporti(figli):
        return [list(figli)]
    n_colonne = min(MAX_COLONNE, -(-len(figli) // SOGLIA_COLONNE))
    per_colonna = -(-len(figli) // n_colonne)
    return [figli[i:i + per_colonna] for i in range(0, len(figli), per_colonna)]


def build_posizioni_albero(ambito_id: int | None = None) -> list[dict]:
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

    Ogni titolare porta ``ha_foto`` per il rendering dell'avatar; ogni nodo
    porta ``griglia`` e ``colonne`` (vedi :func:`spezza_in_colonne`) per il
    layout dei riporti.
    ``ambito_id`` disegna il solo organigramma di quell'ambito.
    """
    albero = build_ruolo_albero(ambito_id)

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

        griglia = griglia_riporti(figli)

        def _nodo(tipo: str, titolari: list[dict], figli_nodo: list[dict]) -> dict:
            return {
                "ruolo": nodo["ruolo"],
                "tipo": tipo,
                "titolari": titolari,
                "figli": figli_nodo,
                "griglia": griglia if figli_nodo else False,
                "colonne": spezza_in_colonne(figli_nodo),
            }

        titolari = sorted(nodo["titolari"], key=lambda t: (t["nome"] or "", t["legacy_id"]))
        for t in titolari:
            t["ha_foto"] = t["legacy_id"] in con_foto

        if not titolari:
            return [_nodo("vacante", [], figli)]
        if len(titolari) == 1:
            return [_nodo("posizione", titolari, figli)]
        if not figli:
            return [_nodo("posizione", [t], []) for t in titolari]
        return [_nodo("condiviso", titolari, figli)]

    posizioni: list[dict] = []
    for radice in albero:
        posizioni.extend(_espandi(radice))
    return posizioni
