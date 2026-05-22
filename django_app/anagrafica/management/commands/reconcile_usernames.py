"""Allinea lo username dell'account portale all'aliasusername dell'anagrafica.

`anagrafica_dipendenti.aliasusername` è la fonte di verità dello username.
Questo comando confronta, per ogni dipendente con account portale collegato
(`utente_id` -> `Profile.legacy_user_id` -> Django `User`), l'`aliasusername`
con `User.username` e, con `--apply`, allinea il secondo al primo.

Senza `--apply` esegue solo un dry-run (nessuna scrittura).

Esempi:
    python manage.py reconcile_usernames                # dry-run, elenca i disallineamenti
    python manage.py reconcile_usernames --apply        # applica l'allineamento
    python manage.py reconcile_usernames --legacy-id 395 --apply
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from core.legacy_anagrafica import fetch_anagrafica_rows, normalize_legacy_alias
from core.models import Profile


class Command(BaseCommand):
    help = "Allinea User.username all'aliasusername dell'anagrafica dipendente."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Applica le modifiche. Senza questo flag esegue solo un dry-run.",
        )
        parser.add_argument(
            "--legacy-id",
            type=int,
            default=None,
            help="Limita la riconciliazione a un singolo dipendente (id anagrafica).",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        only_id = options.get("legacy_id")
        User = get_user_model()

        rows = fetch_anagrafica_rows(deduplicate=True)
        if only_id:
            rows = [r for r in rows if int(r.get("id") or 0) == int(only_id)]

        utente_ids = [int(r.get("utente_id") or 0) for r in rows if int(r.get("utente_id") or 0) > 0]
        profiles = {
            int(p.legacy_user_id): p
            for p in Profile.objects.select_related("user").filter(legacy_user_id__in=utente_ids)
            if p.legacy_user_id
        }

        aligned = no_account = no_alias = skipped_conflict = 0
        pending: list[tuple[Profile, str, str, int]] = []

        for row in rows:
            dip_id = int(row.get("id") or 0)
            utente_id = int(row.get("utente_id") or 0)
            alias = normalize_legacy_alias(str(row.get("aliasusername") or ""))
            if not alias:
                no_alias += 1
                continue
            profile = profiles.get(utente_id) if utente_id > 0 else None
            if not profile or not profile.user_id:
                no_account += 1
                continue
            current = profile.user.username or ""
            if current == alias:
                aligned += 1
                continue
            conflict = (
                User.objects.filter(username__iexact=alias)
                .exclude(id=profile.user_id)
                .first()
            )
            if conflict:
                skipped_conflict += 1
                self.stdout.write(self.style.WARNING(
                    f"  CONFLITTO   dip#{dip_id}  '{current}' -> '{alias}'  "
                    f"(username già usato da user#{conflict.id})"
                ))
                continue
            pending.append((profile, current, alias, dip_id))

        for profile, current, alias, dip_id in pending:
            verb = "AGGIORNO    " if apply_changes else "DA ALLINEARE"
            self.stdout.write(
                f"  {verb} dip#{dip_id}  user#{profile.user_id}  '{current}' -> '{alias}'"
            )

        fixed = 0
        if apply_changes and pending:
            with transaction.atomic():
                for profile, current, alias, dip_id in pending:
                    profile.user.username = alias
                    profile.user.save(update_fields=["username"])
                    fixed += 1

        self.stdout.write("")
        self.stdout.write("Riepilogo riconciliazione username:")
        self.stdout.write(f"  Già allineati .............. {aligned}")
        self.stdout.write(f"  Disallineati ............... {len(pending)}")
        self.stdout.write(f"  {'Allineati ora' if apply_changes else 'Allineabili'} .............. {fixed if apply_changes else len(pending)}")
        self.stdout.write(f"  Saltati per conflitto ...... {skipped_conflict}")
        self.stdout.write(f"  Senza account portale ...... {no_account}")
        self.stdout.write(f"  Senza aliasusername ........ {no_alias}")
        if not apply_changes and pending:
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE("Dry-run: nessuna modifica scritta. Rilancia con --apply per applicare."))
        elif apply_changes:
            self.stdout.write(self.style.SUCCESS(f"Fatto: {fixed} username allineati."))
