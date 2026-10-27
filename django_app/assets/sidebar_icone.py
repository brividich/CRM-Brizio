"""Icone delle voci di primo livello della sidebar Assets.

Solo il contenuto di un ``<svg viewBox="0 0 24 24">`` a tratto (stile Lucide): il
template lo avvolge e il colore viene dal testo, quindi vale in chiaro e in scuro.
Costanti del codice, mai testo dell'utente: si stampano con ``|safe``.
Le voci aggiunte a mano da Impostazioni › Menu sidebar prendono ``PUNTO``.
"""
from __future__ import annotations

PUNTO = '<circle cx="12" cy="12" r="2.5"/>'

_CRUSCOTTO = (
    '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/>'
    '<rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>'
)
_ELENCO = '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>'
_MONITOR = '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>'
_COMPONENTE = (
    '<rect x="6" y="6" width="12" height="12" rx="2"/>'
    '<path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>'
)
_CHIAVE_INGLESE = (
    '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94'
    'l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>'
)
_CURSORI = '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>'
_MAPPA = '<path d="M9 3 3 6v15l6-3 6 3 6-3V3l-6 3-6-3z"/><path d="M9 3v15M15 6v15"/>'
_SCUDO = '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>'
_CHIAVE = '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>'
_PACCO = (
    '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4'
    'a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.27 6.96 12 12.01l8.73-5.05M12 22.08V12"/>'
)
_GLOBO = (
    '<circle cx="12" cy="12" r="10"/>'
    '<path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>'
)
_RACK = (
    '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/>'
    '<path d="M6 6h.01M6 18h.01"/>'
)
_ETICHETTA = (
    '<path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><path d="M7 7h.01"/>'
)
_CALENDARIO = '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>'
INGRANAGGIO = (
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83'
    'l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4'
    'a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1'
    'H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06'
    'A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33'
    'l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09'
    'a1.65 1.65 0 0 0-1.51 1z"/>'
)
GUIDA = '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01"/>'

ICONE: dict[str, str] = {
    "cruscotto": _CRUSCOTTO,
    "inventario": _ELENCO,
    "dashboard": _ELENCO,
    "hardware": _MONITOR,
    "componenti": _COMPONENTE,
    "asset_components": _COMPONENTE,
    "il_mio_turno": _CALENDARIO,
    "maintenance_hub": _CHIAVE_INGLESE,
    "manutenzione_hub": _CHIAVE_INGLESE,
    "maintenance_configurazione": _CURSORI,
    "manutenzione_config": _CURSORI,
    "mappa_officina": _MAPPA,
    "plant_layout_map": _MAPPA,
    "part_145_list": _SCUDO,
    "licenze": _CHIAVE,
    "software_licenses": _CHIAVE,
    "catalogo_software": _PACCO,
    "rete_indirizzi": _GLOBO,
    "rete_rack": _RACK,
    "guida_asset": GUIDA,
}


def icona(code: str) -> str:
    code = (code or "").strip()
    if code.startswith("catnav-"):
        return _ETICHETTA
    return ICONE.get(code, PUNTO)
