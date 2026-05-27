"""Service layer per il calcolo delle scadenze formazione.

NON usare signal per il ricalcolo effettivo — i signal settano solo needs_refresh=True.
Questa funzione è l'unica fonte di verità per TrainingDeadline.

Copertura MVP PATCH-06:
  - TrainingEmployeeRecord (idoneo=True): calcola stato da data_scadenza.
  - TrainingRequirementRule con legacy_anagrafica_id diretto: MAI_FREQUENTATO se nessun record.
  - TODO PATCH-09: cross-reference mansione/area/ruolo con AnagraficaDipendente.
"""
from __future__ import annotations

from datetime import date


def _compute_stato(
    data_scadenza: date | None,
    validita_mesi: int,
    today: date,
) -> tuple[str, int | None]:
    """Ritorna (stato_scadenza, giorni_alla_scadenza)."""
    if validita_mesi == 0 or data_scadenza is None:
        return "UNA_TANTUM", None
    giorni = (data_scadenza - today).days
    if giorni < 0:
        return "SCADUTO", giorni
    if giorni <= 30:
        return "IN_SCADENZA_30", giorni
    if giorni <= 90:
        return "IN_SCADENZA_90", giorni
    return "VALIDO", giorni


def refresh_deadlines(
    legacy_id: int | None = None,
    corso_id: int | None = None,
) -> int:
    """Ricalcola TrainingDeadline per i filtri indicati.

    Se legacy_id e corso_id sono None ricalcola tutti i record.
    Restituisce il numero di record aggiornati/creati.
    """
    from django.db.models import Q  # noqa: PLC0415

    from anagrafica.models_formazione import (  # noqa: PLC0415
        TrainingCourse,
        TrainingDeadline,
        TrainingEmployeeRecord,
        TrainingRequirementRule,
    )

    today = date.today()
    updated = 0

    # ── 1. Ricalcola da record completamento ────────────────────────────────
    rec_qs = (
        TrainingEmployeeRecord.objects
        .filter(idoneo=True)
        .select_related("corso")
    )
    if legacy_id is not None:
        rec_qs = rec_qs.filter(legacy_anagrafica_id=legacy_id)
    if corso_id is not None:
        rec_qs = rec_qs.filter(corso_id=corso_id)

    # Per (dipendente, corso) teniamo solo il record più recente (ultimo completamento)
    pairs: dict[tuple[int, int], TrainingEmployeeRecord] = {}
    for rec in rec_qs.order_by("legacy_anagrafica_id", "corso_id", "-data_completamento"):
        key = (rec.legacy_anagrafica_id, rec.corso_id)
        if key not in pairs:
            pairs[key] = rec

    # Indice regole dirette per (legacy_id, corso_id) — per is_required
    direct_rule_map: dict[tuple[int, int], TrainingRequirementRule] = {}
    rules_idx_qs = TrainingRequirementRule.objects.filter(
        is_active=True,
        legacy_anagrafica_id__isnull=False,
        corso__isnull=False,
    ).select_related()
    if legacy_id is not None:
        rules_idx_qs = rules_idx_qs.filter(legacy_anagrafica_id=legacy_id)
    if corso_id is not None:
        rules_idx_qs = rules_idx_qs.filter(corso_id=corso_id)
    for r in rules_idx_qs:
        direct_rule_map[(r.legacy_anagrafica_id, r.corso_id)] = r

    for (lid, cid), rec in pairs.items():
        stato, giorni = _compute_stato(rec.data_scadenza, rec.corso.validita_mesi, today)
        rule = direct_rule_map.get((lid, cid))
        TrainingDeadline.objects.update_or_create(
            corso_id=cid,
            legacy_anagrafica_id=lid,
            defaults={
                "requirement_rule": rule,
                "assignment": None,
                "ultimo_completamento": rec,
                "data_ultimo_completamento": rec.data_completamento,
                "data_scadenza": rec.data_scadenza,
                "stato_scadenza": stato,
                "giorni_alla_scadenza": giorni,
                "is_required": rule.is_mandatory if rule else False,
                "needs_refresh": False,
                "last_recalculation_source": "refresh_deadlines",
            },
        )
        updated += 1

    # ── 2. Regole per singolo dipendente senza record completamento ──────────
    rules_qs = TrainingRequirementRule.objects.filter(
        is_active=True,
        legacy_anagrafica_id__isnull=False,
    ).select_related("corso", "piano")
    if legacy_id is not None:
        rules_qs = rules_qs.filter(legacy_anagrafica_id=legacy_id)

    for rule in rules_qs:
        corsi: list[TrainingCourse] = []
        if rule.corso_id:
            corsi.append(rule.corso)
        elif rule.piano_id:
            corsi = list(TrainingCourse.objects.filter(piano_id=rule.piano_id, is_active=True))

        for corso in corsi:
            if corso_id is not None and corso.pk != corso_id:
                continue
            key = (rule.legacy_anagrafica_id, corso.pk)
            if key in pairs:
                continue  # Già gestito con il record completamento

            TrainingDeadline.objects.update_or_create(
                corso=corso,
                legacy_anagrafica_id=rule.legacy_anagrafica_id,
                defaults={
                    "requirement_rule": rule,
                    "assignment": None,
                    "ultimo_completamento": None,
                    "data_ultimo_completamento": None,
                    "data_scadenza": None,
                    "stato_scadenza": "MAI_FREQUENTATO",
                    "giorni_alla_scadenza": None,
                    "is_required": rule.is_mandatory,
                    "needs_refresh": False,
                    "last_recalculation_source": "refresh_deadlines",
                },
            )
            updated += 1

    return updated
