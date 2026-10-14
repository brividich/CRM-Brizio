"""Dati di identita' letti dal monitoraggio SNMP che non coincidono con l'anagrafica asset.

Il monitoraggio non scrive mai da solo nell'anagrafica: qui si calcolano solo le
differenze, e l'utente sceglie se applicarle (azione ``apply_snmp_identity`` della
scheda asset, con audit). Si applica soltanto un valore effettivamente letto e
mostrato, mai un testo arbitrario arrivato dalla POST.
"""
from __future__ import annotations

import re

FIELD_LABELS = {
    "serial_number": "Numero di serie",
    "manufacturer": "Produttore",
    "model": "Modello",
}


def _norm(value, field="") -> str:
    text = " ".join(str(value or "").split()).casefold()
    if field == "serial_number":
        # «SN-1234 5» e «sn12345» sono lo stesso seriale: contano solo lettere e cifre.
        return re.sub(r"[^0-9a-z]", "", text)
    return text


def snmp_identity_diffs(asset) -> list[dict]:
    """Differenze fra anagrafica e dati SNMP dei dispositivi/MFC collegati."""
    from contatori.models import DispositivoSNMP, Macchina

    sources = []
    for device in DispositivoSNMP.objects.filter(asset=asset).only("nome", "host", "matricola", "produttore", "modello"):
        sources.append((f"Dispositivo SNMP «{device.nome}» ({device.host})", {
            "serial_number": device.matricola, "manufacturer": device.produttore, "model": device.modello,
        }))
    for machine in Macchina.objects.filter(asset=asset).only("reparto", "matricola", "modello"):
        sources.append((f"MFC «{machine.reparto}» (anagrafica Contatori)", {"serial_number": machine.matricola, "model": machine.modello}))

    diffs, seen = [], set()
    for origin, values in sources:
        for field, value in values.items():
            value = " ".join(str(value or "").split())
            current = getattr(asset, field) or ""
            if not value or _norm(value, field) == _norm(current, field) or (field, _norm(value, field)) in seen:
                continue
            seen.add((field, _norm(value, field)))
            diffs.append({
                "field": field,
                "label": FIELD_LABELS[field],
                "asset_value": current,
                "snmp_value": value[:120],
                "origin": origin,
            })
    return diffs
