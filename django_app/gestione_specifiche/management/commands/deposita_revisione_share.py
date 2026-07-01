"""Deposita una nuova revisione PDF sulla share master (F2), con dry-run/rollback/audit.

DRY-RUN di default: mostra il PIANO (path canonico, file superato -> _SUPERATO, collisioni)
senza toccare nulla. Con ``--apply`` esegue (rollback automatico in caso di errore).

Esempi::

    # elenco cartelle reali selezionabili (per --cartella)
    python manage.py deposita_revisione_share --lista-cartelle

    # dry-run: deposita rev per la Specifica pk=123 dal PDF indicato
    python manage.py deposita_revisione_share --pk 123 --sorgente "C:/tmp/nuova.pdf"

    # esecuzione reale (archivia la precedente in _SUPERATO, aggiorna il collegamento)
    python manage.py deposita_revisione_share --pk 123 --sorgente "C:/tmp/nuova.pdf" --apply
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from gestione_specifiche.models import Specifica
from gestione_specifiche.share_write import elenca_cartelle_consentite, esegui


def _ascii(s) -> str:
    return str(s or "").encode("ascii", "replace").decode("ascii")


class Command(BaseCommand):
    help = "Deposita una nuova revisione PDF sulla share master (dry-run di default; --apply per eseguire)."

    def add_arguments(self, parser):
        parser.add_argument("--pk", type=int, default=0, help="PK della Specifica destinataria.")
        parser.add_argument("--codice", default="", help="Codice (con --revisione) se non si usa --pk.")
        parser.add_argument("--revisione", default="", help="Revisione (con --codice) se non si usa --pk.")
        parser.add_argument("--sorgente", default="", help="Percorso del PDF della nuova revisione.")
        parser.add_argument("--cartella", default="", help="Cartella ESISTENTE di destinazione (default: quella della revisione corrente).")
        parser.add_argument("--nome", default="", help="Nome file esatto (override); default: numero documento del file attuale + REV.<spec.revisione>.")
        parser.add_argument("--forza", action="store_true", help="In caso di collisione, archivia l'esistente in _SUPERATO e scrive comunque.")
        parser.add_argument("--attore", default="", help="Username da registrare nell'audit.")
        parser.add_argument("--apply", action="store_true", help="Esegue realmente (default: dry-run).")
        parser.add_argument("--lista-cartelle", action="store_true", help="Stampa le cartelle reali selezionabili ed esce.")

    def handle(self, *args, **opts):
        if opts["lista_cartelle"]:
            self._lista_cartelle()
            return

        spec = self._risolvi_specifica(opts)
        sorgente = (opts.get("sorgente") or "").strip()
        if not sorgente:
            raise CommandError("Indicare --sorgente (percorso del PDF della nuova revisione).")

        attore = None
        if opts.get("attore"):
            attore = get_user_model().objects.filter(username=opts["attore"]).first()
            if attore is None:
                self.stdout.write(self.style.WARNING(f"  attore '{_ascii(opts['attore'])}' non trovato: audit senza attore."))

        cartella = (opts.get("cartella") or "").strip() or None
        nome = (opts.get("nome") or "").strip() or None
        apply = bool(opts.get("apply"))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Deposito revisione share (Specifica {spec.pk}: {_ascii(spec.codice)} rev {_ascii(spec.revisione)}) "
            + ("[APPLY]" if apply else "[DRY-RUN]")
        ))
        piano = esegui(spec, sorgente, cartella=cartella, nome=nome, forza=bool(opts.get("forza")),
                       apply=apply, attore=attore)

        for riga in piano.descrizione():
            self.stdout.write("  " + _ascii(riga))

        if piano.esito == "ok" and not apply:
            self.stdout.write(self.style.NOTICE("  (dry-run) nessuna scrittura eseguita; rilancia con --apply per applicare."))
        elif piano.esito == "ok" and apply:
            self.stdout.write(self.style.SUCCESS("  OK: nuova revisione depositata e collegamento aggiornato."))
        elif piano.esito == "identico":
            self.stdout.write(self.style.SUCCESS("  Nessuna azione: file identico gia' presente (idempotente)."))
        elif piano.esito == "collisione":
            self.stdout.write(self.style.WARNING("  COLLISIONE: usa --forza per archiviare l'esistente in _SUPERATO."))
        elif piano.esito == "errore":
            raise CommandError("Deposito fallito (rollback eseguito): " + _ascii(piano.note))
        elif piano.esito in ("nome_richiesto", "cartella_richiesta"):
            self.stdout.write(self.style.WARNING("  Serve piu' input (usa --nome e/o --cartella): " + _ascii(piano.note)))
        else:
            self.stdout.write(self.style.WARNING(f"  esito '{_ascii(piano.esito)}': nessuna scrittura."))

    # ------------------------------------------------------------------ helpers
    def _risolvi_specifica(self, opts) -> Specifica:
        if opts.get("pk"):
            spec = Specifica.objects.filter(pk=opts["pk"]).first()
            if spec is None:
                raise CommandError(f"Specifica pk={opts['pk']} non trovata.")
            return spec
        codice = (opts.get("codice") or "").strip()
        if not codice:
            raise CommandError("Indicare --pk oppure --codice (+ --revisione).")
        qs = Specifica.objects.filter(codice=codice)
        if opts.get("revisione"):
            qs = qs.filter(revisione=opts["revisione"])
        n = qs.count()
        if n == 0:
            raise CommandError(f"Nessuna Specifica per codice '{_ascii(codice)}'.")
        if n > 1:
            raise CommandError(f"Piu' Specifiche per codice '{_ascii(codice)}': precisare --revisione o usare --pk.")
        return qs.first()

    def _lista_cartelle(self) -> None:
        cartelle = elenca_cartelle_consentite()
        self.stdout.write(self.style.MIGRATE_HEADING(f"Cartelle selezionabili sulla share ({len(cartelle)}):"))
        if not cartelle:
            self.stdout.write(self.style.WARNING("  nessuna (radici share non configurate o non raggiungibili)."))
            return
        for c in cartelle:
            self.stdout.write(f"  [{_ascii(c['label'])}]  {_ascii(c['path'])}")
