"""
Management command: rentri_catalogo_eer

Carica (sostituendolo) il catalogo EER usato per il confronto del codice nei
movimenti RENTRI. Il file è la decisione 2000/532/CE consolidata, salvata dal
browser da EUR-Lex (HTML o PDF), oppure un CSV ``codice;descrizione``.

Uso:
  python manage.py rentri_catalogo_eer elenco_eer.html
  python manage.py rentri_catalogo_eer elenco_eer.csv --dry-run
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from rentri.catalogo import esteso, leggi_file, sostituisci

# L'elenco europeo ha circa 840 voci: sotto questa soglia il file è quasi certamente sbagliato.
MIN_VOCI = 500


class Command(BaseCommand):
    help = "Carica il catalogo EER (elenco europeo dei rifiuti) da HTML/PDF EUR-Lex o CSV."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Percorso del file (.html, .pdf, .csv, .txt)")
        parser.add_argument("--dry-run", action="store_true", help="Legge e conta, senza salvare.")
        parser.add_argument("--forza", action="store_true", help=f"Salva anche con meno di {MIN_VOCI} voci.")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"File non trovato: {path}")
        voci = leggi_file(path.name, path.read_bytes())
        pericolosi = sum(1 for _, p, _ in voci if p)
        self.stdout.write(f"Voci lette: {len(voci)} (pericolose: {pericolosi})")
        for sei, peric, desc in voci[:5]:
            self.stdout.write(f"  {esteso(sei, peric)}  {desc[:80]}")
        if options["dry_run"]:
            self.stdout.write("Prova: niente salvato.")
            return
        if len(voci) < MIN_VOCI and not options["forza"]:
            raise CommandError(
                f"Solo {len(voci)} voci: il file non sembra l'elenco completo. Controllalo o usa --forza."
            )
        n = sostituisci(voci)
        self.stdout.write(self.style.SUCCESS(f"Catalogo EER aggiornato: {n} voci."))
