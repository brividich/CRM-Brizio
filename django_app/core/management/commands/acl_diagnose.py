"""Diagnosi ACL per-utente/ruolo su una route o path specifico.

Risponde alla domanda operativa "perche' l'utente X non riesce ad accedere a
/path/?" ricostruendo la stessa decisione che prende il middleware a runtime
(``core.acl_v2.resolve_acl_access``) e spiegandola in chiaro, con il suggerimento
su dove intervenire (grant canonico vs permesso legacy).

Non introduce logica ACL nuova: e' un wrapper CLI sulla diagnostica gia' usata
dalla pagina /admin-portale/acl-diagnostica/.

Esempi:
    python manage.py acl_diagnose --user a.astarita --path /tickets/
    python manage.py acl_diagnose --user mario.rossi@example.com --route tickets:dashboard
    python manage.py acl_diagnose --role Manutenzione --path /tickets/
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.urls import NoReverseMatch, reverse

from core.acl_v2 import diagnose_acl_access
from core.legacy_models import AnagraficaDipendente, Ruolo, UtenteLegacy


class Command(BaseCommand):
    help = (
        "Diagnostica ACL per-utente/ruolo su una route o path: spiega la "
        "decisione (canonico vs fallback legacy) e dove intervenire."
    )

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument(
            "--user",
            help="Utente: email (UPN), aliasusername o ID legacy numerico.",
        )
        target.add_argument(
            "--role",
            help="Simula un ruolo legacy senza utente: nome ruolo o ID numerico.",
        )
        where = parser.add_mutually_exclusive_group(required=True)
        where.add_argument("--path", help="Path da verificare (es. /tickets/).")
        where.add_argument("--route", help="Route name da verificare (es. tickets:dashboard).")
        parser.add_argument(
            "--format", choices=("text", "json"), default="text",
            help="Formato output (default: text).",
        )

    def handle(self, *args, **opts):
        legacy_user = self._resolve_target(opts)
        path = self._resolve_path(opts)

        diag = diagnose_acl_access(path=path, legacy_user=legacy_user, django_user=None)

        if (opts.get("format") or "text") == "json":
            self.stdout.write(json.dumps(diag, indent=2, default=str))
            return

        self._render_text(diag, legacy_user)

    # ------------------------------------------------------------------ target

    def _resolve_target(self, opts) -> UtenteLegacy:
        raw_user = (opts.get("user") or "").strip()
        raw_role = (opts.get("role") or "").strip()

        if raw_user:
            return self._resolve_user(raw_user)
        return self._simulate_role(raw_role)

    def _resolve_user(self, value: str) -> UtenteLegacy:
        if value.isdigit():
            user = UtenteLegacy.objects.filter(id=int(value)).first()
            if user is None:
                raise CommandError(f"Nessun utente legacy con ID {value}.")
            return user

        user = UtenteLegacy.objects.filter(email__iexact=value).first()
        if user is None:
            # aliasusername vive su anagrafica_dipendenti -> risali a utente_id
            anagrafica = (
                AnagraficaDipendente.objects.filter(
                    Q(aliasusername__iexact=value) | Q(email__iexact=value)
                )
                .exclude(utente__isnull=True)
                .select_related("utente")
                .first()
            )
            if anagrafica is not None:
                user = anagrafica.utente
        if user is None:
            user = UtenteLegacy.objects.filter(email__istartswith=f"{value}@").order_by("id").first()
        if user is None:
            raise CommandError(
                f"Utente '{value}' non trovato (provato per email, aliasusername, prefisso UPN)."
            )
        return user

    def _simulate_role(self, value: str) -> UtenteLegacy:
        if value.isdigit():
            ruolo = Ruolo.objects.filter(id=int(value)).first()
        else:
            ruolo = Ruolo.objects.filter(nome__iexact=value).first()
        if ruolo is None:
            raise CommandError(f"Ruolo '{value}' non trovato.")
        # Utente legacy non persistito: serve solo a portare ruolo_id nel resolver.
        return UtenteLegacy(
            id=-1,
            nome=f"[simulazione ruolo {ruolo.nome}]",
            email="",
            password="",
            ruolo=ruolo.nome,
            attivo=True,
            deve_cambiare_password=False,
            ruolo_id=ruolo.id,
        )

    # -------------------------------------------------------------------- path

    def _resolve_path(self, opts) -> str:
        path = (opts.get("path") or "").strip()
        if path:
            return path
        route = (opts.get("route") or "").strip()
        try:
            return reverse(route)
        except NoReverseMatch as exc:
            raise CommandError(f"Route '{route}' non risolvibile: {exc}") from exc

    # ------------------------------------------------------------------ render

    def _render_text(self, diag: dict, legacy_user: UtenteLegacy) -> None:
        allowed = bool(diag.get("allowed", False))
        source = str(diag.get("decision_source") or "")
        canonical = diag.get("canonical") or {}

        self.stdout.write(self.style.MIGRATE_HEADING("ACL diagnose"))
        self.stdout.write(f"Utente legacy   : {legacy_user.nome or legacy_user.email or legacy_user.id} "
                          f"(id={legacy_user.id}, ruolo='{legacy_user.ruolo or ''}', ruolo_id={legacy_user.ruolo_id})")
        self.stdout.write(f"Path            : {diag.get('path_normalized') or diag.get('path_input')}")
        self.stdout.write(f"Route name      : {diag.get('route_name') or '(nessuna)'}")
        verdict = self.style.SUCCESS("CONSENTITO") if allowed else self.style.ERROR("NEGATO")
        self.stdout.write(f"Esito           : {verdict}")
        self.stdout.write(f"Sistema         : {self._source_label(source)}")
        self.stdout.write(f"Motivo          : {diag.get('reason') or ''}")

        binding = canonical.get("binding") or {}
        if canonical.get("binding_found"):
            self.stdout.write("")
            self.stdout.write("Binding canonico:")
            self.stdout.write(f"  permission_code : {binding.get('permission_code')}")
            role_grant = canonical.get("role_grant") or {}
            user_override = canonical.get("user_override") or {}
            self.stdout.write(f"  grant ruolo     : {self._grant_label(role_grant)}")
            self.stdout.write(f"  override utente : {self._grant_label(user_override)}")

        self.stdout.write("")
        self.stdout.write("Trace:")
        for step in diag.get("trace") or []:
            self.stdout.write(f"  - {step.get('step')}: {step.get('result')} {step.get('detail') or ''}".rstrip())

        hint = self._action_hint(diag)
        if hint:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Cosa fare:"))
            for line in hint:
                self.stdout.write(f"  {line}")

    @staticmethod
    def _source_label(source: str) -> str:
        return {
            "superuser_bypass": "bypass superuser Django",
            "legacy_admin_bypass": "bypass admin legacy",
            "canonical": "ACL canonico (v2)",
            "canonical_permission_inactive": "ACL canonico (permission disattiva)",
            "legacy_fallback": "fallback legacy (tabella permessi)",
            "deny_missing_legacy_user": "negato: nessun utente legacy",
            "deny_missing_role": "negato: utente senza ruolo_id",
        }.get(source, source or "(sconosciuto)")

    @staticmethod
    def _grant_label(grant: dict) -> str:
        if not grant or grant.get("exists") is False:
            return "assente"
        return "abilitato" if grant.get("enabled") else "presente ma NON abilitato"

    @staticmethod
    def _action_hint(diag: dict) -> list[str]:
        if bool(diag.get("allowed", False)):
            return []
        source = str(diag.get("decision_source") or "")
        canonical = diag.get("canonical") or {}
        binding = canonical.get("binding") or {}
        perm = binding.get("permission_code") or ""

        if source == "deny_missing_role":
            return ["L'utente legacy non ha ruolo_id: assegnare un ruolo prima dei permessi."]
        if source == "deny_missing_legacy_user":
            return ["Nessun utente legacy collegato all'account Django: verificare il binding profilo/legacy."]
        if canonical.get("binding_found"):
            return [
                f"La route usa l'ACL CANONICO sul permesso '{perm}'.",
                "I permessi della tabella legacy qui sono IGNORATI.",
                f"Abilitare il grant su '{perm}' per il ruolo in /admin-portale/acl-canonico/",
                "(oppure un override utente canonico per il singolo utente).",
            ]
        if source == "legacy_fallback":
            return [
                "La route NON ha binding canonico: decide il fallback LEGACY.",
                "Assegnare il permesso al ruolo nella pagina /admin-portale/permessi/.",
            ]
        return []
