"""Collegamenti di una voce del registro con il resto del portale.

Un solo punto che sa da dove nasce una voce (rilievo di un audit interno, rilievo di
un ente, riga MOD.133) e a cosa è legata (processo del catalogo, azione correttiva):
lo usano la scheda della voce, l'elenco e la dashboard, così il link è sempre lo stesso.
"""
from __future__ import annotations

from django.urls import NoReverseMatch, reverse

# Etichette dell'origine per modulo, mostrate nella dashboard e nei filtri.
ORIGINI = (
    ("audit_interno", "Audit interni"),
    ("audit_esterno", "Audit degli enti"),
    ("mod133", "Specifiche / MOD.133"),
    ("manuale", "Inserite a mano"),
)


def _url(nome: str, *args, ancora: str = "") -> str:
    try:
        return reverse(nome, args=args) + (f"#{ancora}" if ancora else "")
    except NoReverseMatch:
        return ""


def tipo_origine(voce) -> str:
    """Chiave dell'origine (una di ``ORIGINI``) ricavata dal riferimento generico."""
    modello = getattr(voce.content_type, "model", "") if voce.content_type_id else ""
    if modello == "auditesito":
        return "audit_interno"
    if modello == "auditesterno":
        return "audit_esterno"
    if modello == "rigamod133" or voce.modulo_origine == "gestione_specifiche":
        return "mod133"
    return "manuale"


def origine(voce) -> dict | None:
    """{tipo, etichetta, url} dell'oggetto da cui nasce la voce; None se inserita a mano."""
    tipo = tipo_origine(voce)
    if tipo == "manuale":
        return None
    oggetto = voce.origine if voce.object_id else None
    if tipo == "audit_interno" and oggetto is not None:
        audit = oggetto.audit
        clausola = getattr(oggetto, "clausola_effettiva", "")
        return {"tipo": tipo, "etichetta": f"Rilievo dell'audit {audit.numero}" + (f" · § {clausola}" if clausola else ""),
                "url": _url("sistema_gestione:audit_dettaglio", audit.pk, ancora=f"esito-{oggetto.pk}")}
    if tipo == "audit_esterno" and oggetto is not None:
        return {"tipo": tipo, "etichetta": f"Rilievo dell'ente: {oggetto}",
                "url": _url("sistema_gestione:esterni_audit", oggetto.pk)}
    if tipo == "mod133" and oggetto is not None:
        specifica = oggetto.mod133.specifica
        return {"tipo": tipo, "etichetta": f"MOD.133 della specifica {specifica.codice}",
                "url": _url("gestione_specifiche:dettaglio", specifica.pk)}
    # L'oggetto d'origine non c'è più: resta l'indicazione del modulo, senza link.
    return {"tipo": tipo, "etichetta": dict(ORIGINI)[tipo] + " (oggetto non più presente)", "url": ""}


def processo(voce) -> dict | None:
    """{etichetta, url} del processo del catalogo collegato alla voce."""
    if not voce.processo_sgi_id:
        return None
    return {"etichetta": str(voce.processo_sgi),
            "url": _url("sistema_gestione:processo_dettaglio", voce.processo_sgi_id, ancora="ofi")}


def car(voce) -> dict:
    """Azione correttiva MT CN 11 della voce: aperta, chiusa o da aprire."""
    from gestione_specifiche.registro_ofi import car_collegata

    collegata = car_collegata(voce)
    stato = "nessuna" if collegata is None else ("chiusa" if collegata.chiusa_il else "aperta")
    return {"stato": stato, "url": _url("sistema_gestione:procedura_car", voce.pk)}


def conta_per_origine(voci) -> list[dict]:
    """[{chiave, etichetta, n}] delle voci per origine, nell'ordine di ``ORIGINI``."""
    conteggi = {k: 0 for k, _ in ORIGINI}
    for v in voci:
        conteggi[tipo_origine(v)] += 1
    return [{"chiave": k, "etichetta": e, "n": conteggi[k]} for k, e in ORIGINI]
