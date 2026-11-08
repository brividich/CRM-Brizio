"""Nuovo OP dal pannello laterale (elenco degli OP e scheda FAI).

Stesse regole e stessa numerazione di Gestione anomalie: crea con
``anomalie.views.crea_op_da_dati``, il titolo è «causale/anno/numero» e le liste di
causali, capicommessa e CAR sono quelle della configurazione di Gestione anomalie.
"""
from __future__ import annotations

from django.urls import reverse

from core import ordini_produzione as op_db
from core.acl_v2 import request_has_permission_code

from .acl_bootstrap import PERM_OP

CAMPI = ("causale_doc", "anno", "numero", "fase", "pn", "capocommessa", "car", "note")
OBBLIGATORI = {"anno": "Scrivi l'anno.", "numero": "Scrivi il numero.", "pn": "Scrivi il P/N.",
               "capocommessa": "Scegli il capocommessa.", "car": "Scegli il CAR."}


def puo_creare(request) -> bool:
    return op_db.disponibile() and request_has_permission_code(request, PERM_OP)


def contesto(request) -> dict | None:
    """Dati del pannello, o ``None`` se la persona non può creare OP."""
    if not puo_creare(request):
        return None
    from anomalie.views import _load_anomalie_lists

    liste = _load_anomalie_lists()
    return {
        "causali": liste.get("causali_doc") or ["OP"],
        "capicommessa": liste.get("capi_commessa") or [],
        "car": liste.get("capi_reparto") or [],
        "url": reverse("produzione:op_nuovo"),
    }


def crea(request, post) -> tuple[dict | None, dict]:
    """Crea l'OP. Restituisce ``(op, errori)``: errori per campo, ``"__all__"`` per il resto."""
    from anomalie.views import crea_op_da_dati, titolo_nuovo_op

    dati = {campo: (post.get(campo) or "").strip() for campo in CAMPI}
    dati["causale_doc"] = dati["causale_doc"] or "OP"
    dati["collaudo_benestare"] = post.get("collaudo_benestare") in ("1", "on", "true")
    errori = {campo: messaggio for campo, messaggio in OBBLIGATORI.items() if not dati[campo]}
    if errori:
        return None, errori
    titolo = titolo_nuovo_op(dati)
    esistente = op_db.per_titolo(titolo)
    if esistente:
        return None, {"numero": f"L'OP {titolo} esiste già."}
    esito = crea_op_da_dati(request, dati)
    if not esito["success"]:
        return None, {"__all__": esito.get("error") or "OP non creato."}
    op = op_db.per_titolo(titolo)
    if op is None:
        return None, {"__all__": "OP creato ma non ritrovato: ricarica l'elenco."}
    op["url"] = reverse("produzione:scheda", args=[op["id"]])
    return op, {}
