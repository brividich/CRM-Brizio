"""Collega ogni ruolo in azienda ai suoi accessi al portale (mappa in ``services/accessi_ruoli.py``).

    python manage.py allinea_accessi_ruoli            # prova: mostra cosa cambierebbe
    python manage.py allinea_accessi_ruoli --applica  # applica

Dopo l'applicazione: Ruoli e permessi → Sistema → «Sincronizza i permessi delle pagine».
"""
from __future__ import annotations

import sys

from django.core.management.base import BaseCommand

from anagrafica.services.accessi_ruoli import allinea


class Command(BaseCommand):
    help = "Allinea i ruoli del portale concessi da ogni ruolo in azienda (prova di default, --applica per salvare)."

    def add_arguments(self, parser):
        parser.add_argument("--applica", action="store_true", help="Salva le modifiche (senza: solo prova).")

    def _scrivi(self, testo: str) -> None:
        # Console di produzione in cp1252: niente caratteri che non sa scrivere.
        enc = getattr(self.stdout, "encoding", None) or getattr(sys.stdout, "encoding", None) or "utf-8"
        self.stdout.write(testo.encode(enc, errors="replace").decode(enc))

    def handle(self, *args, **opts):
        esito = allinea(applica=opts["applica"])
        self._scrivi("APPLICATO" if esito["applicato"] else "PROVA (nessuna modifica salvata)")
        self._scrivi(f"\nRuoli in azienda che cambiano: {len(esito['righe'])}")
        for r in esito["righe"]:
            stato = "" if r["ruolo"].is_active else " [disattivato]"
            self._scrivi(f"  {r['ruolo'].nome}{stato} ({r['persone']} persone): "
                         f"{', '.join(r['prima']) or 'nessuno'} -> {', '.join(r['dopo']) or 'solo ruolo base'}")
        self._scrivi("\nPersone che ricevono (per ruolo del portale):")
        for nome, n in esito["ricevuti"].most_common():
            self._scrivi(f"  +{n:3d}  {nome}")
        self._scrivi("Persone che perdono:")
        for nome, n in esito["tolti"].most_common():
            self._scrivi(f"  -{n:3d}  {nome}")
        if esito["non_mappati"]:
            self._scrivi("\nRuoli NON nella mappa (lasciati come sono):")
            for r, attuali in esito["non_mappati"]:
                self._scrivi(f"  {r.nome}: {', '.join(attuali) or 'nessun collegamento'}")
        if esito["mancanti"]:
            self._scrivi("\nRuoli del portale non trovati (saltati): " + ", ".join(esito["mancanti"]))
        if esito["applicato"]:
            self._scrivi("\nOra: Ruoli e permessi -> Sistema -> «Sincronizza i permessi delle pagine».")
