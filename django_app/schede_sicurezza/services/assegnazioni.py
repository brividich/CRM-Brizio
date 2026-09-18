"""Assegnazione dinamica delle SDS in base alla mansione corrente.

La fonte di verita' resta la relazione prodotto->mansioni e la mansione viva
del dipendente. Un cambio mansione rende quindi immediatamente dovute le SDS
nuove; la presa visione conserva lo storico della specifica versione letta.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Cruscotto personale delle SDS dovute: unica destinazione di notifiche ed email.
URL_SDS_DA_LEGGERE = "/schede-sicurezza/da-leggere/"


@dataclass
class ProfiloSDSUtente:
    collegato: bool
    mansione_nome: str
    mansione_id: int | None
    schede: list
    schede_lette_ids: set[int]

    @property
    def da_leggere(self) -> list:
        return [scheda for scheda in self.schede if scheda.pk not in self.schede_lette_ids]

    @property
    def completate(self) -> list:
        return [scheda for scheda in self.schede if scheda.pk in self.schede_lette_ids]


def _mansione_per_nome(nome: str):
    from anagrafica.models import Mansione

    nome = (nome or "").strip()
    if not nome:
        return None
    return Mansione.objects.filter(nome__iexact=nome).order_by("-is_active", "pk").first()


def _riga_anagrafica_per_legacy_user_id(legacy_user_id: int | None):
    if not legacy_user_id:
        return None
    try:
        from core.legacy_models import AnagraficaDipendente
        from core.legacy_utils import legacy_table_has_column

        if not legacy_table_has_column("anagrafica_dipendenti", "utente_id"):
            return None
        return (
            AnagraficaDipendente.objects
            .filter(utente_id=legacy_user_id)
            .values("id", "utente_id", "mansione")
            .first()
        )
    except Exception:
        logger.warning("Risoluzione dipendente per SDS fallita", exc_info=True)
        return None


def profilo_sds_utente(user) -> ProfiloSDSUtente:
    """SDS correnti dovute all'utente in base alla mansione viva in anagrafica."""
    vuoto = ProfiloSDSUtente(False, "", None, [], set())
    if not getattr(user, "is_authenticated", False):
        return vuoto

    try:
        from core.models import Profile
        from ..models import PresaVisioneScheda, SchedaSicurezza

        legacy_user_id = (
            Profile.objects.filter(user=user).values_list("legacy_user_id", flat=True).first()
        )
        dipendente = _riga_anagrafica_per_legacy_user_id(legacy_user_id)
        if not dipendente:
            return vuoto
        mansione_nome = (dipendente.get("mansione") or "").strip()
        mansione = _mansione_per_nome(mansione_nome)
        if mansione is None:
            return ProfiloSDSUtente(True, mansione_nome, None, [], set())

        schede = list(
            SchedaSicurezza.objects.filter(
                is_corrente=True,
                prodotto__attivo=True,
                prodotto__mansioni=mansione,
            )
            .select_related("prodotto")
            .prefetch_related("prodotto__mansioni", "prodotto__dpi_obbligatori")
            .order_by("prodotto__nome")
        )
        lette = set(
            PresaVisioneScheda.objects.filter(
                operatore=user, scheda_id__in=[scheda.pk for scheda in schede]
            ).values_list("scheda_id", flat=True)
        )
        return ProfiloSDSUtente(True, mansione.nome, mansione.pk, schede, lette)
    except Exception:
        logger.warning(
            "Calcolo SDS dovute all'utente %s fallito",
            getattr(user, "pk", None),
            exc_info=True,
        )
        return vuoto


def _utenti_legacy_per_mansioni(nomi_mansioni: list[str]) -> dict[int, str]:
    """Mappa legacy_user_id -> mansione per dipendenti attivi delle mansioni date."""
    nomi = [nome.strip() for nome in nomi_mansioni if (nome or "").strip()]
    if not nomi:
        return {}
    try:
        from django.db.models import Q
        from anagrafica.models import DipendenteAnagraficaAziendale
        from core.legacy_models import AnagraficaDipendente
        from core.legacy_utils import legacy_table_has_column

        if not legacy_table_has_column("anagrafica_dipendenti", "utente_id"):
            return {}
        filtro = Q()
        for nome in nomi:
            filtro |= Q(mansione__iexact=nome)
        cessati_ids = DipendenteAnagraficaAziendale.objects.filter(
            data_cessazione__isnull=False
        ).values_list("legacy_anagrafica_id", flat=True)
        rows = (
            AnagraficaDipendente.objects.filter(
                filtro, utente_id__isnull=False
            ).exclude(id__in=cessati_ids).values_list("utente_id", "mansione")
        )
        return {int(uid): (mansione or "") for uid, mansione in rows if uid}
    except Exception:
        logger.warning("Risoluzione destinatari SDS per mansione fallita", exc_info=True)
        return {}


def _django_user_ids_per_legacy(legacy_ids: set[int]) -> dict[int, int]:
    if not legacy_ids:
        return {}
    try:
        from core.models import Profile

        return {
            int(legacy_id): int(user_id)
            for legacy_id, user_id in Profile.objects.filter(
                legacy_user_id__in=legacy_ids, user__is_active=True
            ).values_list("legacy_user_id", "user_id")
            if legacy_id and user_id
        }
    except Exception:
        logger.warning("Risoluzione account Django per destinatari SDS fallita", exc_info=True)
        return {}


def _notifica_destinatari_scheda(scheda, nomi_mansioni: list[str], *, motivo: str) -> int:
    from core.notifiche import invia_notifica
    from ..models import PresaVisioneScheda

    destinatari = _utenti_legacy_per_mansioni(nomi_mansioni)
    django_ids = _django_user_ids_per_legacy(set(destinatari))
    gia_letta = set(
        PresaVisioneScheda.objects.filter(
            scheda=scheda, operatore_id__in=django_ids.values()
        ).values_list("operatore_id", flat=True)
    )
    inviate = 0
    for legacy_user_id, mansione in destinatari.items():
        if django_ids.get(legacy_user_id) in gia_letta:
            continue
        invia_notifica(
            legacy_user_id,
            "presa_visione",
            (
                f"SDS '{scheda.prodotto.nome}' versione {scheda.versione or '-'} "
                f"da prendere in visione per la mansione '{mansione}' ({motivo})."
            ),
            url_azione="/schede-sicurezza/da-leggere/",
        )
        inviate += 1
    return inviate


def notifica_nuova_versione(scheda) -> int:
    """Avvisa i dipendenti interessati quando diventa corrente una nuova SDS."""
    nomi = list(scheda.prodotto.mansioni.values_list("nome", flat=True))
    return _notifica_destinatari_scheda(scheda, nomi, motivo="nuova versione")


def notifica_mansioni_aggiunte(prodotto, mansione_ids: set[int]) -> int:
    """Avvisa i nuovi destinatari quando una SDS corrente viene legata a una mansione."""
    scheda = prodotto.scheda_corrente()
    if scheda is None or not mansione_ids:
        return 0
    nomi = list(
        prodotto.mansioni.filter(pk__in=mansione_ids).values_list("nome", flat=True)
    )
    return _notifica_destinatari_scheda(scheda, nomi, motivo="nuova assegnazione")


def conteggio_sds_per_mansione(mansione_ids) -> dict[int, int]:
    """Quante SDS correnti sono dovute per ciascuna mansione (prodotti attivi).

    Una query sola per l'intero catalogo mansioni: la lista mansioni ne mostra
    decine e un conteggio per riga sarebbe una query per riga. ``.order_by()``
    esplicito perche' ``SchedaSicurezza.Meta.ordering`` con ``values_list``
    trascinerebbe la colonna di ordinamento nel GROUP BY (SQL Server 8127).
    """
    ids = {int(value) for value in (mansione_ids or []) if value}
    if not ids:
        return {}
    try:
        from ..models import SchedaSicurezza

        righe = (
            SchedaSicurezza.objects.filter(
                is_corrente=True,
                prodotto__attivo=True,
                prodotto__mansioni__in=ids,
            )
            .values_list("prodotto__mansioni", "prodotto_id")
            .order_by()
            .distinct()
        )
        conteggi: dict[int, int] = {}
        for mansione_id, _prodotto_id in righe:
            if mansione_id:
                conteggi[int(mansione_id)] = conteggi.get(int(mansione_id), 0) + 1
        return conteggi
    except Exception:
        logger.warning("Conteggio SDS per mansione fallito", exc_info=True)
        return {}


def prodotti_sds_per_mansione(mansione_id: int) -> list[dict]:
    """Prodotti chimici della mansione con la SDS corrente (o la sua assenza).

    Ritorna righe ``{"prodotto", "scheda", "stato"}`` con lo stesso vocabolario
    di stato della lista prodotti (``ok`` / ``warn`` = da rivedere / ``bad`` =
    senza scheda corrente), cosi' la scheda della mansione e il modulo SDS
    raccontano la stessa cosa con gli stessi colori.
    """
    if not mansione_id:
        return []
    try:
        from django.db.models import Prefetch

        from ..models import ProdottoChimico, SchedaSicurezza

        prodotti = (
            ProdottoChimico.objects.filter(attivo=True, mansioni__id=mansione_id)
            .prefetch_related(Prefetch(
                "schede",
                queryset=SchedaSicurezza.objects.filter(is_corrente=True),
                to_attr="schede_correnti",
            ))
            .order_by("nome")
        )
        righe: list[dict] = []
        for prodotto in prodotti:
            correnti = getattr(prodotto, "schede_correnti", None) or []
            scheda = correnti[0] if correnti else None
            if scheda is None:
                stato = "bad"
            elif scheda.scaduta:
                stato = "warn"
            else:
                stato = "ok"
            righe.append({"prodotto": prodotto, "scheda": scheda, "stato": stato})
        return righe
    except Exception:
        logger.warning(
            "Elenco SDS della mansione %s fallito", mansione_id, exc_info=True
        )
        return []


def _email_dipendente(legacy_anagrafica_id: int) -> str:
    """Indirizzo di notifica del dipendente (``email_notifica``, poi ``email``).

    In ``anagrafica_dipendenti`` il campo ``email`` e' il login legacy e puo'
    non essere un indirizzo: la risoluzione canonica vive in
    ``core.legacy_anagrafica.resolve_notification_email``.
    """
    try:
        from core.legacy_anagrafica import resolve_notification_email
        from core.legacy_models import AnagraficaDipendente

        riga = (
            AnagraficaDipendente.objects.filter(pk=legacy_anagrafica_id)
            .values("email", "email_notifica")
            .first()
        )
        if not riga:
            return ""
        return resolve_notification_email(
            email=str(riga.get("email") or ""),
            email_notifica=str(riga.get("email_notifica") or ""),
        )
    except Exception:
        logger.warning(
            "Risoluzione email dipendente %s per SDS fallita",
            legacy_anagrafica_id,
            exc_info=True,
        )
        return ""


def _email_cambio_mansione(
    legacy_anagrafica_id: int,
    legacy_user_id: int,
    mansione_nome: str,
    schede_mancanti: list,
) -> bool:
    """Manda al dipendente la richiesta di presa visione delle SDS della mansione.

    La notifica in-app resta il canale primario (e il gate delle preferenze);
    l'email serve a chi la mansione la cambia in reparto e non apre il portale
    da solo. Fail-open: un errore SMTP non deve far fallire lo spostamento.
    """
    destinatario = _email_dipendente(legacy_anagrafica_id)
    if not destinatario or not schede_mancanti:
        return False
    try:
        from django.conf import settings

        from core.email_utils import email_cta, email_item_cards, send_hub_mail, text_to_html
        from core.notifiche_prefs import should_notify

        if not should_notify(tipo="presa_visione", legacy_user_id=legacy_user_id):
            return False

        base = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
        url = (base + URL_SDS_DA_LEGGERE) if base else URL_SDS_DA_LEGGERE
        quante = len(schede_mancanti)
        plurale = "schede" if quante != 1 else "scheda"
        testo = (
            f"Ti è stata assegnata la mansione «{mansione_nome}».\n\n"
            f"Per questa mansione ci sono {quante} {plurale} di sicurezza (SDS) "
            "dei prodotti chimici che ti riguardano, di cui devi prendere visione.\n\n"
            "Apri il portale, leggi ciascuna scheda e conferma la presa visione: "
            "la conferma vale come tracciamento dell'avvenuta informazione "
            "(D.Lgs. 81/08).\n\n"
            f"Elenco: " + ", ".join(
                scheda.prodotto.nome for scheda in schede_mancanti[:20]
            ) + ("…" if quante > 20 else "")
        )
        cards = email_item_cards([
            {
                "title": scheda.prodotto.nome,
                "subtitle": f"Scheda di sicurezza versione {scheda.versione or '-'}",
                "accent": "#ef4444",
            }
            for scheda in schede_mancanti[:20]
        ])
        fragment = (
            text_to_html(
                f"Ti è stata assegnata la mansione «{mansione_nome}». "
                f"Per questa mansione ci sono {quante} {plurale} di sicurezza (SDS) "
                "dei prodotti chimici che ti riguardano, di cui devi prendere visione."
            )
            + '<div style="height:12px;line-height:12px;font-size:0;">&nbsp;</div>'
            + cards
            + '<div style="height:16px;line-height:16px;font-size:0;">&nbsp;</div>'
            + email_cta(
                "Apri le schede da leggere", url,
                note="Leggi ciascuna scheda e conferma la presa visione: la conferma resta registrata.",
            )
        )
        send_hub_mail(
            f"Nuova mansione «{mansione_nome}»: {quante} {plurale} di sicurezza da leggere",
            testo,
            [destinatario],
            title="Schede di sicurezza da prendere in visione",
            body_html_fragment=fragment,
            email_type="Sicurezza",
            section_label="Schede di sicurezza",
            preheader=f"{quante} {plurale} di sicurezza da confermare",
            fail_silently=True,
        )
        return True
    except Exception:
        logger.warning(
            "Email SDS per cambio mansione fallita (dipendente=%s)",
            legacy_anagrafica_id,
            exc_info=True,
        )
        return False


@dataclass
class SDSDovutePerDipendente:
    legacy_user_id: int | None
    mansione_nome: str
    da_leggere: list


def sds_da_leggere_per_dipendente(legacy_anagrafica_id: int, mansione_nome: str) -> SDSDovutePerDipendente:
    """SDS ancora da leggere per un dipendente in una data mansione (nessun effetto collaterale).

    Fattorizzato da ``notifica_cambio_mansione`` per essere riusabile anche da una
    regola del motore automazioni (calcolo del conteggio nel corpo mail), senza
    duplicare la logica di risoluzione mansione/presa-visione.
    """
    vuoto = SDSDovutePerDipendente(None, "", [])
    mansione = _mansione_per_nome(mansione_nome)
    if mansione is None:
        return vuoto
    from core.legacy_models import AnagraficaDipendente
    from core.models import Profile
    from ..models import PresaVisioneScheda, SchedaSicurezza

    legacy_user_id = (
        AnagraficaDipendente.objects.filter(pk=legacy_anagrafica_id)
        .values_list("utente_id", flat=True)
        .first()
    )
    if not legacy_user_id:
        return SDSDovutePerDipendente(None, mansione.nome, [])
    schede = list(
        SchedaSicurezza.objects.filter(
            is_corrente=True, prodotto__attivo=True, prodotto__mansioni=mansione
        ).select_related("prodotto").order_by("prodotto__nome")
    )
    if not schede:
        return SDSDovutePerDipendente(int(legacy_user_id), mansione.nome, [])
    django_user_id = (
        Profile.objects.filter(legacy_user_id=legacy_user_id, user__is_active=True)
        .values_list("user_id", flat=True)
        .first()
    )
    lette = set()
    if django_user_id:
        lette = set(
            PresaVisioneScheda.objects.filter(
                operatore_id=django_user_id,
                scheda_id__in=[scheda.pk for scheda in schede],
            ).values_list("scheda_id", flat=True)
        )
    da_leggere = [scheda for scheda in schede if scheda.pk not in lette]
    return SDSDovutePerDipendente(int(legacy_user_id), mansione.nome, da_leggere)


def notifica_cambio_mansione(
    legacy_anagrafica_id: int,
    mansione_nuova: str,
    mansione_precedente: str = "",
) -> int:
    """Avvisa il dipendente delle SDS ancora da leggere dopo il cambio mansione.

    Due canali: notifica in-app (come prima) ed **email al dipendente**, perche'
    chi lavora in reparto il portale lo apre di rado e la presa visione delle
    SDS e' un obbligo informativo con una scadenza implicita — l'inizio della
    nuova mansione. Entrambe puntano a ``/schede-sicurezza/da-leggere/``, dove
    la conferma incrementa il contatore delle prese visione.
    """
    if (mansione_nuova or "").strip().casefold() == (mansione_precedente or "").strip().casefold():
        return 0
    try:
        from core.notifiche import invia_notifica

        dovute = sds_da_leggere_per_dipendente(legacy_anagrafica_id, mansione_nuova)
        if not dovute.legacy_user_id or not dovute.da_leggere:
            return 0
        mancanti = len(dovute.da_leggere)
        invia_notifica(
            dovute.legacy_user_id,
            "presa_visione",
            (
                f"Nuova mansione '{dovute.mansione_nome}': hai {mancanti} "
                f"{'schede' if mancanti != 1 else 'scheda'} di sicurezza da prendere in visione."
            ),
            url_azione=URL_SDS_DA_LEGGERE,
        )
        _email_cambio_mansione(
            legacy_anagrafica_id, dovute.legacy_user_id, dovute.mansione_nome, dovute.da_leggere
        )
        return mancanti
    except Exception:
        logger.warning(
            "Notifica SDS per cambio mansione fallita (dipendente=%s, mansione=%s)",
            legacy_anagrafica_id,
            mansione_nuova,
            exc_info=True,
        )
        return 0
