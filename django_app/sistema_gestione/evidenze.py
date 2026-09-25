"""Evidenza viva: controlli ISO 27002 per cui il portale calcola già un'evidenza.

Ogni voce punta a un report della sezione Report conformità (che applica il suo
ACL) o a una pagina di questo modulo. È un aiuto a chi compila e a chi fa
l'audit, non sostituisce la giustificazione del MOD.165.
"""
from __future__ import annotations

from django.urls import NoReverseMatch, reverse

_REPORT = "report_conformita:report"

EVIDENZE: dict[str, tuple[tuple[str, str, str], ...]] = {
    "5.7": (("Registro threat intelligence", "sistema_gestione:threat_intelligence", ""),),
    "5.9": (("Inventario asset IT", _REPORT, "inventario-it"),),
    "5.11": (("Revisione accessi (uscite)", _REPORT, "revisione-accessi"),),
    "5.15": (("Revisione degli accessi", _REPORT, "revisione-accessi"),),
    "5.16": (("Revisione degli accessi", _REPORT, "revisione-accessi"),),
    "5.17": (("Revisione accessi (2FA)", _REPORT, "revisione-accessi"),),
    "5.18": (("Revisione degli accessi", _REPORT, "revisione-accessi"),),
    "5.19": (("Albo fornitori", _REPORT, "albo-fornitori"),),
    "5.20": (("Albo fornitori", _REPORT, "albo-fornitori"),),
    "5.21": (("Albo fornitori", _REPORT, "albo-fornitori"),),
    "5.22": (("Albo fornitori", _REPORT, "albo-fornitori"),),
    "5.24": (("Backup, vulnerabilità e rimedi", _REPORT, "sicurezza-it"),),
    "5.25": (("Backup, vulnerabilità e rimedi", _REPORT, "sicurezza-it"),),
    "5.26": (("Backup, vulnerabilità e rimedi", _REPORT, "sicurezza-it"),),
    "5.27": (("Backup, vulnerabilità e rimedi", _REPORT, "sicurezza-it"),),
    "5.32": (("Licenze software", _REPORT, "licenze-software"),),
    "5.36": (("Registro NC/OFI", _REPORT, "registro-nc-ofi"),),
    "5.37": (("Presa visione procedure", _REPORT, "presa-visione"),),
    "6.3": (("Competenze e formazione", _REPORT, "competenze"),),
    "6.5": (("Revisione accessi (uscite)", _REPORT, "revisione-accessi"),),
    "7.13": (("Manutenzione apparecchiature", _REPORT, "manutenzione"),),
    "8.1": (("Inventario asset IT", _REPORT, "inventario-it"),),
    "8.2": (("Revisione accessi (amministratori)", _REPORT, "revisione-accessi"),),
    "8.5": (("Revisione accessi (2FA)", _REPORT, "revisione-accessi"),),
    "8.7": (("Backup, vulnerabilità e rimedi", _REPORT, "sicurezza-it"),),
    "8.8": (("Backup, vulnerabilità e rimedi", _REPORT, "sicurezza-it"),),
    "8.13": (("Backup, vulnerabilità e rimedi", _REPORT, "sicurezza-it"),),
    "8.16": (("Backup, vulnerabilità e rimedi", _REPORT, "sicurezza-it"),),
}


def evidenze_per(codice: str) -> list[tuple[str, str]]:
    out = []
    for label, route, arg in EVIDENZE.get(codice, ()):
        try:
            url = reverse(route, args=[arg]) if arg else reverse(route)
        except NoReverseMatch:
            continue
        out.append((label, url))
    return out
