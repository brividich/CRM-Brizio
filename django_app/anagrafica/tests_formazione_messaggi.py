"""Le pagine Formazione devono mostrare i messaggi di sistema.

Difetto che questo test blinda: le view chiamavano `messages.error(...)` e
`messages.success(...)`, ma **23 pagine su 24** non includevano il partial che
li rende — quindi l'utente agiva, l'operazione falliva, e la pagina tornava
identica senza dire nulla. È un difetto invisibile per costruzione: nessun test
funzionale lo coglieva, perché le view rispondevano correttamente.

Il controllo è sul *sorgente* dei template e non su una risposta HTTP di
proposito: coprire 24 pagine con altrettanti test end-to-end (ognuna con i suoi
permessi, oggetti e parametri) costerebbe molto e proteggerebbe meno — qui
l'invariante è «nessuna pagina Formazione dimentica l'include», e si verifica
esattamente così.
"""
from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

PAGINE = Path(__file__).resolve().parent / "templates" / "anagrafica" / "pages"
INCLUDE = "anagrafica/components/flash_messages.html"


def _pagine_formazione() -> list[Path]:
    return sorted(PAGINE.glob("formazione_*.html"))


class MessaggiFormazioneTests(SimpleTestCase):
    def test_ci_sono_pagine_da_controllare(self):
        """Se la cartella cambia nome, il test non deve passare a vuoto."""
        self.assertGreater(len(_pagine_formazione()), 15)

    def test_ogni_pagina_formazione_mostra_i_messaggi(self):
        senza_include = []
        for pagina in _pagine_formazione():
            testo = pagina.read_text(encoding="utf-8")
            # Il registro presenze è un documento HTML a sé (pagina di stampa,
            # senza shell applicativa): non ha messaggi da mostrare.
            if "<!DOCTYPE html>" in testo:
                continue
            if INCLUDE not in testo:
                senza_include.append(pagina.name)

        self.assertEqual(
            senza_include, [],
            "Queste pagine Formazione chiamano messages.* ma non lo mostrano a nessuno: "
            f"{senza_include}. Aggiungi {{% include \"{INCLUDE}\" %}} dentro il guscio di pagina.",
        )

    def test_include_una_sola_volta_per_pagina(self):
        """Due include = messaggio doppio: `messages` è consumato una volta sola."""
        doppioni = [
            p.name for p in _pagine_formazione()
            if p.read_text(encoding="utf-8").count(INCLUDE) > 1
        ]
        self.assertEqual(doppioni, [], f"Include duplicato in: {doppioni}")
