"""Spostamenti organizzativi: registrazione, verifica di idoneità, attivazione.

Uno spostamento è un atto unico — reparto, area aziendale, mansione e ruolo
cambiano insieme — e viene registrato come ``DipendenteAssegnazione``. Da qui
passano le tre cose che il modulo deve garantire:

1. **Verifica di idoneità.** Prima di confermare, si chiede a
   ``services.conformita`` se la persona è in regola *per la mansione di
   destinazione*: competenze (formazione), DPI e visite mediche. L'esito è
   consultivo — non blocca lo spostamento — e viene fotografato
   sull'assegnazione, così resta la traccia di cosa mancava quel giorno.

2. **Attivazione differita.** I campi vivi del dipendente si toccano solo
   quando la decorrenza è arrivata: un'assegnazione datata al futuro resta
   *programmata* e il portale continua a vedere il reparto vecchio finché
   ``attiva_assegnazione`` non la applica (subito se la data è già passata,
   altrimenti dal task notturno).

3. **Audit per-campo.** All'attivazione si scrive comunque
   ``DipendenteCambiamentoOrganizzativo`` per ciascun campo cambiato, con
   ``data_effetto`` = inizio dell'assegnazione: il log per-campo resta la
   fonte per report e diagnostica esistenti.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from ..models import AreaAziendale, DipendenteAssegnazione, DipendenteCambiamentoOrganizzativo

# Etichette dei domini nel gap di idoneità, come li produce services.conformita.
DOMINIO_PREFISSI = {
    "formazione": "Corso: ",
    "dpi": "DPI: ",
    "visite": "Visita: ",
}


def verifica_idoneita(
    legacy_id: int,
    mansione: str,
    *,
    include_visite_dettaglio: bool = False,
) -> dict[str, Any]:
    """Idoneità della persona **rispetto a una mansione** (anche solo ipotizzata).

    Wrapper di ``conformita.stato_conformita``: quel servizio sa già calcolare i
    requisiti di una mansione arbitraria, quindi lo si usa in anteprima prima di
    confermare lo spostamento.

    Ritorna ``{"esito", "label", "colore", "mancanti", "scaduti", "gap",
    "per_dominio"}``. Fail-open: se il calcolo esplode si torna "da verificare"
    invece di impedire la registrazione dello spostamento.
    """
    vuoto = {
        "esito": DipendenteAssegnazione.IDONEITA_NA,
        "label": DipendenteAssegnazione.IDONEITA_LABEL[DipendenteAssegnazione.IDONEITA_NA],
        "colore": DipendenteAssegnazione.IDONEITA_COLORI[DipendenteAssegnazione.IDONEITA_NA],
        "mancanti": [],
        "scaduti": [],
        "gap": [],
        "per_dominio": {},
    }
    if not mansione or not mansione.strip():
        return vuoto

    try:
        from . import conformita
        stato = conformita.stato_conformita(
            legacy_id,
            mansione=mansione.strip(),
            include_visite_dettaglio=include_visite_dettaglio,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Verifica idoneita fallita per dipendente %s / mansione %r", legacy_id, mansione,
            exc_info=True,
        )
        return dict(vuoto, label="Da verificare", esito="")

    idn = stato.get("idoneita") or {}
    esito = idn.get("esito") or DipendenteAssegnazione.IDONEITA_NA
    mancanti = list(idn.get("mancanti") or [])
    scaduti = list(idn.get("scaduti") or [])

    return {
        "esito": esito,
        "label": DipendenteAssegnazione.IDONEITA_LABEL.get(esito, "Da verificare"),
        "colore": DipendenteAssegnazione.IDONEITA_COLORI.get(esito, "#64748b"),
        "mancanti": mancanti,
        "scaduti": scaduti,
        # Gli scaduti prima: un requisito scaduto è più grave di uno mai registrato.
        "gap": scaduti + mancanti,
        "per_dominio": _raggruppa_per_dominio(scaduti, mancanti),
    }


def _raggruppa_per_dominio(scaduti: list[str], mancanti: list[str]) -> dict[str, list[str]]:
    """Divide il gap nei tre domini che l'utente vuole vedere separati."""
    out: dict[str, list[str]] = {"formazione": [], "dpi": [], "visite": []}
    for voce, suffisso in [(v, " (scaduto)") for v in scaduti] + [(v, "") for v in mancanti]:
        for dominio, prefisso in DOMINIO_PREFISSI.items():
            if voce.startswith(prefisso):
                out[dominio].append(voce[len(prefisso):] + suffisso)
                break
    return {k: v for k, v in out.items() if v}


def assetto_corrente(legacy_id: int) -> dict[str, Any]:
    """Assetto organizzativo **vivo** della persona: reparto, area, mansione, ruolo.

    È il default dello spostamento. Uno spostamento tocca quasi sempre uno o due
    campi su quattro: i campi non toccati devono restare quelli di oggi, non
    diventare vuoti — altrimenti "cambio reparto" cancellerebbe la mansione.

    Ritorna sempre le quattro chiavi, con stringa vuota / ``None`` se il dato non
    esiste.
    """
    from core.legacy_anagrafica import fetch_anagrafica_rows

    from ..models import DipendenteAnagraficaAziendale

    reparto = mansione = ""
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if rows:
        reparto = (rows[0].get("reparto") or "").strip()
        mansione = (rows[0].get("mansione") or "").strip()

    az = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id).first()
    return {
        "reparto": reparto,
        "mansione": mansione,
        "area_aziendale_id": az.area_aziendale_id if az else None,
        "ruolo_aziendale": ((az.ruolo_aziendale or "").strip() if az else ""),
    }


@transaction.atomic
def crea_assegnazione(
    legacy_id: int,
    *,
    data_inizio,
    reparto: str = "",
    area_aziendale_id: int | None = None,
    mansione: str = "",
    ruolo_aziendale: str = "",
    ruolo_parallelo: bool = False,
    note: str = "",
    user=None,
    include_visite_dettaglio: bool = False,
) -> DipendenteAssegnazione:
    """Registra uno spostamento, chiudendo il precedente e verificando l'idoneità.

    I campi lasciati vuoti **ereditano l'assetto attuale** (vedi
    ``assetto_corrente``): l'assegnazione resta la fotografia completa del
    periodo — quattro campi sempre valorizzati — e nessun campo viene azzerato
    solo perché chi registrava lo spostamento non lo ha toccato.

    Con ``ruolo_parallelo`` il ruolo indicato **si aggiunge** a quello in essere
    invece di sostituirlo: due incarichi dello stesso ambito che convivono (chi
    resta capoturno e diventa anche capocommessa). Il campo «Ruolo aziendale»
    della scheda non viene toccato e, sull'assegnazione, ``ruolo_aziendale``
    registra il ruolo *aggiunto*. Senza un ruolo esplicito il flag non ha
    oggetto e viene ignorato.

    Se reparto/area/mansione restano quelli di oggi (l'unica cosa che cambia è
    il ruolo aggiunto, con decorrenza già arrivata), **non si registra un nuovo
    spostamento**: si aggiunge solo l'incarico e l'assegnazione aperta resta
    quella di prima, "In corso". Un nuovo spostamento chiuderebbe quella card
    anche se il ruolo che descriveva resta valido — il flag serve proprio a
    farli convivere, non a farli succedere.

    Se ``data_inizio`` è già passata (o è oggi) l'assegnazione viene anche
    attivata subito; altrimenti resta programmata.
    """
    corrente = assetto_corrente(legacy_id)
    reparto = ((reparto or "").strip() or corrente["reparto"])[:200]
    mansione = ((mansione or "").strip() or corrente["mansione"])[:200]
    # Il flag vale solo su un ruolo scelto adesso: ereditare il principale e poi
    # dichiararlo "parallelo a sé stesso" non vuol dire niente.
    ruolo_parallelo = bool(ruolo_parallelo) and bool((ruolo_aziendale or "").strip())
    ruolo_aziendale = ((ruolo_aziendale or "").strip() or corrente["ruolo_aziendale"])[:200]
    if area_aziendale_id is None:
        area_aziendale_id = corrente["area_aziendale_id"]

    # L'area aziendale deve appartenere al reparto scelto, stessa invariante di
    # _sync_aziendale_from_reparto: un'area incoerente viene scartata invece di
    # bloccare lo spostamento.
    area_valida_id = None
    if area_aziendale_id:
        area = (
            AreaAziendale.objects
            .filter(pk=area_aziendale_id, reparto__nome__iexact=reparto)
            .first()
            if reparto else None
        )
        area_valida_id = area.pk if area is not None else None

    aperta = (
        DipendenteAssegnazione.objects
        .filter(legacy_anagrafica_id=legacy_id, data_fine__isnull=True)
        .order_by("-data_inizio", "-created_at")
        .first()
    )
    # Confronto con la card aperta stessa, non con l'assetto live: sono la
    # stessa cosa nel caso comune, ma possono divergere (sync che azzera
    # l'area, differenze di maiuscole/spazi) — ed è la card aperta quella che
    # non deve chiudersi per un'aggiunta che non la cambia davvero.
    solo_ruolo_aggiunto = (
        aperta is not None
        and ruolo_parallelo
        and data_inizio <= timezone.localdate()
        and reparto.strip().casefold() == (aperta.reparto or "").strip().casefold()
        and mansione.strip().casefold() == (aperta.mansione or "").strip().casefold()
        and area_valida_id == aperta.area_aziendale_id
    )
    if solo_ruolo_aggiunto:
        from .ruoli_sync import assicura_assegnazione
        assicura_assegnazione(legacy_id, ruolo_aziendale, user=user)
        return aperta

    idoneita = verifica_idoneita(
        legacy_id, mansione, include_visite_dettaglio=include_visite_dettaglio
    )

    DipendenteAssegnazione.chiudi_aperta(legacy_id, data_inizio)

    assegnazione = DipendenteAssegnazione.objects.create(
        legacy_anagrafica_id=legacy_id,
        data_inizio=data_inizio,
        reparto=reparto,
        area_aziendale_id=area_valida_id,
        mansione=mansione,
        ruolo_aziendale=ruolo_aziendale,
        ruolo_parallelo=ruolo_parallelo,
        note=note,
        idoneita_esito=idoneita["esito"],
        idoneita_mancanti=idoneita["mancanti"],
        idoneita_scaduti=idoneita["scaduti"],
        idoneita_verificata_il=timezone.now(),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )

    if data_inizio <= timezone.localdate():
        attiva_assegnazione(assegnazione, user=user)

    return assegnazione


@transaction.atomic
def modifica_assegnazione(
    assegnazione: DipendenteAssegnazione,
    *,
    data_inizio,
    reparto: str = "",
    area_aziendale_id: int | None = None,
    mansione: str = "",
    ruolo_aziendale: str = "",
    ruolo_parallelo: bool = False,
    note: str = "",
    user=None,
    include_visite_dettaglio: bool = False,
) -> DipendenteAssegnazione:
    """Corregge una card di spostamento già registrata — attiva, programmata o
    conclusa — senza passare da un nuovo spostamento.

    A differenza di ``crea_assegnazione`` i campi lasciati vuoti ereditano i
    valori **già sulla card** (non l'assetto live di oggi): qui si corregge un
    errore su QUESTA registrazione, non se ne descrive una nuova.

    - **Programmata** (mai attivata): i campi si correggono e basta; se la
      nuova decorrenza è già arrivata l'attivazione parte subito, come alla
      prima registrazione.
    - **Aperta e già attiva** (rappresenta l'assetto vivo di oggi): la
      correzione si propaga ai campi vivi del dipendente e produce lo stesso
      log per-campo di un'attivazione — l'audit trail resta la verità su cosa
      è cambiato, anche per una correzione.
    - **Conclusa** (superata da uno spostamento successivo): la correzione
      resta sulla card, senza toccare i campi vivi né il log per-campo.

    Non ricalcola i confini delle card adiacenti: correggere la decorrenza di
    una card può lasciare un buco o una sovrapposizione con quella
    precedente/successiva, da sistemare a mano se serve.

    Ritorna l'assegnazione aggiornata.
    """
    legacy_id = assegnazione.legacy_anagrafica_id

    reparto = ((reparto or "").strip() or assegnazione.reparto)[:200]
    mansione_prima = assegnazione.mansione
    mansione = ((mansione or "").strip() or mansione_prima)[:200]
    ruolo_parallelo = bool(ruolo_parallelo) and bool((ruolo_aziendale or "").strip())
    ruolo_aziendale = ((ruolo_aziendale or "").strip() or assegnazione.ruolo_aziendale)[:200]
    if area_aziendale_id is None:
        area_aziendale_id = assegnazione.area_aziendale_id

    area_valida_id = None
    if area_aziendale_id:
        area = (
            AreaAziendale.objects
            .filter(pk=area_aziendale_id, reparto__nome__iexact=reparto)
            .first()
            if reparto else None
        )
        area_valida_id = area.pk if area is not None else None

    if mansione != mansione_prima:
        idoneita = verifica_idoneita(
            legacy_id, mansione, include_visite_dettaglio=include_visite_dettaglio
        )
        assegnazione.idoneita_esito = idoneita["esito"]
        assegnazione.idoneita_mancanti = idoneita["mancanti"]
        assegnazione.idoneita_scaduti = idoneita["scaduti"]
        assegnazione.idoneita_verificata_il = timezone.now()

    era_programmata = assegnazione.attivata_il is None
    era_aperta = assegnazione.data_fine is None
    reparto_prima = assegnazione.reparto

    assegnazione.data_inizio = data_inizio
    assegnazione.reparto = reparto
    assegnazione.area_aziendale_id = area_valida_id
    assegnazione.mansione = mansione
    assegnazione.ruolo_aziendale = ruolo_aziendale
    assegnazione.ruolo_parallelo = ruolo_parallelo
    assegnazione.note = note
    assegnazione.modificata_il = timezone.now()
    assegnazione.modificata_da = user if getattr(user, "is_authenticated", False) else None
    assegnazione.save()

    if era_programmata:
        if data_inizio <= timezone.localdate():
            attiva_assegnazione(assegnazione, user=user)
        return assegnazione

    if not era_aperta:
        # Card conclusa: solo storia da correggere, non lo stato vivo.
        return assegnazione

    from core.legacy_anagrafica import fetch_anagrafica_rows, upsert_anagrafica_dipendente
    from ..views import _registra_cambiamento, _sync_aziendale_from_reparto

    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        return assegnazione
    dip = rows[0]

    upsert_anagrafica_dipendente(
        row_id=legacy_id,
        aliasusername=dip.get("aliasusername") or "",
        nome=dip.get("nome") or "",
        cognome=dip.get("cognome") or "",
        reparto=reparto,
        mansione=mansione,
        ruolo=dip.get("ruolo") or "",
        matricola=dip.get("matricola") or "",
        email=dip.get("email") or "",
        email_notifica=dip.get("email_notifica") or "",
        attivo=bool(dip.get("attivo", True)),
    )

    if reparto != reparto_prima:
        _registra_cambiamento(
            legacy_id, DipendenteCambiamentoOrganizzativo.TIPO_REPARTO,
            reparto_prima, reparto, user, data_effetto=data_inizio,
        )
    if mansione != mansione_prima:
        _registra_cambiamento(
            legacy_id, DipendenteCambiamentoOrganizzativo.TIPO_MANSIONE,
            mansione_prima, mansione, user, data_effetto=data_inizio,
        )

    _sync_aziendale_from_reparto(
        legacy_id, reparto,
        area_aziendale_id=area_valida_id,
        saved_by=user,
        data_decorrenza=data_inizio,
    )
    _aggiorna_ruolo_aziendale(
        legacy_id, ruolo_aziendale,
        user=user, data_decorrenza=data_inizio,
        parallelo=ruolo_parallelo,
    )

    return assegnazione


def attiva_assegnazione(assegnazione: DipendenteAssegnazione, *, user=None) -> bool:
    """Allinea i campi vivi del dipendente a questa assegnazione.

    Scrive reparto/mansione sulla riga legacy e area/area aziendale/ruolo su
    ``DipendenteAnagraficaAziendale``, poi registra il log per-campo con
    ``data_effetto`` = inizio dell'assegnazione (non "oggi": se il task gira in
    ritardo la decorrenza formale resta quella giusta).

    Idempotente: un'assegnazione già attivata non viene riapplicata.
    Ritorna True se ha attivato, False se era già attiva.

    Gli helper di ``views`` si importano qui dentro: sono le funzioni che già
    presidiano la scrittura di quei campi e importarle a livello di modulo
    creerebbe un ciclo views -> services -> views.
    """
    if assegnazione.attivata_il is not None:
        return False

    from core.legacy_anagrafica import fetch_anagrafica_rows, upsert_anagrafica_dipendente
    from ..views import _registra_cambiamento, _sync_aziendale_from_reparto

    legacy_id = assegnazione.legacy_anagrafica_id
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        return False
    dip = rows[0]

    reparto_vecchio = (dip.get("reparto") or "").strip()
    mansione_vecchia = (dip.get("mansione") or "").strip()

    # Rete di sicurezza per le assegnazioni con campi parziali (registrate prima
    # del fill-forward di crea_assegnazione, o create da codice): un campo vuoto
    # non cancella il dato vivo, lo lascia com'è.
    reparto_nuovo = assegnazione.reparto or reparto_vecchio
    mansione_nuova = assegnazione.mansione or mansione_vecchia
    area_nuova_id = assegnazione.area_aziendale_id or _area_aziendale_corrente_id(legacy_id)

    upsert_anagrafica_dipendente(
        row_id=legacy_id,
        aliasusername=dip.get("aliasusername") or "",
        nome=dip.get("nome") or "",
        cognome=dip.get("cognome") or "",
        reparto=reparto_nuovo,
        mansione=mansione_nuova,
        ruolo=dip.get("ruolo") or "",
        matricola=dip.get("matricola") or "",
        email=dip.get("email") or "",
        email_notifica=dip.get("email_notifica") or "",
        attivo=bool(dip.get("attivo", True)),
    )

    _registra_cambiamento(
        legacy_id,
        DipendenteCambiamentoOrganizzativo.TIPO_REPARTO,
        reparto_vecchio, reparto_nuovo,
        user, data_effetto=assegnazione.data_inizio,
    )
    _registra_cambiamento(
        legacy_id,
        DipendenteCambiamentoOrganizzativo.TIPO_MANSIONE,
        mansione_vecchia, mansione_nuova,
        user, data_effetto=assegnazione.data_inizio,
    )

    # Reparto/area aziendale sul record aziendale: il sync è l'unico punto che
    # scrive quei due campi e li storicizza da sé.
    _sync_aziendale_from_reparto(
        legacy_id, reparto_nuovo,
        area_aziendale_id=area_nuova_id,
        saved_by=user,
        data_decorrenza=assegnazione.data_inizio,
    )

    _aggiorna_ruolo_aziendale(
        legacy_id, assegnazione.ruolo_aziendale,
        user=user, data_decorrenza=assegnazione.data_inizio,
        parallelo=assegnazione.ruolo_parallelo,
    )

    assegnazione.attivata_il = timezone.now()
    assegnazione.save(update_fields=["attivata_il"])
    return True


def _area_aziendale_corrente_id(legacy_id: int) -> int | None:
    from ..models import DipendenteAnagraficaAziendale

    return (
        DipendenteAnagraficaAziendale.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .values_list("area_aziendale_id", flat=True)
        .first()
    )


def _aggiorna_ruolo_aziendale(
    legacy_id: int, ruolo: str, *, user, data_decorrenza, parallelo: bool = False
) -> None:
    from ..models import DipendenteAnagraficaAziendale
    from ..views import _registra_cambiamento

    # Ruolo non indicato dallo spostamento: si conserva quello in essere. Il
    # ruolo aziendale si toglie esplicitamente dalla scheda, non per omissione.
    if not (ruolo or "").strip():
        return

    from .ruoli_sync import assicura_assegnazione, nome_alimenta_principale

    # Ruolo che si somma invece di sostituire. Due casi, stesso effetto:
    # il flag «in parallelo» scelto da chi registra lo spostamento, e i ruoli di
    # un altro organigramma (45001, 27001, …), che per definizione non scrivono
    # il «Ruolo aziendale» della scheda. In entrambi il ruolo diventa
    # un'assegnazione in più e il principale resta quello di prima.
    if parallelo or not nome_alimenta_principale(ruolo):
        # Fuori catalogo non c'è nulla da aggiungere: un nome storico resta un
        # valore testuale, e in parallelo non ha dove vivere.
        assicura_assegnazione(legacy_id, ruolo, user=user)
        return

    az, _ = DipendenteAnagraficaAziendale.objects.get_or_create(
        legacy_anagrafica_id=legacy_id, defaults={"updated_by": user},
    )
    precedente = az.ruolo_aziendale or ""
    if precedente.strip().casefold() == (ruolo or "").strip().casefold():
        # Stesso ruolo di prima: niente da storicizzare, ma l'assegnazione può
        # mancare lo stesso (schede più vecchie della card «Ruoli operativi»).
        assicura_assegnazione(legacy_id, ruolo, user=user)
        return
    az.ruolo_aziendale = ruolo
    az.updated_by = user
    az.save(update_fields=["ruolo_aziendale", "updated_by", "updated_at"])
    # Il ruolo principale è uno dei ruoli della persona: se lo spostamento ne
    # nomina uno del catalogo, deve comparire anche tra le assegnazioni. Le
    # altre non si toccano — il multiruolo resta.
    assicura_assegnazione(legacy_id, ruolo, user=user)
    _registra_cambiamento(
        legacy_id,
        DipendenteCambiamentoOrganizzativo.TIPO_RUOLO_AZIENDALE,
        precedente, ruolo,
        user, data_effetto=data_decorrenza,
    )


def attiva_programmate_scadute(*, limit: int | None = None) -> dict[str, int]:
    """Applica tutte le assegnazioni programmate la cui decorrenza è arrivata.

    Pensata per il task schedulato: gira ogni notte e non deve mai far cadere il
    cluster, quindi un errore su una persona non ferma le altre.
    """
    import logging
    logger = logging.getLogger(__name__)

    qs = (
        DipendenteAssegnazione.objects
        .filter(attivata_il__isnull=True, data_inizio__lte=timezone.localdate())
        .order_by("data_inizio", "pk")
    )
    if limit:
        qs = qs[:limit]

    attivate = errori = 0
    for assegnazione in list(qs):
        try:
            if attiva_assegnazione(assegnazione):
                attivate += 1
        except Exception:
            errori += 1
            logger.exception(
                "Attivazione assegnazione %s (dipendente %s) fallita",
                assegnazione.pk, assegnazione.legacy_anagrafica_id,
            )
    return {"attivate": attivate, "errori": errori}


def assegnazione_corrente(legacy_id: int) -> DipendenteAssegnazione | None:
    """Assegnazione in vigore oggi (nessuna se la persona non ne ha mai avute)."""
    oggi = timezone.localdate()
    from django.db.models import Q
    return (
        DipendenteAssegnazione.objects
        .filter(legacy_anagrafica_id=legacy_id, data_inizio__lte=oggi)
        .filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi))
        .select_related("area_aziendale")
        .order_by("-data_inizio", "-created_at")
        .first()
    )
