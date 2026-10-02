"""Storico per il copilota MOD.133: cosa e' gia' stato approvato per la stessa specifica e per lo stesso cliente.

- revisione precedente della stessa specifica: le righe MOD.133 approvate (argomento, riferimenti CN, TAG,
  impatti) sono la base piu' affidabile per la nuova revisione;
- altre specifiche dello stesso cliente: gli argomenti che ricorrono e i documenti CN a cui rimandano;
- TAG di processo usati per lo stesso cliente.

Impara: alla chiusura della compilazione si confrontano righe e TAG proposti con quelli salvati
(``ai_assistant.apprendimento``); le correzioni frequenti tornano nel contesto delle proposte successive.
"""
from __future__ import annotations

import logging
from collections import Counter

logger = logging.getLogger(__name__)

MODULO = "specifiche"
AZIONE_RIGHE = "mod133_righe"
AZIONE_TAG = "tag"


def _righe_approvate(spec) -> list:
    mod = getattr(spec, "mod133", None) if spec else None
    try:
        if mod is None or not mod.data_approvazione:
            return []
        return list(mod.righe.all().order_by("ordine", "id"))
    except Exception:  # noqa: BLE001 - spec senza MOD.133
        return []


def storico_spec(spec, *, max_cliente: int = 6) -> dict:
    from .models import Specifica

    out = {"precedente": None, "argomenti_cliente": [], "tag_cliente": []}
    prec, visti = getattr(spec, "revisione_precedente", None), {spec.pk}
    for _ in range(3):  # la revisione precedente puo' non avere un MOD.133 approvato: risale ancora
        if prec is None or prec.pk in visti:
            break
        visti.add(prec.pk)
        righe = _righe_approvate(prec)
        if righe:
            out["precedente"] = {
                "codice": prec.codice, "revisione": prec.revisione,
                "righe": [{"argomento": r.argomento, "rif_paragrafo": r.rif_paragrafo, "rif_doc_cn": r.rif_doc_cn,
                           "tag_processo": r.tag_processo, "impatto_documenti": r.impatto_documenti,
                           "impatto_operativo": r.impatto_operativo} for r in righe[:30]],
            }
            break
        prec = getattr(prec, "revisione_precedente", None)

    cliente = (spec.cliente or "").strip()
    if cliente:
        altre = (Specifica.objects.filter(cliente__iexact=cliente).exclude(pk__in=visti)
                 .select_related("mod133").order_by("-id")[:40])
        argomenti, tag_righe, lette = Counter(), {}, 0
        for altra in altre:
            righe = _righe_approvate(altra)
            if not righe:
                continue
            lette += 1
            for r in righe:
                chiave = (r.argomento or "").strip()
                if chiave:
                    argomenti[chiave] += 1
                    tag_righe.setdefault(chiave, Counter())[(r.tag_processo or "", r.rif_doc_cn or "")] += 1
            if lette >= max_cliente:
                break
        out["argomenti_cliente"] = [
            {"argomento": arg, "volte": n, "tag_processo": tag_righe[arg].most_common(1)[0][0][0],
             "rif_doc_cn": tag_righe[arg].most_common(1)[0][0][1]}
            for arg, n in argomenti.most_common(10) if n >= 2
        ]
        tag = Counter(t for t in Specifica.objects.filter(cliente__iexact=cliente).exclude(pk=spec.pk)
                      .exclude(tag="").values_list("tag", flat=True)[:200])
        out["tag_cliente"] = [{"tag": t, "volte": n} for t, n in tag.most_common(5)]
    return out


def storico_testo(storico: dict) -> str:
    righe = []
    prec = storico.get("precedente")
    if prec:
        righe.append(f"MOD.133 APPROVATO della revisione precedente ({prec['codice']} rev. {prec['revisione'] or '-'}): "
                     "riprendi le righe ancora valide e aggiorna solo ciò che cambia.")
        for r in prec["righe"]:
            righe.append(f"- §{r['rif_paragrafo'] or '?'} {r['argomento']} → doc CN {r['rif_doc_cn'] or 'n.d.'}, TAG {r['tag_processo'] or 'n.d.'}"
                         + (", impatto documenti" if r["impatto_documenti"] else "") + (", impatto operativo" if r["impatto_operativo"] else ""))
    if storico.get("argomenti_cliente"):
        righe.append("ARGOMENTI RICORRENTI nei MOD.133 approvati dello stesso cliente:")
        righe += [f"- {a['argomento']} ({a['volte']} volte) → doc CN {a['rif_doc_cn'] or 'n.d.'}, TAG {a['tag_processo'] or 'n.d.'}"
                  for a in storico["argomenti_cliente"]]
    if storico.get("tag_cliente"):
        righe.append("TAG usati per le specifiche dello stesso cliente: " + ", ".join(f"{t['tag']} ({t['volte']})" for t in storico["tag_cliente"]))
    try:
        from ai_assistant.apprendimento import lezioni_testo

        for azione, etichette in ((AZIONE_TAG, {"tag": "TAG"}), (AZIONE_RIGHE, {"argomenti": "argomenti"})):
            lezioni = lezioni_testo(MODULO, azione, etichette=etichette)
            if lezioni:
                righe.append(lezioni)
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(righe)


def registra_proposta_righe(spec, righe: list[dict], user=None) -> None:
    try:
        from ai_assistant.apprendimento import registra_proposta

        argomenti = [r.get("argomento") for r in righe if r.get("argomento")]
        tag = sorted({r.get("tag_processo") for r in righe if r.get("tag_processo")})
        if argomenti:
            registra_proposta(modulo=MODULO, azione=AZIONE_RIGHE, oggetto_ref=spec.pk,
                              proposta={"argomenti": argomenti, "tag_righe": tag}, user=user)
    except Exception:  # noqa: BLE001
        logger.exception("Proposta MOD.133 non registrata")


def registra_proposta_tag(spec, tag: str, user=None) -> None:
    try:
        from ai_assistant.apprendimento import registra_proposta

        if tag:
            registra_proposta(modulo=MODULO, azione=AZIONE_TAG, oggetto_ref=spec.pk, proposta={"tag": tag}, user=user)
    except Exception:  # noqa: BLE001
        logger.exception("Proposta TAG non registrata")


def registra_esito_compilazione(spec, user=None) -> None:
    """Chiusura della compilazione: righe e TAG definitivi contro quelli proposti."""
    try:
        from ai_assistant.apprendimento import registra_decisione

        righe = list(spec.mod133.righe.all())
        registra_decisione(modulo=MODULO, azione=AZIONE_RIGHE, oggetto_ref=spec.pk, user=user, decisione={
            "argomenti": [r.argomento for r in righe if r.argomento],
            "tag_righe": sorted({r.tag_processo for r in righe if r.tag_processo}),
        })
        registra_decisione(modulo=MODULO, azione=AZIONE_TAG, oggetto_ref=spec.pk, user=user, decisione={"tag": spec.tag})
    except Exception:  # noqa: BLE001
        logger.exception("Esito compilazione MOD.133 non registrato")
