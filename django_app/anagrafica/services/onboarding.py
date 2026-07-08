"""Generazione e chiusura delle pratiche di onboarding (H1).

Speculare al flusso offboarding ma con logica dedicata: la checklist di
inserimento è composta da un nucleo di task standard (account, badge, DPI da
mansionario, corsi obbligatori, visita preassuntiva) arricchito dai campi
configurati in ``OnboardingOffboardingCampo`` con ``fase=ONBOARDING``.

A differenza dell'offboarding la chiusura non tocca il record legacy/aziendale:
serve solo a tracciare il completamento della presa in carico. Una pratica con
task non completati si chiude comunque, ma in stato ``CHIUSA_CON_ECCEZIONI``.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import mansionario
from ..models import OnboardingOffboardingCampo, OnboardingPratica, OnboardingTask

logger = logging.getLogger(__name__)


# Task standard sempre creati. Le descrizioni di DPI e formazione vengono
# arricchite dinamicamente in base a mansione/area/ruoli del dipendente.
TASK_BASE = [
    {
        "codice": "it_account_ad",
        "categoria": OnboardingTask.CATEGORIA_IT,
        "titolo": "Creare account AD, email e accessi applicativi",
        "descrizione": "Predisporre utenza Active Directory, casella email, gruppi e credenziali dei portali necessari.",
    },
    {
        "codice": "hr_badge_accessi",
        "categoria": OnboardingTask.CATEGORIA_HR,
        "titolo": "Consegnare badge e accessi fisici",
        "descrizione": "Emettere badge, chiavi e abilitare i varchi/tornelli necessari alla mansione.",
    },
    {
        "codice": "dpi_consegna_iniziale",
        "categoria": OnboardingTask.CATEGORIA_DPI,
        "titolo": "Consegnare i DPI previsti dal mansionario",
        "descrizione": "Verificare e consegnare i DPI obbligatori per la mansione, con firma di consegna.",
    },
    {
        "codice": "formazione_corsi_obbligatori",
        "categoria": OnboardingTask.CATEGORIA_RESPONSABILE,
        "titolo": "Iscrivere ai corsi di formazione obbligatori",
        "descrizione": "Pianificare l'iscrizione ai corsi obbligatori previsti per mansione/area/ruoli.",
    },
    {
        "codice": "visita_preassuntiva",
        "categoria": OnboardingTask.CATEGORIA_HR,
        "titolo": "Programmare la visita medica preassuntiva",
        "descrizione": "Fissare la visita con il medico competente prima dell'avvio in mansione.",
    },
    {
        "codice": "responsabile_postazione_affiancamento",
        "categoria": OnboardingTask.CATEGORIA_RESPONSABILE,
        "titolo": "Preparare postazione e affiancamento",
        "descrizione": "Predisporre postazione/strumenti e organizzare l'affiancamento iniziale in reparto.",
    },
]


def _workflow_task_code(field_key: str) -> str:
    safe = "".join(
        ch if ch.isalnum() else "_"
        for ch in (field_key or "").strip().lower()
    ).strip("_")
    return f"campo_{safe or 'configurato'}"[:60]


def _configured_field_tasks() -> list[dict[str, Any]]:
    """Task derivati dai campi configurati per la fase ONBOARDING."""
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
    """Titoli dei corsi/piani obbligatori applicabili al dipendente.

    Match difensivo su ``TrainingRequirementRule`` attive e obbligatorie per
    mansione (nome), ruoli operativi o singolo dipendente. Se nulla matcha
    ritorna lista vuota.

    Nota: il match per area aziendale derivata dal reparto non è più
    possibile dopo l'inversione della gerarchia Reparto/AreaAziendale (un
    Reparto ha ora più Aree aziendali figlie, non una sola) — vedi Fase 2
    nello spec `docs/superpowers/specs/2026-07-08-inversione-reparto-area-aziendale-design.md`.
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


def task_definitions(
    *,
    legacy_id: int | None = None,
    mansione: str = "",
    reparto: str = "",
    ruolo_ids: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    """Lista (dict) dei task da creare per una pratica onboarding.

    I requisiti DPI/formazione/visite sono derivati dalla "mansione di rischio"
    (``services.mansionario``); se la mansione non è a catalogo si ricade sui
    fallback legacy (flag globale DPI, regole di obbligatorietà formativa).
    """
    tasks = [dict(t) for t in TASK_BASE]
    by_code = {t["codice"]: t for t in tasks}

    requisiti = (
        mansionario.requisiti_per_nome_mansione(mansione)
        if mansione else mansionario.requisiti_vuoti()
    )

    # DPI: categorie dalla mansione di rischio, fallback al flag globale.
    categorie_dpi = [c.nome for c in requisiti["dpi"]] or _categorie_dpi_obbligatorie()
    if categorie_dpi and "dpi_consegna_iniziale" in by_code:
        by_code["dpi_consegna_iniziale"]["descrizione"] += (
            " Categorie obbligatorie per la mansione: " + ", ".join(categorie_dpi) + "."
        )

    # Formazione: corsi/piani dalla mansione di rischio, fallback alle regole.
    corsi = [c.titolo for c in requisiti["corsi"]] + [f"Piano: {p.nome}" for p in requisiti["piani"]]
    if not corsi:
        corsi = _corsi_obbligatori(legacy_id, mansione, reparto, ruolo_ids)
    if corsi and "formazione_corsi_obbligatori" in by_code:
        by_code["formazione_corsi_obbligatori"]["descrizione"] += (
            " Corsi obbligatori applicabili: " + ", ".join(corsi) + "."
        )

    # Visite mediche richieste dalla mansione di rischio.
    visite = [v.nome for v in requisiti["visite"]]
    if visite and "visita_preassuntiva" in by_code:
        by_code["visita_preassuntiva"]["descrizione"] += (
            " Visite previste per la mansione: " + ", ".join(visite) + "."
        )

    existing = set(by_code)
    for task in _configured_field_tasks():
        if task["codice"] not in existing:
            tasks.append(task)
            existing.add(task["codice"])
    return tasks


def genera_task_pratica(pratica: OnboardingPratica, *, ruolo_ids: Iterable[int] | None = None) -> int:
    """Crea i task della pratica. Ritorna il numero di task creati."""
    definizioni = task_definitions(
        legacy_id=pratica.legacy_anagrafica_id,
        mansione=pratica.mansione,
        reparto=pratica.reparto,
        ruolo_ids=ruolo_ids,
    )
    OnboardingTask.objects.bulk_create([
        OnboardingTask(
            pratica=pratica,
            codice=task["codice"],
            categoria=task["categoria"],
            titolo=task["titolo"],
            descrizione=task["descrizione"],
        )
        for task in definizioni
    ])
    return len(definizioni)


def _caporeparto_emails(reparto_nome: str) -> list[str]:
    """Email di notifica del caporeparto del reparto (CAR), se presente."""
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
    legacy_id: int,
    dipendente_nome: str,
    reparto: str = "",
    mansione: str = "",
    data_assunzione=None,
    note_hr: str = "",
    user=None,
    ruolo_ids: Iterable[int] | None = None,
    notifica_dpi: bool = True,
) -> OnboardingPratica:
    """Crea una pratica onboarding con la checklist generata, in transazione.

    Se ``notifica_dpi`` e la mansione richiede DPI, invia (fuori transazione)
    le notifiche ad AMM e al caporeparto (CAR).
    """
    with transaction.atomic():
        pratica = OnboardingPratica.objects.create(
            legacy_anagrafica_id=legacy_id,
            dipendente_nome=dipendente_nome,
            reparto=reparto,
            mansione=mansione,
            data_assunzione=data_assunzione,
            note_hr=note_hr,
            created_by=user,
            updated_by=user,
        )
        genera_task_pratica(pratica, ruolo_ids=ruolo_ids)
    if notifica_dpi:
        notifica_assegnazione_mansione_rischio(
            dipendente_nome=dipendente_nome, mansione=mansione, reparto=reparto,
        )
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
