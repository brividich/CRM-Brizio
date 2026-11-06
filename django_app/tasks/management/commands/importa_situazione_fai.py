"""Porta il file «Situazione FAI-ISIR» nel Registro FAI. Senza --apply non scrive nulla."""
import csv

from django.core.management.base import BaseCommand, CommandError

from tasks.services.fai_import import FileNonValido, importa


class Command(BaseCommand):
    help = "Importa il file Situazione FAI-ISIR nel Registro FAI (prova, se manca --apply)."

    def add_arguments(self, parser):
        parser.add_argument("percorso", help="File .xlsm o .xlsx")
        parser.add_argument("--apply", action="store_true", help="Scrive davvero nel database")
        parser.add_argument("--report", help="CSV con le righe scartate e i valori da rivedere")

    def handle(self, *args, **opzioni):
        try:
            esito = importa(opzioni["percorso"], applica=opzioni["apply"])
        except (FileNonValido, OSError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write("IMPORTATO" if opzioni["apply"] else "PROVA: non è stato scritto nulla")
        for etichetta, valore in (
            ("Righe lette", esito.righe),
            ("FAI nuovi", esito.creati),
            ("FAI aggiornati", esito.aggiornati),
            ("FAI invariati", esito.invariati),
            ("Modificati nel portale, non toccati", esito.modificati_nel_portale),
            ("Righe scartate", esito.scartate),
            ("Articoli nuovi", esito.articoli_nuovi),
            ("Date non leggibili", esito.date_illeggibili),
            ("Celle in errore (#REF!)", esito.celle_errore),
            ("Testi troncati", esito.testi_troncati),
            ("Cross-correlation non riconosciute", esito.cross_non_riconosciute),
        ):
            self.stdout.write(f"{etichetta}: {valore}")
        self.stdout.write("Stati:")
        for stato, conta in esito.stati.most_common():
            self.stdout.write(f"  {stato}: {conta}")

        if opzioni.get("report"):
            with open(opzioni["report"], "w", newline="", encoding="utf-8-sig") as uscita:
                scrittore = csv.writer(uscita, delimiter=";")
                scrittore.writerow(["Riga del file", "Colonna", "Motivo"])
                for riga, motivo in esito.scarti:
                    scrittore.writerow([riga, "", motivo])
                for riga, colonna, motivo in esito.avvisi:
                    scrittore.writerow([riga, colonna, motivo])
            self.stdout.write(f"Dettaglio: {opzioni['report']}")
