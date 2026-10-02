"""Normalizza il nominativo degli utenti del portale (``utenti.nome``) in ``COGNOME NOME``.

``utenti.nome`` alimenta le tendine di assegnatari, responsabili e ACL. Nasce dal
displayName di Active Directory (in azienda già «Cognome Nome») o da inserimenti
a mano, con il maiuscolo che capitava. Da qui in avanti login AD, ``sync_ldap_users``
e form di amministrazione scrivono già nel formato unico; questo comando sistema
una volta sola le righe presenti:

- utente riconducibile a un dipendente (``anagrafica_dipendenti.utente_id``, stessa
  email di login o alias = parte locale dell'email) → nominativo dell'anagrafica,
  che ha nome e cognome separati e quindi l'ordine certo;
- altrimenti → stesso testo, in MAIUSCOLO (l'ordine non si può dedurre).

Il nome/cognome dell'utente Django collegato viene riallineato insieme.

Uso:
    python manage.py normalizza_nomi_utenti           # anteprima, non scrive
    python manage.py normalizza_nomi_utenti --apply
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connections, transaction

from core import naming
from core.legacy_utils import _split_name


class Command(BaseCommand):
    help = (
        "Uniforma utenti.nome nel formato COGNOME NOME maiuscolo "
        "(dry-run di default, --apply per scrivere)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Scrive le modifiche. Senza questo flag il comando è di sola lettura.",
        )

    def handle(self, *args, **options):
        applica = bool(options.get("apply"))

        with connections["default"].cursor() as cur:
            cur.execute("SELECT id, nome, email FROM utenti ORDER BY id")
            utenti = cur.fetchall()
            cur.execute(
                "SELECT nome, cognome, email, aliasusername, utente_id FROM anagrafica_dipendenti"
            )
            anagrafica = cur.fetchall()

        per_utente: dict[int, set[str]] = {}
        per_email: dict[str, set[str]] = {}
        per_alias: dict[str, set[str]] = {}
        for nome, cognome, email, alias, utente_id in anagrafica:
            nominativo = naming.nome_completo(nome, cognome)
            if not nominativo:
                continue
            if utente_id:
                per_utente.setdefault(int(utente_id), set()).add(nominativo)
            if (email or "").strip():
                per_email.setdefault(email.strip().lower(), set()).add(nominativo)
            if (alias or "").strip():
                per_alias.setdefault(alias.strip().lower(), set()).add(nominativo)

        def _da_anagrafica(user_id: int, email: str) -> str:
            email = (email or "").strip().lower()
            locale = email.split("@", 1)[0] if "@" in email else ""
            for candidati in (per_utente.get(user_id), per_email.get(email), per_alias.get(locale)):
                # Più dipendenti con nominativi diversi: ambiguo, meglio non scegliere.
                if candidati and len(candidati) == 1:
                    return next(iter(candidati))
            return ""

        da_cambiare = []
        senza_anagrafica = 0
        for user_id, nome, email in utenti:
            nuovo = _da_anagrafica(int(user_id), email)
            if not nuovo:
                senza_anagrafica += 1
                nuovo = naming.normalizza_parte(nome)
            if nuovo and nuovo != (nome or ""):
                da_cambiare.append((int(user_id), nome or "", nuovo))

        self.stdout.write(f"Utenti esaminati: {len(utenti)}")
        self.stdout.write(f"Senza dipendente collegato (solo maiuscolo): {senza_anagrafica}")
        self.stdout.write(f"Da normalizzare: {len(da_cambiare)}")
        for user_id, vecchio, nuovo in da_cambiare:
            self.stdout.write(f"  [{user_id}] {vecchio}  ->  {nuovo}")

        if not da_cambiare:
            self.stdout.write(self.style.SUCCESS("Nessuna modifica necessaria."))
            return
        if not applica:
            self.stdout.write(
                self.style.WARNING("Dry-run: nessuna modifica scritta. Rilancia con --apply.")
            )
            return

        from django.contrib.auth import get_user_model

        from core.models import Profile

        User = get_user_model()
        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cur:
                for user_id, _vecchio, nuovo in da_cambiare:
                    cur.execute("UPDATE utenti SET nome = %s WHERE id = %s", [nuovo, user_id])
            django_ids = dict(
                Profile.objects.filter(legacy_user_id__in=[u for u, _v, _n in da_cambiare])
                .values_list("legacy_user_id", "user_id")
            )
            for user_id, _vecchio, nuovo in da_cambiare:
                if user_id in django_ids:
                    first_name, last_name = _split_name(nuovo)
                    User.objects.filter(pk=django_ids[user_id]).update(
                        first_name=first_name[:150], last_name=last_name[:150]
                    )

        self.stdout.write(self.style.SUCCESS(f"Normalizzati {len(da_cambiare)} utenti."))
