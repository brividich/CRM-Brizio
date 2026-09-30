"""Importa la Control Matrix del MOD.165 (PDF) come nuova revisione in bozza della SoA.

Dry-run di default: mostra cosa verrebbe caricato. Con ``--apply`` crea la
revisione (stato Bozza) da far verificare e proporre alla Direzione nel portale.

    manage.py importa_soa_mod165 "\\\\server\\...\\MOD.165 - RAR ... Rev.3.pdf" --numero 3 --apply
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sistema_gestione.models import ControlloIso27002, SoaRevisione, SoaVoce
from sistema_gestione.services.mod165_import import Mod165FormatoNonRiconosciuto, leggi_control_matrix
from sistema_gestione.services.soa import TransizioneNonAmmessa, assicura_catalogo, nuova_revisione


class Command(BaseCommand):
    help = "Importa la Control Matrix del MOD.165 (PDF) come revisione in bozza della Dichiarazione di applicabilità."

    def add_arguments(self, parser):
        parser.add_argument("pdf", help="Percorso del PDF MOD.165 - RAR")
        parser.add_argument("--numero", type=int, default=None, help="Indice di revisione da assegnare (default: successivo)")
        parser.add_argument("--apply", action="store_true", help="Scrive nel database (default: dry-run)")

    def handle(self, *args, **options):
        try:
            righe = leggi_control_matrix(options["pdf"])
        except FileNotFoundError as exc:
            raise CommandError(f"File non trovato: {options['pdf']}") from exc
        except Mod165FormatoNonRiconosciuto as exc:
            raise CommandError(str(exc)) from exc

        assicura_catalogo()
        catalogo = set(ControlloIso27002.objects.values_list("codice", flat=True))
        trovati = {r.codice for r in righe}
        sconosciuti = sorted(trovati - catalogo)
        mancanti = sorted(catalogo - trovati, key=lambda c: [int(x) for x in c.split(".")])
        senza_livello = [r.codice for r in righe if r.livello is None]

        self.stdout.write(f"Controlli letti: {len(righe)} su {len(catalogo)}")
        for r in righe[:5]:
            self.stdout.write(f"  {r.codice}: livello {r.livello}, vulnerabilità {r.vulnerabilita}, rif. «{r.riferimenti[:60]}»")
        if sconosciuti:
            self.stdout.write(self.style.WARNING(f"Codici non in catalogo (ignorati): {', '.join(sconosciuti)}"))
        if mancanti:
            self.stdout.write(self.style.WARNING(f"Controlli assenti nel PDF (restano vuoti): {', '.join(mancanti)}"))
        if senza_livello:
            self.stdout.write(self.style.WARNING(f"Livello non leggibile: {', '.join(senza_livello)}"))

        if not options["apply"]:
            self.stdout.write(self.style.NOTICE("DRY-RUN: nessuna scrittura. Rilancia con --apply."))
            return

        numero = options["numero"]
        if numero is not None and SoaRevisione.objects.filter(numero=numero).exists():
            raise CommandError(f"Esiste già la revisione {numero}.")
        with transaction.atomic():
            try:
                revisione = nuova_revisione(
                    numero=numero, motivo="Import dal MOD.165", origine=f"Import PDF: {options['pdf']}"[:255],
                )
            except TransizioneNonAmmessa as exc:
                raise CommandError(str(exc)) from exc
            voci = {v.controllo.codice: v for v in revisione.voci.select_related("controllo")}
            aggiornate = 0
            for r in righe:
                voce = voci.get(r.codice)
                if voce is None:
                    continue
                voce.livello = r.livello if r.livello is not None else 0
                voce.vulnerabilita = (
                    r.vulnerabilita if r.vulnerabilita is not None
                    else SoaVoce.VULNERABILITA_DA_LIVELLO.get(voce.livello, 0)
                )
                voce.riferimenti = r.riferimenti
                voce.giustificazione = r.giustificazione
                for campo, valore in r.obblighi.items():
                    setattr(voce, campo, valore)
                voce.save()
                aggiornate += 1
        self.stdout.write(self.style.SUCCESS(
            f"Creata la revisione {revisione.numero} in bozza con {aggiornate} controlli importati: verificala e proponila nel portale."
        ))
