"""Moduli trasversali di core nel sistema dei permessi (core.permessi).

``piattaforma`` raccoglie i permessi tecnici (setup, monitoring, BrizioHUB,
API di servizio, health): resta all'Amministratore. Login e logout stanno in
«bacheca» (dashboard), la dotazione base che ogni preset concede. Le pagine aperte a
ogni utente autenticato (notifiche, onboarding, ricerca, home personale) non
passano dai permessi: sono in ``core.middleware._ACL_SHARED_ROUTE_NAMES``.
"""
from core.permessi.registro import ModuloPermessi, registra_modulo

registra_modulo(ModuloPermessi(
    chiave="capa",
    nome="Azioni CAPA",
    descrizione="Azioni correttive e preventive trasversali.",
    area="Qualità",
    app="core",
    moduli_acl=("capa",),
    codici_acl=("legacy.core.capa_manage",),
))

# Visitatori della reception (GuestPortal e pannello Reception dell'HUB, app ``reception``). La chiave
# resta «portale_ospiti» perché le celle dei ruoli già salvate la usano; non è il Wi-Fi ospiti.
#   Vedere      -> Accessi esterni, Presenti, Storico, scheda visita, Richieste (dati personali: con giudizio)
#   Creare / Modificare / Cancellare -> registrare ingressi e uscite, pre-registrazioni, richieste,
#                  referenti, ditte, cartellini (reception.pannello.manage, reception 0006)
#   Impostazioni -> Reception → Impostazioni (reception.impostazioni.manage, core/permessi/impostazioni.py)
registra_modulo(ModuloPermessi(
    chiave="portale_ospiti",
    nome="Reception e visitatori",
    descrizione="Accessi esterni e pannello Reception: presenti, ingressi, pre-registrazioni, richieste, referenti, ditte, cartellini.",
    area="Persone",
    app="core",
    moduli_acl=("portale_esterno",),
    capacita_forzate=(
        ("legacy.portale_esterno.portale_esterno", "lettura"),
        ("reception.pannello.manage", "modifica"),
    ),
))

registra_modulo(ModuloPermessi(
    chiave="piattaforma",
    nome="Piattaforma (tecnico)",
    descrizione="Setup, monitoring, BrizioHUB, API di servizio: solo amministratori.",
    area="Piattaforma",
    app="core",
    moduli_acl=(
        "hub_tools", "setup_wizard", "monitoring", "monitoring_admin", "api",
        "approval_proxy", "health", "healthz", "readyz",
        "version", "check", "coming", "modifica_capo", "modifica_info_completa",
        "gestione_reparto",
    ),
    solo_amministratore=True,
))
