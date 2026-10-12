"""Moduli trasversali di core nel sistema dei permessi (core.permessi).

``piattaforma`` raccoglie i permessi tecnici (setup, monitoring, BrizioHUB,
API di servizio, login/health): resta all'Amministratore. Le pagine aperte a
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

registra_modulo(ModuloPermessi(
    chiave="portale_ospiti",
    nome="Portale ospiti (Wi-Fi)",
    descrizione="Collegamento al pannello del portale ospiti.",
    area="IT",
    app="core",
    moduli_acl=("portale_esterno",),
))

registra_modulo(ModuloPermessi(
    chiave="piattaforma",
    nome="Piattaforma (tecnico)",
    descrizione="Setup, monitoring, BrizioHUB, API di servizio: solo amministratori.",
    area="Piattaforma",
    app="core",
    moduli_acl=(
        "hub_tools", "setup_wizard", "monitoring", "monitoring_admin", "api",
        "approval_proxy", "login", "logout", "health", "healthz", "readyz",
        "version", "check", "coming", "modifica_capo", "modifica_info_completa",
        "gestione_reparto",
    ),
    solo_amministratore=True,
))
