"""Read-only IT profiles; no inventory reclassification or inferred ownership."""
from assets.models import Asset


def is_workstation(asset):
    # An industrial extension wins even if an old import used the PC type.
    return (
        asset.asset_type in (Asset.TYPE_PC, Asset.TYPE_NOTEBOOK)
        and getattr(asset, "work_machine", None) is None
        and not asset.prodotto_chimico_id
    )


def it_profile(asset):
    if getattr(asset, "work_machine", None) is not None or asset.prodotto_chimico_id:
        return None
    return {
        Asset.TYPE_PC: "workstation", Asset.TYPE_NOTEBOOK: "workstation",
        Asset.TYPE_SERVER: "server", Asset.TYPE_VM: "vm", Asset.TYPE_STAMPANTE: "printer",
    }.get(asset.asset_type)


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
    if profile != "printer" and (not details or not details.os):
        checks.append("Sistema operativo da censire.")
    if profile in ("server", "vm"):
        checks.append("Referente tecnico, servizio e criticità non sono ancora censiti come dati dedicati.")
    if profile == "vm":
        checks.append("Host di virtualizzazione non collegato: non viene dedotto dal nome o dall'indirizzo IP.")
    declarations = []
    if details and profile != "printer":
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
        "label": {"workstation": "Postazione IT", "server": "Server fisico", "vm": "Macchina virtuale", "printer": "Stampante / MFC"}[profile],
        "assignment_label": "Assegnatario" if profile == "workstation" else "Assegnazione censita",
        "location_label": "Posizione dichiarata" if profile == "vm" else "Posizione",
        "checks": checks,
        "endpoints": list(asset.endpoints.all()),
        "declarations": declarations,
        "has_details": details is not None,
    }
