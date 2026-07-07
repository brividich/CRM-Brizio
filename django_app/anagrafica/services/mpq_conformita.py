"""MOD.128 MPQ — conformità dei requisiti di processo.

Un processo qualificato può dichiarare **requisiti** (corsi di formazione, DPI,
visite mediche) come una mansione di rischio. Questo servizio verifica, per una
persona abilitata al processo, se possiede i requisiti dichiarati, riusando le
stesse fonti del motore conformità esistente:
- formazione → ``TrainingDeadline`` (stato_scadenza per corso);
- visite → ultima ``VisitaMedica`` per tipologia (scaduta se ``data_scadenza`` passata);
- DPI → ``ConsegnaDPI`` consegnata per categoria.

Ritorna una struttura leggera per l'UI (esito + voci con stato). Modelli ``dpi``
importati localmente (cross-app, fail-safe).
"""
from __future__ import annotations

from django.utils import timezone

_SOGLIA_WARN = 60


def verifica_requisiti(processo, legacy_id: int, *, oggi=None) -> dict:
    """Verifica i requisiti del processo per una persona (legacy_anagrafica_id).

    Ritorna ``{"esito", "voci": [{"tipo","nome","stato"}], "n_mancanti"}`` dove
    ``stato`` ∈ {ok, in_scadenza, scaduto, mancante, na} e ``esito`` ∈
    {ok, warn, incompleto, ko, nessuno}.
    """
    oggi = oggi or timezone.localdate()
    voci: list[dict] = []

    corsi = list(processo.corsi_richiesti.all())
    if corsi and legacy_id:
        from ..models import TrainingDeadline
        dmap = {
            d.corso_id: d for d in TrainingDeadline.objects
            .filter(legacy_anagrafica_id=legacy_id, corso__in=corsi).select_related("corso")
        }
        for c in corsi:
            d = dmap.get(c.id)
            if d is None or d.stato_scadenza == "MAI_FREQUENTATO":
                stato = "mancante"
            elif d.stato_scadenza == "SCADUTO":
                stato = "scaduto"
            elif d.stato_scadenza in ("IN_SCADENZA_30", "IN_SCADENZA_90"):
                stato = "in_scadenza"
            else:
                stato = "ok"
            voci.append({"tipo": "Corso", "nome": c.titolo, "stato": stato})

    visite = list(processo.visite_richieste.all())
    if visite and legacy_id:
        from ..models import VisitaMedica
        ultime = {}
        for v in (VisitaMedica.objects
                  .filter(legacy_anagrafica_id=legacy_id, tipo__in=visite)
                  .order_by("-data_svolgimento", "-pk")):
            ultime.setdefault(v.tipo_id, v)
        for t in visite:
            v = ultime.get(t.id)
            if v is None:
                stato = "mancante"
            elif v.data_scadenza is None:
                stato = "ok"
            elif v.data_scadenza < oggi:
                stato = "scaduto"
            elif (v.data_scadenza - oggi).days <= _SOGLIA_WARN:
                stato = "in_scadenza"
            else:
                stato = "ok"
            voci.append({"tipo": "Visita", "nome": t.nome, "stato": stato})

    dpi_cats = list(processo.dpi_richiesti.all())
    if dpi_cats and legacy_id:
        consegnate = None
        try:
            from dpi.models import ConsegnaDPI, StatoRichiesta
            consegnate = set(
                ConsegnaDPI.objects
                .filter(richiesta__richiedente_legacy_id=legacy_id,
                        richiesta__stato=StatoRichiesta.CONSEGNATA,
                        richiesta__categoria__in=dpi_cats)
                .values_list("richiesta__categoria_id", flat=True)
            )
        except Exception:
            consegnate = None
        for cat in dpi_cats:
            if consegnate is None:
                stato = "na"
            elif cat.id in consegnate:
                stato = "ok"
            else:
                stato = "mancante"
            voci.append({"tipo": "DPI", "nome": getattr(cat, "nome", str(cat)), "stato": stato})

    stati = [v["stato"] for v in voci]
    if not voci:
        esito = "nessuno"
    elif "scaduto" in stati:
        esito = "ko"
    elif "mancante" in stati:
        esito = "incompleto"
    elif "in_scadenza" in stati:
        esito = "warn"
    else:
        esito = "ok"
    n_mancanti = sum(1 for s in stati if s in ("scaduto", "mancante"))
    return {"esito": esito, "voci": voci, "n_mancanti": n_mancanti}
