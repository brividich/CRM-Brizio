"""Struttura → processi del Sistema di Gestione: chi possiede e chi esegue un processo.

- owner: chi ricopre oggi il ruolo owner del processo (``Processo.ruolo_owner``);
- esecutori: chi è operativo su una mansione lavorativa del processo
  (``CompetenzaSkm.processo_sgi``) secondo la soglia della skill matrix.

Serve alla scheda del processo e alle proposte di auditati nel piano di audit.
Le email sono quelle di notifica (``email_notifica``), mai il login legacy.
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from ..models import AbilitazioneMacchina, DipendenteRuoloOperativo, SkillMatrixConfig


def _anagrafica(ids) -> dict[int, dict]:
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return {}
    out = {}
    for r in fetch_anagrafica_rows(ids=ids):
        attivo = r.get("attivo")
        if attivo is not None and not attivo:
            continue
        out[int(r["id"])] = {
            "legacy_id": int(r["id"]),
            "nome": naming.nome_completo(r.get("nome"), r.get("cognome")) or f"#{r['id']}",
            "email": (r.get("email_notifica") or "").strip(),
        }
    return out


def persone_processo(processo) -> dict:
    """``{owner, mansioni, esecutori}`` del processo; persone non attive escluse."""
    oggi = timezone.localdate()
    owner_ids = []
    if processo.ruolo_owner_id:
        owner_ids = list(
            DipendenteRuoloOperativo.objects.filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi),
                                                    ruolo_id=processo.ruolo_owner_id)
            .values_list("legacy_anagrafica_id", flat=True)
        )
    mansioni = list(processo.mansioni_lavorative.filter(attiva=True).order_by("display"))
    soglia = SkillMatrixConfig.get_instance().soglia_operativa_ordinale
    abil = list(AbilitazioneMacchina.objects.filter(competenza__in=mansioni, in_lista=True))
    operative = [a for a in abil if a.is_operativa(soglia)]
    persone = _anagrafica([*owner_ids, *(a.legacy_anagrafica_id for a in operative)])

    per_mansione = {m.pk: {"mansione": m, "n_lista": 0, "n_operativi": 0} for m in mansioni}
    for a in abil:
        per_mansione[a.competenza_id]["n_lista"] += 1
    esecutori: dict[int, dict] = {}
    for a in operative:
        per_mansione[a.competenza_id]["n_operativi"] += 1
        p = persone.get(a.legacy_anagrafica_id)
        if p:
            esecutori.setdefault(p["legacy_id"], {**p, "mansioni": []})["mansioni"].append(
                per_mansione[a.competenza_id]["mansione"].display)
    owner = [persone[i] for i in dict.fromkeys(owner_ids) if i in persone]
    return {
        "owner": sorted(owner, key=lambda p: p["nome"].casefold()),
        "mansioni": list(per_mansione.values()),
        "esecutori": sorted(esecutori.values(), key=lambda p: p["nome"].casefold()),
    }


def proposte_auditati(audit) -> list[dict]:
    """Persone da proporre nel piano: owner come responsabili del processo, esecutori come auditati.

    Salta chi è già nel piano (stessa email o stesso nome). Una persona compare una
    volta sola, col ruolo più alto (responsabile prima di auditato).
    """
    from sistema_gestione.models import AuditPersona

    gia = {(p.email or "").casefold() for p in audit.persone.all() if p.email}
    gia_nomi = {(p.nome or "").casefold() for p in audit.persone.all()}
    out: dict[int, dict] = {}
    for processo in audit.processi_catalogo.select_related("ruolo_owner").order_by("codice"):
        dati = persone_processo(processo)
        righe = ([(p, AuditPersona.RUOLO_PROCESSO, processo.ruolo_owner.etichetta if processo.ruolo_owner_id else "")
                  for p in dati["owner"]]
                 + [(p, AuditPersona.RUOLO_AUDITATO, ", ".join(p["mansioni"])) for p in dati["esecutori"]])
        for p, ruolo, funzione in righe:
            if (p["email"] and p["email"].casefold() in gia) or p["nome"].casefold() in gia_nomi:
                continue
            voce = out.get(p["legacy_id"])
            if voce is None:
                out[p["legacy_id"]] = {**p, "ruolo": ruolo, "funzione": funzione, "processi": [processo.codice]}
            else:
                if processo.codice not in voce["processi"]:
                    voce["processi"].append(processo.codice)
                if ruolo == AuditPersona.RUOLO_PROCESSO:
                    voce["ruolo"], voce["funzione"] = ruolo, funzione
    return sorted(out.values(), key=lambda p: (p["ruolo"] != AuditPersona.RUOLO_PROCESSO, p["nome"].casefold()))
