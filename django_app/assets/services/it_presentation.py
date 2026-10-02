"""Read-only presentation for the first IT profile; no inventory reclassification."""
from assets.models import Asset


def is_workstation(asset):
    # An industrial extension wins even if an old import used the PC type.
    return (
        asset.asset_type in (Asset.TYPE_PC, Asset.TYPE_NOTEBOOK)
        and getattr(asset, "work_machine", None) is None
        and not asset.prodotto_chimico_id
    )


def workstation_context(asset):
    if not is_workstation(asset):
        return None
    details = getattr(asset, "it_details", None)
    checks = []
    if not asset.assignment_to:
        checks.append("Assegnatario non indicato.")
    if not asset.assignment_location:
        checks.append("Posizione del dispositivo non indicata.")
    if not details or not details.os:
        checks.append("Sistema operativo da censire.")
    declarations = []
    if details:
        for key, label in (
            ("domain_joined", "Appartenenza al dominio"),
            ("edr_enabled", "EDR abilitato"),
            ("ad360_managed", "Gestione AD360"),
            ("bios_pwd_set", "Password BIOS impostata"),
        ):
            declarations.append({
                "label": label,
                "value": "Sì, dichiarato" if getattr(details, key) else "No / non verificato",
            })
    return {
        "checks": checks,
        "endpoints": list(asset.endpoints.all()),
        "declarations": declarations,
        "has_details": details is not None,
    }
