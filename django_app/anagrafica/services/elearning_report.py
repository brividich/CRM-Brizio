"""Reportistica e-learning per la Direzione: copertura, andamento, qualità dei contenuti.

Solo aggregazioni (nessuna query in ciclo):

- **copertura** degli obblighi su corsi e-learning pubblicati, per reparto e per
  mansione, dal motore unico dei requisiti (gli stessi numeri dello scadenzario);
- **completamenti** per mese, **ore** effettive (tempo accreditato dagli
  heartbeat), **punteggio medio** e **tempo medio** di completamento per corso;
- **domande più sbagliate** (dai tentativi inviati) per migliorare i contenuti;
- **registro** dei completamenti (chi, ciclo, versione, quando, tempo effettivo,
  tentativi, punteggio, impronta), base dell'export per l'audit.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone


def _corsi_pubblicati():
    from ..models_formazione import TrainingCourse
    from .elearning_fruizione import corsi_pubblicati
    return {c.pk: c for c in corsi_pubblicati()}


def copertura(*, reparto: str = "", corso_id: int | None = None) -> dict:
    """Percentuale di obblighi e-learning in regola, totale e per reparto/mansione."""
    from . import requisiti

    corsi = _corsi_pubblicati()
    if corso_id:
        corsi = {k: v for k, v in corsi.items() if k == corso_id}
    ctx = requisiti.ambito()
    persone = {d.id: d for d in ctx._tutti() if d.data_cessazione is None and d.attivo_legacy}
    if reparto:
        persone = {k: p for k, p in persone.items() if (p.reparto or "").casefold() == reparto.casefold()}
    per_reparto: dict[str, Counter] = defaultdict(Counter)
    per_mansione: dict[str, Counter] = defaultdict(Counter)
    per_persona: dict[int, list] = defaultdict(list)
    totale = Counter()
    if corsi and persone:
        for v in requisiti.formazione(ctx, persone):
            if v.corso.pk not in corsi or not v.obbligatorio:
                continue
            ok = v.stato not in ("MAI_FREQUENTATO", "SCADUTO")
            p = persone[v.persona]
            for contatore in (totale, per_reparto[p.reparto or "—"], per_mansione[p.mansione or "—"]):
                contatore["obblighi"] += 1
                contatore["in_regola"] += ok
            per_persona[v.persona].append({"corso": v.corso, "stato": v.stato, "scadenza": v.scadenza, "ok": ok})

    def _righe(gruppi):
        out = [{"nome": k, "obblighi": c["obblighi"], "in_regola": c["in_regola"],
                "pct": round(100 * c["in_regola"] / c["obblighi"]) if c["obblighi"] else 0} for k, c in gruppi.items()]
        return sorted(out, key=lambda r: (r["pct"], r["nome"].casefold()))

    persone_righe = sorted(
        ({"legacy_id": pid, "nome": persone[pid].nominativo, "reparto": persone[pid].reparto,
          "mansione": persone[pid].mansione, "voci": voci, "mancanti": sum(1 for x in voci if not x["ok"])}
         for pid, voci in per_persona.items()),
        key=lambda r: (-r["mancanti"], r["nome"].casefold()),
    )
    return {
        "obblighi": totale["obblighi"], "in_regola": totale["in_regola"],
        "pct": round(100 * totale["in_regola"] / totale["obblighi"]) if totale["obblighi"] else 0,
        "per_reparto": _righe(per_reparto), "per_mansione": _righe(per_mansione), "persone": persone_righe,
    }


def andamento(mesi: int = 12) -> dict:
    """Completamenti per mese, ore effettive, punteggio e tempo medi per corso."""
    from ..models_elearning import TrainingElearningCompletamento
    from ..models_formazione import TrainingElearningEnrollment

    dal = timezone.now() - timedelta(days=31 * mesi)
    per_mese = list(
        TrainingElearningCompletamento.objects.filter(creato_il__gte=dal)
        .annotate(mese=TruncMonth("creato_il")).values("mese").annotate(n=Count("pk")).order_by("mese")
    )
    per_corso = list(
        TrainingElearningEnrollment.objects.filter(stato="COMPLETATO")
        .values("corso_id", "corso__titolo")
        .annotate(n=Count("pk"), punteggio=Avg("best_punteggio_pct"), secondi=Avg("secondi_accreditati"))
        .order_by("corso__titolo")
    )
    ore = (TrainingElearningEnrollment.objects.aggregate(s=Sum("secondi_accreditati"))["s"] or 0) / 3600
    for r in per_corso:
        r["minuti_medi"] = round((r["secondi"] or 0) / 60)
        r["punteggio"] = round(float(r["punteggio"] or 0), 1)
    return {"per_mese": per_mese, "per_corso": per_corso, "ore_erogate": round(ore, 1),
            "totale_periodo": sum(m["n"] for m in per_mese)}


def domande_piu_sbagliate(limite: int = 10, ultimi: int = 2000) -> list[dict]:
    from ..models_formazione import TrainingQuizAttempt

    errori, totali, testi = Counter(), Counter(), {}
    for risposte in (TrainingQuizAttempt.objects.filter(stato="INVIATO").order_by("-pk")
                     .values_list("risposte_json", flat=True)[:ultimi]):
        for r in (risposte or {}).get("risposte", []):
            did = r.get("domanda_id")
            totali[did] += 1
            errori[did] += not r.get("giusta")
            testi.setdefault(did, r.get("domanda", ""))
    righe = [{"domanda_id": d, "testo": testi[d], "errori": errori[d], "risposte": totali[d],
              "pct_errori": round(100 * errori[d] / totali[d]) if totali[d] else 0}
             for d in totali if totali[d] >= 3]
    return sorted(righe, key=lambda r: (-r["pct_errori"], -r["risposte"]))[:limite]


def registro(*, corso_id: int | None = None, dal=None, al=None) -> list[dict]:
    """Registro dei completamenti, difendibile in audit (dati già fotografati)."""
    from ..models_elearning import TrainingElearningCompletamento
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    qs = TrainingElearningCompletamento.objects.select_related("enrollment__corso", "record").order_by("-creato_il")
    if corso_id:
        qs = qs.filter(enrollment__corso_id=corso_id)
    if dal:
        qs = qs.filter(creato_il__date__gte=dal)
    if al:
        qs = qs.filter(creato_il__date__lte=al)
    righe = list(qs[:5000])
    ids = sorted({c.enrollment.legacy_anagrafica_id for c in righe})
    nomi = {int(r["id"]): naming.nome_completo(r.get("nome"), r.get("cognome")) for r in fetch_anagrafica_rows(ids=ids)} if ids else {}
    out = []
    for c in righe:
        v = c.verifica_json or {}
        quiz = v.get("quiz") or {}
        out.append({
            "data": c.creato_il, "dipendente": nomi.get(c.enrollment.legacy_anagrafica_id, f"#{c.enrollment.legacy_anagrafica_id}"),
            "legacy_id": c.enrollment.legacy_anagrafica_id, "corso": c.enrollment.corso.titolo,
            "codice": c.enrollment.corso.codice, "ciclo": c.enrollment.ciclo,
            "versione": c.enrollment.versione_label_snapshot or c.record.course_version_snapshot or "",
            "minuti_effettivi": round((v.get("secondi_effettivi") or 0) / 60),
            "slide": f"{v.get('slide_completate', '')}/{v.get('slide_totali', '')}",
            "tentativi": v.get("tentativi", ""), "punteggio": quiz.get("punteggio_pct", ""),
            "protocollo": c.record.numero_protocollo or "", "impronta": c.sha256[:16],
        })
    return out
