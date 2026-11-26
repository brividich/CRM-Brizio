"""Qualifiche dai completamenti: riporta sulla scheda le qualifiche dei corsi già fatti.

Il collegamento corso → qualifica scrive la qualifica solo per i completamenti NUOVI
(``_crea_employee_record``/``_crea_record_completamento_elearning``): i completamenti importati o
precedenti al collegamento non l'hanno mai ricevuta (analisi 26/11/2026: 0 qualifiche contro 275
completamenti su corsi che la rilasciano). Qui si recupera, una volta, con la stessa funzione.
"""
from __future__ import annotations


def da_allineare() -> list:
    """Ultimo completamento idoneo per (persona, qualifica) che la scheda non riporta ancora
    (qualifica assente o conseguita prima di quel completamento)."""
    from ..models import DipendenteQualifica
    from ..models_formazione import TrainingEmployeeRecord

    ultimi = {}
    for r in (TrainingEmployeeRecord.objects.filter(corso__qualifica__isnull=False, idoneo=True)
              .select_related("corso", "corso__qualifica").order_by("data_completamento", "pk")):
        ultimi[(r.legacy_anagrafica_id, r.corso.qualifica_id)] = r
    if not ultimi:
        return []
    attuali = {}
    for q in DipendenteQualifica.objects.filter(tipo_id__in={k[1] for k in ultimi}).order_by("data_conseguimento", "pk"):
        attuali[(q.legacy_anagrafica_id, q.tipo_id)] = q
    out = []
    for chiave, r in ultimi.items():
        q = attuali.get(chiave)
        if q is None or (q.data_conseguimento or r.data_completamento) < r.data_completamento:
            out.append(r)
    return out


def allinea(user=None) -> int:
    """Crea o aggiorna la qualifica corrente per ogni completamento di :func:`da_allineare`."""
    from ..views._helpers import _upsert_dipendente_qualifica

    n = 0
    for r in da_allineare():
        qual, _creata = _upsert_dipendente_qualifica(
            r.legacy_anagrafica_id, r.corso.qualifica, r.data_completamento, r.data_scadenza, user=user,
            note=f"Dal completamento del corso {r.corso.codice} del {r.data_completamento:%d-%m-%Y}")
        if qual.record_formazione_id != r.pk:
            qual.record_formazione = r
            qual.save(update_fields=["record_formazione"])
        n += 1
    return n
