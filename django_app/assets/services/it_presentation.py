"""Read-only IT profiles; no inventory reclassification or inferred ownership."""
from assets.models import Asset


def is_workstation(asset):
    return it_profile(asset) == "workstation"


def it_profile(asset):
    if getattr(asset, "work_machine", None) is not None or asset.prodotto_chimico_id:
        return None
    profiles = {
        Asset.TYPE_PC: "workstation", Asset.TYPE_NOTEBOOK: "workstation",
        Asset.TYPE_SERVER: "server", Asset.TYPE_VM: "vm", Asset.TYPE_STAMPANTE: "printer",
        Asset.TYPE_FIREWALL: "network",
    }
    if asset.asset_type != Asset.TYPE_OTHER:
        return profiles.get(asset.asset_type)
    # Legacy imports may leave the type as OTHER. Use category metadata only,
    # never a device name/IP or an unauthorized monitoring relationship.
    aliases = {
        "stampante": "printer", "stampanti": "printer", "multifunzione": "printer",
        "mfc": "printer", "stampanti e multifunzione": "printer",
        "pc": "workstation", "computer": "workstation", "notebook": "workstation",
        "portatili": "workstation", "server": "server", "server fisici": "server",
        "vm": "vm", "macchine virtuali": "vm",
        "firewall": "network", "firewall e apparati rete": "network", "rete": "network",
        "apparati di rete": "network", "access point": "network", "switch": "network",
    }
    category = getattr(asset, "asset_category", None)
    seen = set()
    while category and category.pk not in seen and len(seen) < 8:
        seen.add(category.pk)
        if category.base_asset_type != Asset.TYPE_OTHER:
            return profiles.get(category.base_asset_type)
        match = aliases.get(category.label.strip().casefold())
        if match:
            return match
        category = category.parent
    return None


def workstation_context(asset):
    """Compatibility entry point for callers needing specifically a workstation."""
    return it_context(asset) if is_workstation(asset) else None


def it_context(asset):
    profile = it_profile(asset)
    if profile is None:
        return None
    details = getattr(asset, "it_details", None)
    checks = []
    if profile == "workstation" and not asset.assignment_to:
        checks.append("Assegnatario non indicato.")
    if profile != "vm" and not asset.assignment_location:
        checks.append("Posizione del dispositivo non indicata.")
    if profile not in ("printer", "network") and (not details or not details.os):
        checks.append("Sistema operativo da censire.")
    if profile in ("server", "vm"):
        checks.append("Referente tecnico, servizio e criticità non sono ancora censiti come dati dedicati.")
    if profile == "vm":
        checks.append("Host di virtualizzazione non collegato: non viene dedotto dal nome o dall'indirizzo IP.")
    declarations = []
    if details and profile not in ("printer", "network"):
        fields = [
            ("domain_joined", "Appartenenza al dominio"),
            ("edr_enabled", "EDR abilitato"),
            ("ad360_managed", "Gestione AD360"),
        ]
        if profile != "vm":
            fields.append(("bios_pwd_set", "Password BIOS impostata"))
        for key, label in fields:
            declarations.append({
                "label": label,
                "value": "Sì, dichiarato" if getattr(details, key) else "No / non verificato",
            })
    return {
        "profile": profile,
        "from_category": asset.asset_type == Asset.TYPE_OTHER,
        "mark": {"workstation": "PC", "server": "SRV", "vm": "VM", "printer": "MFC", "network": "NET"}[profile],
        "label": {"workstation": "Postazione IT", "server": "Server fisico", "vm": "Macchina virtuale", "printer": "Stampante / MFC", "network": "Firewall / apparato di rete"}[profile],
        "assignment_label": "Assegnatario" if profile == "workstation" else "Assegnazione censita",
        "location_label": "Posizione dichiarata" if profile == "vm" else "Posizione",
        "checks": checks,
        "endpoints": list(asset.endpoints.all()),
        "declarations": declarations,
        "has_details": details is not None,
    }
