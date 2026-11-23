"""Ambiente di test sul server: stesso codice della produzione, chiuso verso l'esterno.

Si accende con ``HUB_AMBIENTE_TEST=1`` nel ``.env`` dell'ambiente di test (le impostazioni
restano ``config.settings.prod``, come per ogni ambiente distribuito). Serve quando il
database di test è una copia di quello di produzione con dati reali: senza queste barriere
il portale manderebbe mail vere e farebbe partire le automazioni.

Barriere, tutte in ``config/settings/prod.py``:

- ogni database deve avere «TEST» nel nome, altrimenti il portale non parte;
- la posta finisce in file sotto ``logs/mail_test``;
- le connessioni Python verso l'esterno sono bloccate (``config/rete_guard.py``), tranne
  i server del login di dominio e gli host elencati in ``HUB_TEST_HOST_CONSENTITI``;
- ``qcluster`` e il poller della coda automazioni non partono;
- ogni pagina mostra l'etichetta «Ambiente di test».

Procedura: ``docs/deploy/AMBIENTE_TEST.md``.
"""
from __future__ import annotations

import re

COMANDI_FERMI = ("qcluster", "process_automation_queue")


def host_da_uri(testo: str) -> list[str]:
    """Host di uno o più indirizzi (``ldap://dc1.example.local:389 dc2``), senza schema e porta."""
    host = []
    for pezzo in re.split(r"[\s,;]+", str(testo or "").strip()):
        pezzo = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", pezzo).split("/", 1)[0]
        if pezzo.startswith("["):  # IPv6 fra quadre
            pezzo = pezzo[1:].split("]", 1)[0]
        elif pezzo.count(":") == 1:
            pezzo = pezzo.split(":", 1)[0]
        if pezzo:
            host.append(pezzo.lower())
    return host


def host_consentiti(ldap_server: str = "", ldap_domain: str = "", extra=()) -> set[str]:
    """Host verso cui l'ambiente di test può aprire connessioni: il login di dominio e le aggiunte."""
    host = set(host_da_uri(ldap_server)) | set(host_da_uri(ldap_domain))
    for voce in extra or ():
        host.update(host_da_uri(voce))
    return host


def controlla_nome_db(alias: str, nome) -> None:
    """Il database dell'ambiente di test deve dichiararsi tale nel nome."""
    if "TEST" not in str(nome or "").upper():
        raise RuntimeError(
            f"Ambiente di test: il database «{alias}» si chiama {str(nome or '')!r}. "
            "Con HUB_AMBIENTE_TEST=1 ogni database deve avere TEST nel nome, "
            "così l'ambiente di test non può puntare al database di produzione."
        )


def comando_fermo(argv) -> str:
    """Il comando di ``manage.py`` che nell'ambiente di test non deve partire, oppure ''."""
    for comando in COMANDI_FERMI:
        if comando in list(argv or ())[1:3]:
            return comando
    return ""
