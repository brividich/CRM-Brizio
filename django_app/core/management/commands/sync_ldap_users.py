from __future__ import annotations

import argparse
import logging
import socket
from collections.abc import Iterable

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from core.legacy_models import Ruolo, UtenteLegacy
from core.legacy_utils import legacy_table_columns, sync_django_user_from_legacy

logger = logging.getLogger(__name__)


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    txt = str(value).strip()
    if not txt:
        return []
    return [txt]


def _cn_from_dn(dn: str) -> str:
    for part in str(dn or "").split(","):
        chunk = str(part or "").strip()
        if chunk.upper().startswith("CN="):
            return chunk[3:].strip()
    return ""


def _entry_first(entry_dict: dict, key: str, default: str = "") -> str:
    raw = entry_dict.get(key)
    values = _as_list(raw)
    if not values:
        return default
    return values[0]


def _normalized_allowlist(raw_values: Iterable[str]) -> set[str]:
    return {str(v).strip().casefold() for v in raw_values if str(v).strip()}


def _domain_root_dn(*values: str) -> str:
    for value in values:
        text = str(value or "").strip().strip("@")
        if not text or "." not in text:
            continue
        parts = [part.strip() for part in text.split(".") if part.strip()]
        if len(parts) >= 2:
            return ",".join(f"DC={part.upper()}" for part in parts)
    return ""


def _format_ldap_search_error(result, *, search_base: str, domain: str, upn_suffix: str) -> str:
    if isinstance(result, dict):
        description = str(result.get("description") or "").strip()
        message = str(result.get("message") or "").strip()
    else:
        description = ""
        message = str(result or "").strip()

    if description == "noSuchObject":
        suggestion = _domain_root_dn(upn_suffix, domain)
        detail = f" Dettaglio AD: {message}" if message else ""
        if suggestion and suggestion.casefold() != search_base.casefold():
            return (
                "Ricerca LDAP fallita: Base DN non trovato "
                f"({search_base}). Imposta LDAP_BASE_DN su un DN esistente, "
                f"ad esempio {suggestion}, oppure correggi il percorso OU/container.{detail}"
            )
        return (
            "Ricerca LDAP fallita: Base DN non trovato "
            f"({search_base}). Correggi LDAP_BASE_DN con un DN esistente in Active Directory.{detail}"
        )
    return f"Ricerca LDAP fallita: {result}"


class Command(BaseCommand):
    help = "Importa utenti da LDAP/AD su UtenteLegacy + auth_user/Profile e sincronizza gruppi Django (membership multipla)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Esegue import in transazione e rollback finale.")
        parser.add_argument("--limit", type=int, default=0, help="Numero massimo utenti da processare (0 = tutti).")
        parser.add_argument(
            "--group-allowlist",
            default="",
            help="Lista gruppi consentiti separati da virgola; override di LDAP_GROUP_ALLOWLIST.",
        )
        parser.add_argument(
            "--replace-allowlist-memberships",
            action="store_true",
            help="Se attivo, aggiorna in modo autoritativo i gruppi dell'allowlist (rimuove quelli non presenti su LDAP).",
        )
        parser.add_argument("--search-base", default="", help="Override LDAP_BASE_DN.")
        parser.add_argument("--user-filter", default="", help="Override LDAP_USER_FILTER.")
        parser.add_argument(
            "--ldap-enabled",
            dest="ldap_enabled",
            action="store_true",
            default=None,
            help=argparse.SUPPRESS,
        )
        parser.add_argument("--server", dest="server", default="", help=argparse.SUPPRESS)
        parser.add_argument("--domain", dest="domain", default="", help=argparse.SUPPRESS)
        parser.add_argument("--upn-suffix", dest="upn_suffix", default=None, help=argparse.SUPPRESS)
        parser.add_argument("--timeout", dest="timeout", type=int, default=None, help=argparse.SUPPRESS)
        parser.add_argument("--service-user", dest="service_user", default="", help=argparse.SUPPRESS)
        parser.add_argument("--service-password", dest="service_password", default="", help=argparse.SUPPRESS)
        parser.add_argument("--page-size", dest="page_size", type=int, default=None, help=argparse.SUPPRESS)

    def handle(self, *args, **options):
        ldap_enabled = options.get("ldap_enabled")
        if ldap_enabled is None:
            ldap_enabled = bool(getattr(settings, "LDAP_ENABLED", False))
        if not bool(ldap_enabled):
            raise CommandError("LDAP non abilitato (LDAP_ENABLED=0).")

        server_url = str(options.get("server") or getattr(settings, "LDAP_SERVER", "") or "").strip()
        domain = str(options.get("domain") or getattr(settings, "LDAP_DOMAIN", "") or "").strip()
        upn_suffix_option = options.get("upn_suffix")
        upn_suffix = str(
            getattr(settings, "LDAP_UPN_SUFFIX", "") if upn_suffix_option is None else upn_suffix_option
        ).strip().lstrip("@")
        timeout = int(options.get("timeout") or getattr(settings, "LDAP_TIMEOUT", 5) or 5)
        service_user = str(options.get("service_user") or getattr(settings, "LDAP_SERVICE_USER", "") or "").strip()
        service_password = str(
            options.get("service_password") or getattr(settings, "LDAP_SERVICE_PASSWORD", "") or ""
        ).strip()
        search_base = str(options.get("search_base") or getattr(settings, "LDAP_BASE_DN", "") or "").strip()
        user_filter = str(options.get("user_filter") or getattr(settings, "LDAP_USER_FILTER", "") or "").strip()
        page_size = max(
            100,
            min(int(options.get("page_size") or getattr(settings, "LDAP_SYNC_PAGE_SIZE", 500) or 500), 2000),
        )
        dry_run = bool(options.get("dry_run"))
        limit = max(0, int(options.get("limit") or 0))
        replace_allowlist = bool(options.get("replace_allowlist_memberships"))

        if not server_url:
            raise CommandError("LDAP_SERVER non configurato.")
        if not service_user or not service_password:
            raise CommandError("LDAP_SERVICE_USER / LDAP_SERVICE_PASSWORD non configurati.")
        if not search_base:
            raise CommandError("LDAP_BASE_DN non configurato.")
        if not user_filter:
            raise CommandError("LDAP_USER_FILTER non configurato.")

        try:
            from ldap3 import NONE, NTLM, SIMPLE, SUBTREE, Connection, Server
            from ldap3.core.exceptions import LDAPException, LDAPSocketOpenError
        except Exception as exc:
            raise CommandError(f"ldap3 non disponibile: {exc}") from exc

        allowlist_raw = str(options.get("group_allowlist") or "").strip()
        if allowlist_raw:
            allowlist = _normalized_allowlist(v for v in allowlist_raw.split(","))
        else:
            allowlist = _normalized_allowlist(getattr(settings, "LDAP_GROUP_ALLOWLIST", []) or [])

        def _bind_attempts() -> list[tuple[str, object]]:
            if "\\" in service_user:
                return [(service_user, NTLM)]
            if "@" in service_user:
                return [(service_user, SIMPLE)]

            attempts: list[tuple[str, object]] = []
            if upn_suffix:
                attempts.append((f"{service_user}@{upn_suffix}", SIMPLE))
            attempts.append((service_user, SIMPLE))
            if domain:
                attempts.append((f"{domain}\\{service_user}", NTLM))
            return attempts

        try:
            server = Server(server_url, connect_timeout=timeout, get_info=NONE)
            conn = None
            last_result = None
            for bind_user, authentication in _bind_attempts():
                candidate = Connection(
                    server,
                    user=bind_user,
                    password=service_password,
                    authentication=authentication,
                    auto_bind=False,
                    auto_referrals=False,
                    raise_exceptions=False,
                )
                ok = candidate.bind()
                if ok:
                    conn = candidate
                    break
                last_result = candidate.result
                try:
                    candidate.unbind()
                except Exception:
                    pass
            if conn is None:
                raise CommandError(f"Bind LDAP fallito: {last_result}")
        except (LDAPSocketOpenError, LDAPException, socket.error, OSError) as exc:
            raise CommandError(f"Connessione LDAP fallita: {exc}") from exc

        attrs = ["displayName", "givenName", "sn", "mail", "userPrincipalName", "sAMAccountName", "memberOf"]
        try:
            search_ok = conn.search(
                search_base=search_base,
                search_filter=user_filter,
                search_scope=SUBTREE,
                attributes=attrs,
                paged_size=page_size,
            )
        except (LDAPSocketOpenError, LDAPException, socket.error, OSError) as exc:
            conn.unbind()
            raise CommandError(f"Ricerca LDAP fallita: {exc}") from exc
        if not search_ok:
            conn.unbind()
            raise CommandError(
                _format_ldap_search_error(
                    conn.result,
                    search_base=search_base,
                    domain=domain,
                    upn_suffix=upn_suffix,
                )
            )

        role_utente = Ruolo.objects.filter(nome__iexact="utente").first()
        ruolo_id = int(role_utente.id) if role_utente else None
        user_cols = legacy_table_columns("utenti")
        has_json_ruoli = "ruoli" in user_cols

        totals = {
            "scanned": 0,
            "imported": 0,
            "legacy_created": 0,
            "legacy_updated": 0,
            "group_links_added": 0,
            "group_links_removed": 0,
            "skipped": 0,
        }

        with transaction.atomic():
            for entry in conn.entries:
                if limit and totals["scanned"] >= limit:
                    break
                totals["scanned"] += 1

                data = entry.entry_attributes_as_dict if hasattr(entry, "entry_attributes_as_dict") else {}
                upn = _entry_first(data, "userPrincipalName").strip().lower()
                mail = _entry_first(data, "mail").strip().lower()
                sam = _entry_first(data, "sAMAccountName").strip().lower()
                given = _entry_first(data, "givenName").strip()
                sn = _entry_first(data, "sn").strip()
                display = _entry_first(data, "displayName").strip()

                if not upn and sam:
                    suffix = str(getattr(settings, "LDAP_UPN_SUFFIX", "") or "").strip().lstrip("@")
                    if suffix:
                        upn = f"{sam}@{suffix}".lower()
                ident_email = upn or mail
                full_name = display or " ".join([p for p in [given, sn] if p]).strip() or sam or ident_email

                if not ident_email:
                    totals["skipped"] += 1
                    continue

                member_dns = _as_list(data.get("memberOf"))
                ldap_group_names = []
                for member_dn in member_dns:
                    group_name = _cn_from_dn(member_dn)
                    if not group_name:
                        continue
                    if allowlist and group_name.casefold() not in allowlist:
                        continue
                    ldap_group_names.append(group_name)
                ldap_group_names = sorted(set(ldap_group_names), key=str.casefold)

                legacy_user = UtenteLegacy.objects.filter(email__iexact=ident_email).first()
                created_legacy = False
                if legacy_user is None:
                    create_kwargs = {
                        "nome": full_name,
                        "email": ident_email,
                        "password": "*AD_MANAGED*",
                        "ruolo": "utente",
                        "attivo": True,
                        "deve_cambiare_password": False,
                        "ruolo_id": ruolo_id,
                    }
                    if has_json_ruoli:
                        create_kwargs["ruoli"] = '["utente"]'
                    legacy_user = UtenteLegacy.objects.create(**create_kwargs)
                    totals["legacy_created"] += 1
                    created_legacy = True
                else:
                    changed_fields = []
                    if (legacy_user.nome or "").strip() != full_name:
                        legacy_user.nome = full_name
                        changed_fields.append("nome")
                    if (legacy_user.email or "").strip().lower() != ident_email:
                        legacy_user.email = ident_email
                        changed_fields.append("email")
                    if (legacy_user.password or "").strip() != "*AD_MANAGED*":
                        legacy_user.password = "*AD_MANAGED*"
                        changed_fields.append("password")
                    if not bool(legacy_user.attivo):
                        legacy_user.attivo = True
                        changed_fields.append("attivo")
                    if changed_fields:
                        legacy_user.save(update_fields=changed_fields)
                        totals["legacy_updated"] += 1

                try:
                    django_user = sync_django_user_from_legacy(legacy_user)
                except DatabaseError as exc:
                    logger.warning("LDAP sync skip legacy_user=%s error=%s", legacy_user.id, exc)
                    totals["skipped"] += 1
                    continue

                added_count = 0
                for group_name in ldap_group_names:
                    group_obj, _created = Group.objects.get_or_create(name=group_name)
                    if not django_user.groups.filter(id=group_obj.id).exists():
                        django_user.groups.add(group_obj)
                        added_count += 1
                totals["group_links_added"] += added_count

                removed_count = 0
                if replace_allowlist and allowlist:
                    current_names = set(django_user.groups.values_list("name", flat=True))
                    target_names = set(ldap_group_names)
                    remove_names = [n for n in current_names if n.casefold() in allowlist and n not in target_names]
                    if remove_names:
                        remove_groups = list(Group.objects.filter(name__in=remove_names))
                        django_user.groups.remove(*remove_groups)
                        removed_count = len(remove_groups)
                totals["group_links_removed"] += removed_count

                totals["imported"] += 1
                if created_legacy:
                    self.stdout.write(self.style.SUCCESS(f"[OK] creato {ident_email} groups={len(ldap_group_names)}"))
                else:
                    self.stdout.write(f"[OK] aggiornato {ident_email} groups={len(ldap_group_names)}")

            if dry_run:
                transaction.set_rollback(True)

        conn.unbind()
        summary = (
            f"LDAP sync completata scanned={totals['scanned']} imported={totals['imported']} "
            f"legacy_created={totals['legacy_created']} legacy_updated={totals['legacy_updated']} "
            f"group_added={totals['group_links_added']} group_removed={totals['group_links_removed']} "
            f"skipped={totals['skipped']} dry_run={int(dry_run)}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
