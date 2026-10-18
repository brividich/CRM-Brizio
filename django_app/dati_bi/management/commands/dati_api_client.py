"""Gestisce le applicazioni che leggono l'API dati ``/api/v1/``.

    python manage.py dati_api_client elenco
    python manage.py dati_api_client crea "Power BI direzione" --ambito scadenze --ambito manutenzione
    python manage.py dati_api_client ambiti "Power BI direzione" --ambito asset --ambito scadenze
    python manage.py dati_api_client rigenera "Power BI direzione"
    python manage.py dati_api_client disattiva "Power BI direzione"

Il token in chiaro si stampa una volta sola: a DB resta solo l'hash SHA-256.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from dati_bi.models import AMBITI, ApiClient


class Command(BaseCommand):
    help = "Crea, elenca, rigenera o disattiva le applicazioni dell'API dati (token stampato una volta sola)."

    def add_arguments(self, parser):
        parser.add_argument("azione", choices=["elenco", "crea", "rigenera", "ambiti", "disattiva", "riattiva"])
        parser.add_argument("nome", nargs="?", default="")
        parser.add_argument(
            "--ambito", action="append", default=[],
            help=f"Ambito consentito (ripetibile): {', '.join(AMBITI)}.",
        )
        parser.add_argument("--note", default="")

    def _ambiti(self, valori):
        sconosciuti = sorted(set(valori) - set(AMBITI))
        if sconosciuti:
            raise CommandError(f"Ambiti sconosciuti: {', '.join(sconosciuti)}. Validi: {', '.join(AMBITI)}.")
        return sorted(set(valori))

    def _stampa_token(self, client, token):
        self.stdout.write(self.style.WARNING(f"Token di «{client.nome}» (copialo ora, non verrà più mostrato):"))
        self.stdout.write(token)
        self.stdout.write("Uso: intestazione HTTP  Authorization: Bearer <token>")

    def handle(self, *args, **options):
        azione, nome = options["azione"], options["nome"].strip()
        if azione == "elenco":
            for c in ApiClient.objects.all():
                stato = "attiva" if c.attivo else "DISATTIVA"
                ultimo = c.ultimo_accesso.strftime("%d-%m-%Y %H:%M") if c.ultimo_accesso else "mai"
                self.stdout.write(f"{c.nome} · {stato} · ambiti: {', '.join(c.ambiti or []) or '—'} · ultimo accesso: {ultimo}")
            return
        if not nome:
            raise CommandError("Indica il nome dell'applicazione.")
        client = ApiClient.objects.filter(nome=nome).first()

        if azione == "crea":
            if client:
                raise CommandError(f"L'applicazione «{nome}» esiste già: usa «rigenera» per un token nuovo.")
            ambiti = self._ambiti(options["ambito"])
            if not ambiti:
                raise CommandError(f"Indica almeno un --ambito ({', '.join(AMBITI)}).")
            token = ApiClient.nuovo_token()
            client = ApiClient(nome=nome, ambiti=ambiti, note=options["note"])
            client.imposta_token(token)
            client.save()
            self._stampa_token(client, token)
            return

        if client is None:
            raise CommandError(f"Applicazione «{nome}» non trovata.")
        if azione == "rigenera":
            token = ApiClient.nuovo_token()
            client.imposta_token(token)
            client.save(update_fields=["token_hash"])
            self._stampa_token(client, token)
        elif azione == "ambiti":
            client.ambiti = self._ambiti(options["ambito"])
            client.save(update_fields=["ambiti"])
            self.stdout.write(self.style.SUCCESS(f"Ambiti di «{nome}»: {', '.join(client.ambiti) or '—'}"))
        elif azione in ("disattiva", "riattiva"):
            client.attivo = azione == "riattiva"
            client.save(update_fields=["attivo"])
            self.stdout.write(self.style.SUCCESS(f"«{nome}» {'riattivata' if client.attivo else 'disattivata'}."))
