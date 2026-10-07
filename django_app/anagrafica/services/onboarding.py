"""Pratiche di onboarding: piano di inserimento a fasi con scadenze.

La pratica raccoglie tutto ciò che va fatto perché un nuovo assunto entri in
servizio in regola, diviso nelle fasi di un gestionale HR:

- **Prima dell'ingresso**: documenti, comunicazione UNILAV, visite della
  mansione (visita preventiva, D.Lgs. 81/2008 art. 41 c. 2 lett. a), account;
- **Primo giorno**: badge, accoglienza e tutor, DPI della mansione (art. 77);
- **Prima settimana**: presa visione delle schede di sicurezza;
- **Primi 60 giorni**: corsi obbligatori (formazione entro 60 giorni
  dall'assunzione, Accordo Stato-Regioni), colloquio di inserimento a 30 giorni;
- **Fine periodo di prova**: valutazione ed esito.

Le scadenze si calcolano dalla data di ingresso (e dalla fine prova, letta dal
contratto in anagrafica aziendale). Visite, corsi, DPI, schede di sicurezza e
account sono **voci puntuali che si chiudono da sole** quando il portale registra
visita, corso, consegna, presa visione o account (:func:`aggiorna_pratiche`,
stessa verifica del piano cambio mansione); le altre si chiudono a mano.

La pratica può nascere **prima** che il dipendente esista (offerta accettata in
Recruiting): resta in «pre-ingresso» senza ``legacy_anagrafica_id`` e si
collega al dipendente all'assunzione (:func:`collega_dipendente`). La chiusura
non tocca il record legacy/aziendale; con voci non completate la pratica si
chiude in ``CHIUSA_CON_ECCEZIONI``.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Iterable

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import mansionario
from ..models import OnboardingOffboardingCampo, OnboardingPratica, OnboardingTask

logger = logging.getLogger(__name__)

T = OnboardingTask

# Ordine delle fasi e scadenza standard di ogni fase rispetto all'ingresso.
FASI_ORDINE = [T.FASE_PRE, T.FASE_GIORNO1, T.FASE_SETTIMANA1, T.FASE_60GG, T.FASE_PROVA]
FASI_OFFSET_GIORNI = {
    T.FASE_PRE: -1,          # UNILAV entro il giorno precedente l'inizio
    T.FASE_GIORNO1: 0,
    T.FASE_SETTIMANA1: 7,
    T.FASE_60GG: 60,
}
# Voci con una scadenza propria dentro la fase.
OFFSET_PER_CODICE = {
    "responsabile_colloquio_30gg": 30,
}
GIORNI_PRIMA_FINE_PROVA = {
    "responsabile_valutazione_prova": 7,
    "hr_esito_prova": 0,
}

# Voci manuali sempre presenti. Visite, DPI, corsi e SDS vengono dalla mansione
# (:func:`_voci_mansione`); se la mansione non è a catalogo restano i fallback.
TASK_BASE = [
    {"codice": "hr_documenti_assunzione", "fase": T.FASE_PRE, "categoria": T.CATEGORIA_HR,
     "titolo": "Raccogliere i documenti per l'assunzione",
     "descrizione": "Documento d'identità, codice fiscale, IBAN, permesso di soggiorno se dovuto, "
                    "consenso privacy e contratto firmato."},
    {"codice": "amm_unilav", "fase": T.FASE_PRE, "categoria": T.CATEGORIA_AMMINISTRAZIONE,
     "titolo": "Inviare la comunicazione obbligatoria di assunzione (UNILAV)",
     "descrizione": "Da trasmettere entro il giorno precedente l'inizio del rapporto di lavoro."},
    {"codice": "it_account_ad", "fase": T.FASE_PRE, "categoria": T.CATEGORIA_IT, "tipo": T.TIPO_ACCOUNT,
     "titolo": "Creare account AD, email e accessi applicativi",
     "descrizione": "Utenza Active Directory, casella email, gruppi e accesso al portale. "
                    "Si chiude da sola quando l'account del portale è collegato al dipendente."},
    {"codice": "hr_badge_accessi", "fase": T.FASE_GIORNO1, "categoria": T.CATEGORIA_HR,
     "titolo": "Consegnare badge e accessi fisici",
     "descrizione": "Emettere badge, chiavi e abilitare i varchi necessari alla mansione."},
    {"codice": "responsabile_postazione_affiancamento", "fase": T.FASE_GIORNO1, "categoria": T.CATEGORIA_RESPONSABILE,
     "titolo": "Accogliere in reparto, preparare la postazione e assegnare il tutor",
     "descrizione": "Presentazione del reparto, postazione e strumenti pronti, affiancamento iniziale."},
    {"codice": "hr_informativa_regolamento", "fase": T.FASE_GIORNO1, "categoria": T.CATEGORIA_HR,
     "titolo": "Consegnare informativa privacy e regolamento aziendale",
     "descrizione": "Con firma per ricevuta."},
    {"codice": "responsabile_colloquio_30gg", "fase": T.FASE_60GG, "categoria": T.CATEGORIA_RESPONSABILE,
     "titolo": "Colloquio di inserimento a 30 giorni",
     "descrizione": "Verificare con il nuovo assunto e il tutor come procede l'inserimento."},
    {"codice": "responsabile_valutazione_prova", "fase": T.FASE_PROVA, "categoria": T.CATEGORIA_RESPONSABILE,
     "titolo": "Valutazione di fine periodo di prova",
     "descrizione": "Giudizio del responsabile, da dare almeno una settimana prima della fine della prova."},
    {"codice": "hr_esito_prova", "fase": T.FASE_PROVA, "categoria": T.CATEGORIA_HR,
     "titolo": "Registrare l'esito del periodo di prova",
     "descrizione": "Superamento o recesso, comunicato per iscritto entro la fine della prova."},
]

# Fallback quando la mansione non ha requisiti a catalogo.
TASK_FALLBACK = {
    "visita": {"codice": "visita_preassuntiva", "fase": T.FASE_PRE, "categoria": T.CATEGORIA_HR,
               "tipo": T.TIPO_VISITA,
               "titolo": "Programmare la visita medica preventiva",
               "descrizione": "Con il medico competente, prima dell'adibizione alla mansione. "
                              "Si chiude da sola quando la visita è registrata."},
    "dpi": {"codice": "dpi_consegna_iniziale", "fase": T.FASE_GIORNO1, "categoria": T.CATEGORIA_DPI,
            "titolo": "Consegnare i DPI previsti dal mansionario",
            "descrizione": "Verificare e consegnare i DPI obbligatori per la mansione, con firma di consegna."},
    "corsi": {"codice": "formazione_corsi_obbligatori", "fase": T.FASE_60GG, "categoria": T.CATEGORIA_HR,
              "titolo": "Iscrivere ai corsi di formazione obbligatori",
              "descrizione": "Formazione generale e specifica entro 60 giorni dall'assunzione."},
}


def _workflow_task_code(field_key: str) -> str:
    safe = "".join(
        ch if ch.isalnum() else "_"
        for ch in (field_key or "").strip().lower()
    ).strip("_")
    return f"campo_{safe or 'configurato'}"[:60]


def _configured_field_tasks() -> list[dict[str, Any]]:
    """Task derivati dai campi configurati per la fase ONBOARDING (prima dell'ingresso)."""
    configured = OnboardingOffboardingCampo.objects.filter(
        fase=OnboardingOffboardingCampo.FASE_ONBOARDING,
        is_active=True,
    ).order_by("ordine", "campo_label")
    tasks: list[dict[str, Any]] = []
    for item in configured:
        parts = []
        if item.sezione:
            parts.append(f"Sezione + Nuovo dipendente: {item.sezione}.")
        if item.note:
            parts.append(item.note)
        if item.obbligatorio:
            parts.append("Campo marcato come obbligatorio nel workflow.")
        tasks.append({
            "codice": _workflow_task_code(item.campo_key),
            "fase": T.FASE_PRE,
            "categoria": item.categoria,
            "titolo": f"Verificare {item.campo_label}",
            "descrizione": " ".join(parts).strip(),
        })
    return tasks


def _categorie_dpi_obbligatorie() -> list[str]:
    """Nomi delle categorie DPI obbligatorie da mansionario (vuoto se modulo assente)."""
    try:
        from dpi.models import CategoriaDPI
    except Exception:
        return []
    return list(
        CategoriaDPI.objects
        .filter(is_active=True, obbligatoria_mansionario=True)
        .order_by("order_index", "nome")
        .values_list("nome", flat=True)
    )


def _corsi_obbligatori(
    legacy_id: int | None,
    mansione_nome: str,
    reparto_nome: str,
    ruolo_ids: Iterable[int] | None,
) -> list[str]:
    """Titoli dei corsi/piani obbligatori dalle ``TrainingRequirementRule`` (fallback).

    Match difensivo su regole attive e obbligatorie per mansione (nome), ruoli
    operativi o singolo dipendente. Se nulla matcha ritorna lista vuota.
    """
    from ..models_formazione import TrainingRequirementRule

    conds: list[Q] = []
    if legacy_id:
        conds.append(Q(legacy_anagrafica_id=legacy_id))
    if mansione_nome:
        conds.append(Q(mansione__nome__iexact=mansione_nome.strip()))
    ruolo_ids = [int(r) for r in (ruolo_ids or []) if r]
    if ruolo_ids:
        conds.append(Q(ruolo_operativo_id__in=ruolo_ids))
    if not conds:
        return []

    query = conds[0]
    for cond in conds[1:]:
        query |= cond

    titoli: list[str] = []
    for rule in (
        TrainingRequirementRule.objects
        .filter(query, is_active=True, is_mandatory=True)
        .select_related("corso", "piano")
    ):
        if rule.corso_id and rule.corso:
            titoli.append(rule.corso.titolo)
        elif rule.piano_id and rule.piano:
            titoli.append(f"Piano: {rule.piano.nome}")

    seen: set[str] = set()
    out: list[str] = []
    for titolo in titoli:
        if titolo not in seen:
            seen.add(titolo)
            out.append(titolo)
    return out


def _sds_della_mansione(mansione: str) -> int:
    """Quante schede di sicurezza correnti sono dovute per la mansione (0 se nessuna)."""
    if not mansione:
        return 0
    try:
        from schede_sicurezza.services.assegnazioni import _mansione_per_nome, conteggio_sds_per_mansione
        m = _mansione_per_nome(mansione)
        return conteggio_sds_per_mansione([m.pk]).get(m.pk, 0) if m else 0
    except Exception:
        logger.debug("Conteggio SDS per mansione %s non disponibile", mansione, exc_info=True)
        return 0


def _voci_mansione(*, legacy_id, mansione: str, reparto: str, ruolo_ids) -> list[dict[str, Any]]:
    """Voci puntuali dalla mansione: una per visita, DPI, corso; più le SDS.

    Se la mansione non ha un requisito a catalogo resta la voce generica di
    fallback (con le regole formative o il flag DPI globale in descrizione).
    """
    requisiti = mansionario.requisiti_per_nome_mansione(mansione) if mansione else mansionario.requisiti_vuoti()
    voci: list[dict[str, Any]] = []

    visite = requisiti.get("visite") or []
    for tipo in visite:
        voci.append({"codice": f"visita_{tipo.pk}", "fase": T.FASE_PRE, "categoria": T.CATEGORIA_HR,
                     "tipo": T.TIPO_VISITA, "riferimento_id": tipo.pk,
                     "titolo": f"Visita medica: {tipo.nome}",
                     "descrizione": "Prima dell'adibizione alla mansione (visita preventiva). "
                                    "Si chiude da sola quando la visita è registrata."})
    if not visite:
        voci.append(dict(TASK_FALLBACK["visita"]))

    categorie = requisiti.get("dpi") or []
    for cat in categorie:
        voci.append({"codice": f"dpi_{cat.pk}", "fase": T.FASE_GIORNO1, "categoria": T.CATEGORIA_DPI,
                     "tipo": T.TIPO_DPI, "riferimento_id": cat.pk,
                     "titolo": f"Consegnare DPI: {cat.nome}",
                     "descrizione": "Si chiude da sola quando la consegna è registrata nel modulo DPI."})
    if not categorie:
        voce = dict(TASK_FALLBACK["dpi"])
        globali = _categorie_dpi_obbligatorie()
        if globali:
            voce["descrizione"] += " Categorie obbligatorie: " + ", ".join(globali) + "."
        voci.append(voce)

    corsi = requisiti.get("corsi") or []
    for corso in corsi:
        voci.append({"codice": f"corso_{corso.pk}", "fase": T.FASE_60GG, "categoria": T.CATEGORIA_HR,
                     "tipo": T.TIPO_FORMAZIONE, "riferimento_id": corso.pk,
                     "titolo": f"Corso: {corso.titolo}",
                     "descrizione": "Entro 60 giorni dall'assunzione. Si chiude da sola quando il corso "
                                    "risulta completato (anche formazione pregressa)."})
    for piano in requisiti.get("piani") or []:
        voci.append({"codice": f"piano_{piano.pk}", "fase": T.FASE_60GG, "categoria": T.CATEGORIA_HR,
                     "titolo": f"Piano formativo: {piano.nome}",
                     "descrizione": "Iscrivere ai corsi del piano previsto per la mansione."})
    if not corsi and not requisiti.get("piani"):
        voce = dict(TASK_FALLBACK["corsi"])
        regole = _corsi_obbligatori(legacy_id, mansione, reparto, ruolo_ids)
        if regole:
            voce["descrizione"] += " Corsi obbligatori applicabili: " + ", ".join(regole) + "."
        voci.append(voce)

    n_sds = _sds_della_mansione(mansione)
    if n_sds:
        voci.append({"codice": "sds_presa_visione", "fase": T.FASE_SETTIMANA1, "categoria": T.CATEGORIA_DPI,
                     "tipo": T.TIPO_SDS,
                     "titolo": f"Presa visione delle schede di sicurezza ({n_sds})",
                     "descrizione": "Prodotti chimici della mansione. Si chiude da sola quando "
                                    "tutte le schede risultano lette dal portale."})
    return voci


def task_definitions(
    *,
    legacy_id: int | None = None,
    mansione: str = "",
    reparto: str = "",
    ruolo_ids: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    """Voci della pratica, già ordinate per fase (dict pronti per ``OnboardingTask``)."""
    voci = [dict(t) for t in TASK_BASE]
    voci += _voci_mansione(legacy_id=legacy_id, mansione=mansione, reparto=reparto, ruolo_ids=ruolo_ids)
    codici = {v["codice"] for v in voci}
    for voce in _configured_field_tasks():
        if voce["codice"] not in codici:
            voci.append(voce)
            codici.add(voce["codice"])

    posizione = {fase: i for i, fase in enumerate(FASI_ORDINE)}
    for i, voce in enumerate(voci):
        voce.setdefault("tipo", T.TIPO_MANUALE)
        voce.setdefault("riferimento_id", None)
        voce["ordine"] = posizione[voce["fase"]] * 100 + i
    voci.sort(key=lambda v: v["ordine"])
    return voci


def scadenza_voce(fase: str, codice: str, ingresso: date | None, fine_prova: date | None) -> date | None:
    """Scadenza di una voce dalla data di ingresso (o dalla fine prova)."""
    if fase == T.FASE_PROVA:
        if not fine_prova:
            return None
        return fine_prova - timedelta(days=GIORNI_PRIMA_FINE_PROVA.get(codice, 0))
    if not ingresso:
        return None
    giorni = OFFSET_PER_CODICE.get(codice, FASI_OFFSET_GIORNI.get(fase, 0))
    return ingresso + timedelta(days=giorni)


def fine_prova_da_contratto(legacy_id: int | None) -> date | None:
    """Fine del periodo di prova registrata in anagrafica aziendale, se c'è."""
    if not legacy_id:
        return None
    from ..models import DipendenteAnagraficaAziendale
    return (
        DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id)
        .values_list("prova_data_fine", flat=True).first()
    )


def genera_task_pratica(pratica: OnboardingPratica, *, ruolo_ids: Iterable[int] | None = None) -> int:
    """Crea le voci mancanti della pratica (idempotente per codice). Ritorna quante ne crea."""
    esistenti = set(pratica.tasks.values_list("codice", flat=True))
    nuove = [
        OnboardingTask(
            pratica=pratica,
            codice=voce["codice"],
            categoria=voce["categoria"],
            titolo=voce["titolo"][:200],
            descrizione=voce["descrizione"],
            fase=voce["fase"],
            ordine=voce["ordine"],
            tipo=voce["tipo"],
            riferimento_id=voce["riferimento_id"],
            scadenza=scadenza_voce(voce["fase"], voce["codice"], pratica.data_assunzione, pratica.fine_prova),
        )
        for voce in task_definitions(
            legacy_id=pratica.legacy_anagrafica_id,
            mansione=pratica.mansione,
            reparto=pratica.reparto,
            ruolo_ids=ruolo_ids,
        )
        if voce["codice"] not in esistenti
    ]
    # Uno per volta: su SQL Server un INSERT a lotti con un solo scarto
    # invaliderebbe l'intera transazione (vedi bulk + savepoint).
    for task in nuove:
        task.save()
    return len(nuove)


def ricalcola_scadenze(pratica: OnboardingPratica) -> int:
    """Riallinea le scadenze delle voci aperte a ingresso e fine prova correnti."""
    aggiornate = 0
    for task in pratica.tasks.filter(stato=OnboardingTask.STATO_DA_FARE):
        nuova = scadenza_voce(task.fase, task.codice, pratica.data_assunzione, pratica.fine_prova)
        if nuova != task.scadenza:
            task.scadenza = nuova
            task.save(update_fields=["scadenza", "updated_at"])
            aggiornate += 1
    return aggiornate


def _caporeparto_emails(reparto_nome: str) -> list[str]:
    """Email di notifica del caporeparto del reparto (CAR), se presente.

    NB responsabile effettivo: quando un'area aziendale ha un responsabile
    diverso dal caporeparto, la fonte preferenziale a valle è il denormalizzato
    ``DipendenteAnagraficaAziendale.caporeparto_legacy_id`` (già scritto dal
    responsabile effettivo in :func:`anagrafica.views._sync_aziendale_from_reparto`).
    Questo helper resta a livello di reparto: notifica il CAR del reparto, dato
    che riceve solo il nome reparto (nessuna area nel contesto).
    """
    if not reparto_nome:
        return []
    try:
        from core.legacy_models import AnagraficaDipendente
        from ..models import Reparto
        rep = Reparto.objects.filter(nome__iexact=reparto_nome.strip()).first()
        if not rep or not rep.caporeparto_legacy_id:
            return []
        # NB: in anagrafica_dipendenti `email` è il login legacy → usare email_notifica.
        email = (
            AnagraficaDipendente.objects
            .filter(id=rep.caporeparto_legacy_id)
            .values_list("email_notifica", flat=True)
            .first()
        ) or ""
        return [email.strip()] if email.strip() else []
    except Exception:
        logger.debug("Risoluzione email caporeparto fallita per reparto=%s", reparto_nome, exc_info=True)
        return []


from automazioni.managed_flows import event_flow


@event_flow("onboarding_dpi_rischio", skipped_result=None)
def notifica_assegnazione_mansione_rischio(
    *,
    dipendente_nome: str,
    mansione: str,
    reparto: str = "",
    requisiti: dict | None = None,
) -> None:
    """All'assegnazione di una mansione con requisiti DPI notifica via email
    AMM (DPI da distribuire) e CAR/caporeparto (controllo uso effettivo DPI).

    Fail-open: nessuna eccezione propagata (l'onboarding non deve rompersi se
    la mail non parte). Non invia nulla se la mansione non richiede DPI.
    """
    try:
        from core.email_utils import send_hub_mail
        from .reminders import get_reminder_recipients

        if requisiti is None:
            requisiti = (
                mansionario.requisiti_per_nome_mansione(mansione)
                if mansione else mansionario.requisiti_vuoti()
            )
        categorie = [c.nome for c in requisiti.get("dpi", [])]
        if not categorie:
            return  # non è una mansione di rischio (nessun DPI richiesto)

        elenco = ", ".join(categorie)
        nome = dipendente_nome or "nuovo assunto"
        rep_txt = f" — reparto {reparto}" if reparto else ""

        amm = get_reminder_recipients("dpi_amm_emails")
        if amm:
            send_hub_mail(
                subject=f"[DPI] Da distribuire — {nome} ({mansione})",
                body_text=(
                    f"Assegnata la mansione «{mansione}» a {nome}{rep_txt}.\n\n"
                    f"DPI da preparare e consegnare: {elenco}."
                ),
                recipients=amm,
                title="DPI da distribuire",
                email_type="Anagrafica HR",
                section_label="Onboarding",
                fail_silently=True,
            )

        car = _caporeparto_emails(reparto) or get_reminder_recipients("dpi_car_emails")
        if car:
            send_hub_mail(
                subject=f"[DPI] Controllo uso — {nome} ({mansione})",
                body_text=(
                    f"{nome} è stato assegnato alla mansione «{mansione}»{rep_txt}.\n\n"
                    f"Verificare l'uso effettivo dei DPI previsti: {elenco}."
                ),
                recipients=car,
                title="Controllo uso DPI",
                email_type="Anagrafica HR",
                section_label="Onboarding",
                fail_silently=True,
            )
    except Exception:
        logger.warning("Notifica mansione di rischio fallita (mansione=%s)", mansione, exc_info=True)


def registra_formazione_pregressa(
    legacy_id: int,
    items: Iterable[dict[str, Any]],
    *,
    user=None,
) -> int:
    """Registra la formazione sicurezza pregressa dichiarata in preinserimento.

    ``items`` = iterabile di ``{"corso_id": int, "data": date}``. Per ogni corso
    crea un ``TrainingEmployeeRecord`` con gli snapshot storici e marca la
    scadenza formazione da ricalcolare. Ritorna il numero di record creati.
    Idempotente: salta i corsi già presenti nello storico del dipendente.
    """
    from ..models import _add_months
    from ..models_formazione import TrainingDeadline, TrainingEmployeeRecord

    items = [it for it in (items or []) if it.get("corso_id") and it.get("data")]
    if not items:
        return 0

    creati = 0
    for it in items:
        corso_id = int(it["corso_id"])
        data = it["data"]
        if TrainingEmployeeRecord.objects.filter(
            legacy_anagrafica_id=legacy_id, corso_id=corso_id
        ).exists():
            continue
        try:
            from ..models_formazione import TrainingCourse
            corso = TrainingCourse.objects.select_related("piano").filter(pk=corso_id).first()
            if corso is None:
                continue
            validita = corso.validita_mesi or 0
            scad = _add_months(data, validita) if validita > 0 else None
            TrainingEmployeeRecord.objects.create(
                corso=corso,
                legacy_anagrafica_id=legacy_id,
                data_completamento=data,
                idoneo=True,
                data_scadenza=scad,
                validato_da=user,
                validato_il=timezone.localdate(),
                note="Formazione pregressa dichiarata in preinserimento.",
                course_code_snapshot=corso.codice,
                course_title_snapshot=corso.titolo,
                course_version_snapshot=corso.versione,
                plan_code_snapshot=corso.piano.codice if corso.piano_id else "",
                plan_name_snapshot=corso.piano.nome if corso.piano_id else "",
                validity_months_snapshot=validita,
            )
            TrainingDeadline.objects.filter(
                legacy_anagrafica_id=legacy_id, corso_id=corso_id
            ).update(needs_refresh=True)
            creati += 1
        except Exception:
            logger.warning("Registrazione formazione pregressa fallita (corso=%s)", corso_id, exc_info=True)
    return creati


def avvia_onboarding(
    *,
    legacy_id: int | None,
    dipendente_nome: str,
    reparto: str = "",
    mansione: str = "",
    data_assunzione=None,
    fine_prova=None,
    note_hr: str = "",
    user=None,
    ruolo_ids: Iterable[int] | None = None,
    notifica_dpi: bool = True,
) -> OnboardingPratica:
    """Crea una pratica onboarding con il piano a fasi, in transazione.

    ``legacy_id`` può mancare (pre-ingresso da offerta accettata): la pratica si
    collega al dipendente con :func:`collega_dipendente`. Se ``notifica_dpi`` e
    la mansione richiede DPI, avvisa AMM e caporeparto (fuori transazione).
    """
    with transaction.atomic():
        pratica = OnboardingPratica.objects.create(
            legacy_anagrafica_id=legacy_id or None,
            dipendente_nome=dipendente_nome,
            reparto=reparto,
            mansione=mansione,
            data_assunzione=data_assunzione,
            fine_prova=fine_prova or fine_prova_da_contratto(legacy_id),
            note_hr=note_hr,
            created_by=user,
            updated_by=user,
        )
        genera_task_pratica(pratica, ruolo_ids=ruolo_ids)
    if legacy_id:
        aggiorna_pratiche(pratiche=[pratica])
    if notifica_dpi:
        notifica_assegnazione_mansione_rischio(
            dipendente_nome=dipendente_nome, mansione=mansione, reparto=reparto,
        )
    return pratica


def collega_dipendente(pratica: OnboardingPratica, legacy_id: int, *, user=None,
                       reparto: str = "", mansione: str = "", data_assunzione=None) -> OnboardingPratica:
    """Aggancia una pratica di pre-ingresso al dipendente appena creato.

    Aggiorna i dati che all'offerta potevano mancare, aggiunge le voci che
    dipendono dalla persona e verifica subito quelle già soddisfatte.
    """
    pratica.legacy_anagrafica_id = int(legacy_id)
    if reparto:
        pratica.reparto = reparto
    if mansione:
        pratica.mansione = mansione
    if data_assunzione:
        pratica.data_assunzione = data_assunzione
    pratica.fine_prova = pratica.fine_prova or fine_prova_da_contratto(legacy_id)
    pratica.updated_by = user
    pratica.save(update_fields=[
        "legacy_anagrafica_id", "reparto", "mansione", "data_assunzione", "fine_prova",
        "updated_by", "updated_at",
    ])
    genera_task_pratica(pratica)
    ricalcola_scadenze(pratica)
    aggiorna_pratiche(pratiche=[pratica])
    return pratica


def pratica_aperta(legacy_id: int) -> OnboardingPratica | None:
    return (
        OnboardingPratica.objects
        .filter(legacy_anagrafica_id=legacy_id, stato__in=OnboardingPratica.STATI_APERTI)
        .order_by("-created_at")
        .first()
    )


def chiudi_pratica(pratica: OnboardingPratica, *, user=None) -> str:
    """Chiude la pratica. CHIUSA se tutti i task sono completati, altrimenti
    CHIUSA_CON_ECCEZIONI (task ancora da fare o marcati eccezione). Non blocca.
    Ritorna lo stato finale.
    """
    tasks = list(pratica.tasks.all())
    ha_non_completati = any(t.stato != OnboardingTask.STATO_COMPLETATO for t in tasks)
    pratica.stato = (
        OnboardingPratica.STATO_CHIUSA_CON_ECCEZIONI if ha_non_completati
        else OnboardingPratica.STATO_CHIUSA
    )
    pratica.closed_at = timezone.now()
    pratica.closed_by = user
    pratica.updated_by = user
    pratica.save(update_fields=["stato", "closed_at", "closed_by", "updated_by", "updated_at"])
    return pratica.stato


def annulla_pratica(pratica: OnboardingPratica, *, user=None) -> None:
    pratica.stato = OnboardingPratica.STATO_ANNULLATA
    pratica.closed_at = timezone.now()
    pratica.closed_by = user
    pratica.updated_by = user
    pratica.save(update_fields=["stato", "closed_at", "closed_by", "updated_by", "updated_at"])


# ═══════════════════════════════════════════════════════════════════════════
# Chiusura automatica delle voci verificabili
# ═══════════════════════════════════════════════════════════════════════════

def _account_collegato(legacy_ids: Iterable[int]) -> bool:
    from core.legacy_models import AnagraficaDipendente
    return AnagraficaDipendente.objects.filter(pk__in=list(legacy_ids), utente_id__isnull=False).exists()


def aggiorna_pratiche(*, pratiche: Iterable[OnboardingPratica] | None = None,
                      legacy_ids: Iterable[int] | None = None) -> dict[str, int]:
    """Chiude le voci aperte il cui requisito ora risulta soddisfatto.

    Gira ogni notte e alla consultazione di cruscotto e pratica. Le pratiche in
    pre-ingresso (senza dipendente) non hanno nulla da verificare.
    """
    from . import requisiti
    from .cambio_mansione import requisito_soddisfatto

    if pratiche is None:
        qs = OnboardingPratica.objects.filter(
            stato__in=OnboardingPratica.STATI_APERTI, legacy_anagrafica_id__isnull=False,
        )
        if legacy_ids is not None:
            qs = qs.filter(legacy_anagrafica_id__in=[int(i) for i in legacy_ids])
        pratiche = list(qs)
    pratiche = [p for p in pratiche if p.legacy_anagrafica_id and p.is_aperta]
    task_aperti = list(
        OnboardingTask.objects.filter(pratica__in=pratiche, stato=OnboardingTask.STATO_DA_FARE)
        .exclude(tipo=OnboardingTask.TIPO_MANUALE).select_related("pratica")
    )
    if not task_aperti:
        return {"controllati": 0, "chiusi": 0}

    ctx = requisiti.ambito()
    tutti = {d.id: d for d in ctx._tutti()}
    chiusi = 0
    for task in task_aperti:
        pratica = task.pratica
        persona = tutti.get(ctx.canonico(pratica.legacy_anagrafica_id))
        if persona is None:
            continue
        try:
            if task.tipo == OnboardingTask.TIPO_ACCOUNT:
                motivo = "Account del portale collegato" if _account_collegato(persona.tutti_gli_id) else ""
            else:
                motivo = requisito_soddisfatto(
                    task.tipo, task.riferimento_id, ctx=ctx, persona=persona,
                    dal=pratica.created_at.date(), mansione=pratica.mansione,
                )
        except Exception:
            logger.exception("verifica voce onboarding %s fallita", task.pk)
            continue
        if motivo:
            task.stato = OnboardingTask.STATO_COMPLETATO
            task.completed_at = timezone.now()
            task.completed_by = None
            task.chiusura_automatica = True
            task.chiusura_nota = motivo[:300]
            task.save(update_fields=[
                "stato", "completed_at", "completed_by", "chiusura_automatica", "chiusura_nota", "updated_at",
            ])
            chiusi += 1
    return {"controllati": len(task_aperti), "chiusi": chiusi}


# ═══════════════════════════════════════════════════════════════════════════
# Riepilogo per cruscotto e pratica
# ═══════════════════════════════════════════════════════════════════════════

def riepilogo(pratica: OnboardingPratica, tasks: list[OnboardingTask] | None = None) -> dict[str, Any]:
    """Avanzamento, fase corrente, prossima scadenza e ritardi della pratica."""
    tasks = list(pratica.tasks.all()) if tasks is None else tasks
    oggi = timezone.localdate()
    aperti = [t for t in tasks if t.stato == OnboardingTask.STATO_DA_FARE]
    completati = sum(1 for t in tasks if t.stato == OnboardingTask.STATO_COMPLETATO)
    eccezioni = sum(1 for t in tasks if t.stato == OnboardingTask.STATO_ECCEZIONE)
    fatti = completati + eccezioni
    in_ritardo = [t for t in aperti if t.scadenza and t.scadenza < oggi]
    con_scadenza = sorted((t for t in aperti if t.scadenza), key=lambda t: t.scadenza)
    fasi_aperte = [f for f in FASI_ORDINE if any(t.fase == f for t in aperti)]
    etichette = dict(OnboardingTask.FASE_CHOICES)
    return {
        "totale": len(tasks),
        "da_fare": len(aperti),
        "completati": completati,
        "eccezioni": eccezioni,
        "percentuale": round(fatti * 100 / len(tasks)) if tasks else 0,
        "in_ritardo": len(in_ritardo),
        "prossima": con_scadenza[0] if con_scadenza else None,
        "fase_corrente": etichette.get(fasi_aperte[0], "") if fasi_aperte else "",
        "responsabili": sorted({t.get_categoria_display() for t in aperti}),
    }


def fasi_con_voci(pratica: OnboardingPratica, tasks: list[OnboardingTask]) -> list[dict[str, Any]]:
    """Voci raggruppate per fase, con la data di riferimento di ciascuna fase."""
    etichette = dict(OnboardingTask.FASE_CHOICES)
    out = []
    for fase in FASI_ORDINE:
        voci = [t for t in tasks if t.fase == fase]
        if not voci:
            continue
        out.append({
            "codice": fase,
            "label": etichette[fase],
            "data": scadenza_voce(fase, "", pratica.data_assunzione, pratica.fine_prova),
            "voci": voci,
            "fatte": sum(1 for t in voci if t.stato != OnboardingTask.STATO_DA_FARE),
        })
    return out
