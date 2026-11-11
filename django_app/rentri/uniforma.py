"""Uniformare il modo in cui è scritto il codice CER (storico importato).

Lo storico scrive lo stesso codice in modi diversi («12.01.01 Sfridi Ferro Kg»,
«12 01 01»): i conti già passano dalle sei cifre (:func:`rentri.fili.chiave`), ma
elenco, stampe e suggerimenti mostrano testi diversi. Qui si propone **un testo per
codice** («12 01 01 Sfridi Ferro») e lo si applica con anteprima e conferma.

Regole:

- il codice resta lo stesso: si cambia solo il testo, e solo se le sei cifre del
  testo nuovo sono quelle del vecchio;
- gli annullati non si toccano (restano come furono annullati);
- ogni riga cambiata ha la sua voce di audit (vecchio → nuovo, visibile nella
  scheda); se SharePoint è configurato la riga resta segnata da reinviare
  (``rentri_sync_riprova``), come nel consolidamento in blocco.
"""
from __future__ import annotations

import re
from collections import Counter

from django.db import transaction
from django.utils import timezone

from core.audit import log_action

from .fili import chiave
from .models import RegistroRifiuti

_PREFISSO = re.compile(r"^\s*\d{2}[\s.\-]*\d{2}[\s.\-]*\d{2}\s*\*?\s*[-–:]?\s*")
_UNITA_FINALE = re.compile(r"\s+(kg|kgs|lt|l|litri|mc|m3|m³|t|ton)\.?\s*$", re.I)
_UNITA_ATTACCATA = re.compile(r"(?<=[a-zà-ù])(Kg|KG|Lt|LT)\s*$")  # «lampadineKg»


def codice_esteso(k: str, pericoloso: bool) -> str:
    return f"{k[0:2]} {k[2:4]} {k[4:6]}" + ("*" if pericoloso else "")


def descrizione_da_testo(testo: str) -> str:
    """«12.01.01 Sfridi Ferro Kg» → «Sfridi Ferro» (senza codice né unità finale)."""
    d = _PREFISSO.sub("", " ".join((testo or "").split()))
    d = d.lstrip("* ").strip()
    return _UNITA_ATTACCATA.sub("", _UNITA_FINALE.sub("", d)).strip(" -–:")


def proposte() -> list[dict]:
    """Un testo proposto per ogni codice scritto in più modi o non nella forma «NN NN NN»."""
    from .models import CatalogoEER

    catalogo = {c.codice: c for c in CatalogoEER.objects.all()}
    righe = list(RegistroRifiuti.objects.attivi().exclude(codice="").values_list("codice", "salva"))
    per_codice: dict[str, Counter] = {}
    consolidate: Counter = Counter()
    for testo, salva in righe:
        k = chiave(testo)
        if not k:
            continue
        t = " ".join(testo.split())
        per_codice.setdefault(k, Counter())[t] += 1
        if salva:
            consolidate[k] += 1
    out = []
    for k, varianti in sorted(per_codice.items()):
        voce = catalogo.get(k)
        pericoloso = bool(voce and voce.pericoloso) or any("*" in t for t in varianti)
        descrizioni = Counter()
        for t, n in varianti.items():
            d = descrizione_da_testo(t)
            if d:
                descrizioni[d] += n
        descr = descrizioni.most_common(1)[0][0] if descrizioni else (voce.descrizione if voce else "")
        proposta = f"{codice_esteso(k, pericoloso)} {descr}".strip()
        da_cambiare = sum(n for t, n in varianti.items() if t != proposta)
        if not da_cambiare:
            continue
        out.append({
            "chiave": k,
            "varianti": varianti.most_common(),
            "proposta": proposta,
            "da_cambiare": da_cambiare,
            "consolidate": consolidate[k],
            "catalogo": voce.descrizione if voce else "",
        })
    return out


class TestoNonValido(ValueError):
    pass


def applica(request, scelte: dict[str, str], utente: str) -> dict:
    """Scrive il testo scelto su tutte le righe valide del codice. `scelte`: chiave → testo."""
    from .sharepoint import _graph_configured

    pulite = {}
    for k, testo in scelte.items():
        t = " ".join((testo or "").split())[:100]
        if chiave(t) != k:
            raise TestoNonValido(f"«{t}» non è il codice {codice_esteso(k, False)}: il codice non si cambia, solo il modo di scriverlo.")
        pulite[k] = t
    nota_sync = "Da reinviare dopo l'uniformazione dei codici" if _graph_configured() else ""
    cambiate = 0
    adesso = timezone.now()
    with transaction.atomic():
        for r in RegistroRifiuti.objects.attivi().exclude(codice="").order_by("id"):
            nuovo = pulite.get(chiave(r.codice))
            if not nuovo or " ".join(r.codice.split()) == nuovo:
                continue
            vecchio = r.codice
            r.codice = nuovo
            r.updated_at = adesso
            campi = ["codice", "updated_at"]
            if nota_sync:
                r.sync_errore = nota_sync
                campi.append("sync_errore")
            r.save(update_fields=campi)
            log_action(
                request, "rentri_codice_uniformato", "rentri",
                {"id_registrazione": r.id_registrazione, "tipo": r.tipo,
                 "modifiche": {"codice": {"old": vecchio, "new": nuovo}}, "consolidato": r.salva},
                oggetto=r,
            )
            cambiate += 1
    esito = {"codici": len(pulite), "righe": cambiate, "da": utente}
    log_action(request, "rentri_codici_uniformati", "rentri", esito)
    return esito
