from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from werkzeug.security import generate_password_hash

from core.legacy_models import Ruolo, UtenteLegacy
from core.legacy_utils import legacy_table_columns


def _normalize_alias(raw: str) -> str:
    txt = (raw or "").strip().lower()
    if not txt:
        return ""
    if "\\" in txt:
        txt = txt.split("\\")[-1]
    if "@" in txt:
        txt = txt.split("@", 1)[0]
    return txt.strip()


def _pretty_text(raw: str) -> str:
    txt = " ".join((raw or "").strip().split())
    if not txt:
        return ""
    return txt.lower().title()


def _split_fullname(fullname: str) -> tuple[str, str]:
    """Restituisce (cognome, nome). Ultimo token = nome, tutto il resto = cognome.
    Es: 'DE LUCIA MICHELE' -> ('De Lucia', 'Michele')
        'GIRARDI MARIA TERESA' -> ('Girardi Maria', 'Teresa')
    """
    parts = " ".join((fullname or "").strip().split()).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def _row_value(row: dict[str, str], key: str) -> str:
    target = key.strip().casefold()
    for k, v in row.items():
        if str(k).strip().casefold() == target:
            return str(v or "").strip()
    return ""


class Command(BaseCommand):
    help = (
        "Importa/aggiorna anagrafica_dipendenti da CSV. "
        "Mappa USERNAME -> aliasusername (supporta alias, dominio\\alias, alias@dominio)."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Percorso CSV dipendenti.")
        parser.add_argument("--dry-run", action="store_true", help="Esegue rollback finale.")
        parser.add_argument("--delimiter", default=",", help="Separatore CSV (default: ',').")
        parser.add_argument("--email-domain", default="", help="Dominio per login_id da alias (es. example.local).")
        parser.add_argument(
            "--overwrite-email",
            action="store_true",
            help="Sovrascrive email (login_id) esistente in anagrafica_dipendenti con quella derivata dal CSV.",
        )
        parser.add_argument("--limit", type=int, default=0, help="Numero massimo righe da processare (0=tutte).")
        parser.add_argument(
            "--sync-legacy-users",
            action="store_true",
            help="Allinea anche tabella utenti usando email derivata e popola utente_id. Utile per login offline.",
        )
        parser.add_argument(
            "--default-password",
            default="",
            help="Password iniziale per nuovi utenti legacy (richiesto con --sync-legacy-users senza --ad-managed).",
        )
        parser.add_argument(
            "--ad-managed",
            action="store_true",
            help="Imposta password=*AD_MANAGED* (login via Active Directory). Non richiede --default-password.",
        )
        parser.add_argument(
            "--no-ensure-schema",
            action="store_true",
            help="Non prova ad aggiungere automaticamente le colonne mancanti.",
        )

    def handle(self, *args, **options):
        csv_path = Path(str(options["csv_path"])).expanduser()
        if not csv_path.exists():
            raise CommandError(f"CSV non trovato: {csv_path}")

        if not csv_path.is_file():
            raise CommandError(f"Percorso non valido (non e' un file): {csv_path}")

        delimiter = str(options.get("delimiter") or ",")
        dry_run = bool(options.get("dry_run"))
        limit = max(0, int(options.get("limit") or 0))
        email_domain = str(options.get("email_domain") or "").strip().lstrip("@").lower()
        overwrite_email = bool(options.get("overwrite_email"))
        sync_legacy_users = bool(options.get("sync_legacy_users"))
        default_password = str(options.get("default_password") or "")
        no_ensure_schema = bool(options.get("no_ensure_schema"))

        ad_managed = bool(options.get("ad_managed"))

        if sync_legacy_users and not default_password and not ad_managed:
            raise CommandError(
                "Con --sync-legacy-users devi specificare --default-password oppure --ad-managed."
            )

        table_cols = legacy_table_columns("anagrafica_dipendenti")
        if "id" not in table_cols or "aliasusername" not in table_cols:
            raise CommandError("Tabella anagrafica_dipendenti non compatibile (mancano colonne id/aliasusername).")

        if not no_ensure_schema:
            if self._ensure_extra_columns():
                legacy_table_columns.cache_clear()
                table_cols = legacy_table_columns("anagrafica_dipendenti")

        rows = self._load_csv_rows(csv_path, delimiter)
        if not rows:
            self.stdout.write(self.style.WARNING("CSV vuoto: nessuna riga processata."))
            return

        existing = self._load_existing_by_alias()
        stats = {
            "rows": 0,
            "skipped": 0,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "legacy_created": 0,
            "legacy_updated": 0,
        }

        ruolo_utente = Ruolo.objects.filter(nome__iexact="utente").first() if sync_legacy_users else None
        ruolo_id = int(ruolo_utente.id) if ruolo_utente else None

        with transaction.atomic():
            for row in rows:
                if limit and stats["rows"] >= limit:
                    break
                stats["rows"] += 1

                nominativo = _row_value(row, "Nominativo")
                cognome = _row_value(row, "COGNOME")
                nome = _row_value(row, "NOME")
                username_raw = _row_value(row, "USERNAME")
                mansione = _pretty_text(_row_value(row, "MANSIONE"))
                email_notifica = _row_value(row, "EMAIL_NOTIFICA").lower()

                alias = _normalize_alias(username_raw or nominativo)
                if not alias:
                    stats["skipped"] += 1
                    continue

                # Alcuni export hanno NOME/COGNOME valorizzati in modo non separato.
                if cognome and nome and cognome.casefold() == nome.casefold():
                    cg, nm = _split_fullname(nominativo or cognome)
                    cognome, nome = cg or cognome, nm or nome
                elif not cognome or not nome:
                    cg, nm = _split_fullname(nominativo)
                    if not cognome:
                        cognome = cg
                    if not nome:
                        nome = nm

                cognome = _pretty_text(cognome)
                nome = _pretty_text(nome)

                # email = login_id (es. l.bova@example.local)
                email_value = ""
                username_norm = (username_raw or "").strip().lower()
                if "@" in username_norm:
                    email_value = username_norm
                elif email_domain:
                    email_value = f"{alias}@{email_domain}"

                utente_id: int | None = None
                if sync_legacy_users and email_value:
                    legacy_user, created, updated = self._sync_legacy_user(
                        email_value=email_value,
                        nome_display=f"{cognome} {nome}".strip() or alias,
                        ruolo_id=ruolo_id,
                        default_password=default_password,
                        ad_managed=ad_managed,
                    )
                    utente_id = int(legacy_user.id) if legacy_user else None
                    if created:
                        stats["legacy_created"] += 1
                    if updated:
                        stats["legacy_updated"] += 1

                current = existing.get(alias)
                if current:
                    changed = self._update_anagrafica_row(
                        row_id=int(current["id"]),
                        table_cols=table_cols,
                        current=current,
                        alias=alias,
                        nome=nome,
                        cognome=cognome,
                        mansione=mansione,
                        email_value=email_value,
                        email_notifica=email_notifica,
                        overwrite_email=overwrite_email,
                        utente_id=utente_id,
                    )
                    if changed:
                        stats["updated"] += 1
                        current["aliasusername"] = alias
                        current["nome"] = nome
                        current["cognome"] = cognome
                        current["mansione"] = mansione
                        if email_value and (overwrite_email or not str(current.get("email") or "").strip()):
                            current["email"] = email_value
                        if utente_id:
                            current["utente_id"] = utente_id
                    else:
                        stats["unchanged"] += 1
                else:
                    row_id = self._insert_anagrafica_row(
                        table_cols=table_cols,
                        alias=alias,
                        nome=nome,
                        cognome=cognome,
                        mansione=mansione,
                        email_value=email_value,
                        email_notifica=email_notifica,
                        utente_id=utente_id,
                    )
                    existing[alias] = {
                        "id": row_id,
                        "aliasusername": alias,
                        "nome": nome,
                        "cognome": cognome,
                        "mansione": mansione,
                        "email": email_value,
                        "email_notifica": email_notifica,
                        "utente_id": utente_id,
                    }
                    stats["inserted"] += 1

            if dry_run:
                transaction.set_rollback(True)

        dry_note = " [DRY-RUN]" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                "Import completato%s rows=%s inserted=%s updated=%s unchanged=%s skipped=%s"
                % (
                    dry_note,
                    stats["rows"],
                    stats["inserted"],
                    stats["updated"],
                    stats["unchanged"],
                    stats["skipped"],
                )
            )
        )
        if sync_legacy_users:
            self.stdout.write(
                "Legacy utenti: created=%s updated=%s"
                % (stats["legacy_created"], stats["legacy_updated"])
            )

    def _load_csv_rows(self, csv_path: Path, delimiter: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                rows.append({str(k): str(v or "") for k, v in row.items()})
        return rows

    def _ensure_extra_columns(self) -> bool:
        """Aggiunge colonne mancanti a anagrafica_dipendenti. Restituisce True se sono state aggiunte."""
        cols = legacy_table_columns("anagrafica_dipendenti")
        vendor = connections["default"].vendor
        added = False

        missing = []
        if "mansione" not in cols:
            missing.append(("mansione", "TEXT" if vendor == "sqlite" else "NVARCHAR(200) NULL"))
        if "email_notifica" not in cols:
            missing.append(("email_notifica", "TEXT" if vendor == "sqlite" else "NVARCHAR(200) NULL"))
        if "utente_id" not in cols:
            missing.append(("utente_id", "INTEGER" if vendor == "sqlite" else "INT NULL"))

        for col_name, col_type in missing:
            with connections["default"].cursor() as cur:
                if vendor == "sqlite":
                    cur.execute(f"ALTER TABLE anagrafica_dipendenti ADD COLUMN {col_name} {col_type}")
                else:
                    cur.execute(f"ALTER TABLE anagrafica_dipendenti ADD {col_name} {col_type}")
            self.stdout.write(
                self.style.WARNING(f"Schema aggiornato: aggiunta colonna anagrafica_dipendenti.{col_name}")
            )
            added = True

        return added

    def _load_existing_by_alias(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        cols = legacy_table_columns("anagrafica_dipendenti")
        select_cols = ["id", "aliasusername", "nome", "cognome", "email"]
        for extra in ("mansione", "email_notifica", "utente_id"):
            if extra in cols:
                select_cols.append(extra)
        with connections["default"].cursor() as cur:
            cur.execute(f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti")
            db_cols = [str(c[0]).lower() for c in cur.description]
            for row in cur.fetchall():
                record = dict(zip(db_cols, row))
                alias = _normalize_alias(str(record.get("aliasusername") or ""))
                if not alias:
                    continue
                out[alias] = {k: str(v or "") if k != "utente_id" else (int(v) if v else None) for k, v in record.items()}
        return out

    def _update_anagrafica_row(
        self,
        *,
        row_id: int,
        table_cols: set[str],
        current: dict,
        alias: str,
        nome: str,
        cognome: str,
        mansione: str,
        email_value: str,
        email_notifica: str,
        overwrite_email: bool,
        utente_id: int | None,
    ) -> bool:
        updates: dict[str, object] = {}
        if "aliasusername" in table_cols and (str(current.get("aliasusername") or "").strip().lower() != alias):
            updates["aliasusername"] = alias
        if "nome" in table_cols and nome and str(current.get("nome") or "").strip() != nome:
            updates["nome"] = nome
        if "cognome" in table_cols and cognome and str(current.get("cognome") or "").strip() != cognome:
            updates["cognome"] = cognome
        if "mansione" in table_cols and mansione and str(current.get("mansione") or "").strip() != mansione:
            updates["mansione"] = mansione
        if "email" in table_cols and email_value:
            cur_email = str(current.get("email") or "").strip()
            if overwrite_email or not cur_email:
                if cur_email.lower() != email_value.lower():
                    updates["email"] = email_value
        if "email_notifica" in table_cols and email_notifica:
            cur_notifica = str(current.get("email_notifica") or "").strip().lower()
            if cur_notifica != email_notifica.lower():
                updates["email_notifica"] = email_notifica
        if "utente_id" in table_cols and utente_id and current.get("utente_id") != utente_id:
            updates["utente_id"] = utente_id

        if not updates:
            return False

        set_sql = ", ".join([f"{k} = %s" for k in updates.keys()])
        with connections["default"].cursor() as cur:
            cur.execute(
                f"UPDATE anagrafica_dipendenti SET {set_sql} WHERE id = %s",
                [*updates.values(), row_id],
            )
        return True

    def _insert_anagrafica_row(
        self,
        *,
        table_cols: set[str],
        alias: str,
        nome: str,
        cognome: str,
        mansione: str,
        email_value: str,
        email_notifica: str,
        utente_id: int | None,
    ) -> int:
        payload: dict[str, object] = {}
        if "aliasusername" in table_cols:
            payload["aliasusername"] = alias
        if "nome" in table_cols:
            payload["nome"] = nome
        if "cognome" in table_cols:
            payload["cognome"] = cognome
        if "mansione" in table_cols and mansione:
            payload["mansione"] = mansione
        if "email" in table_cols and email_value:
            payload["email"] = email_value
        if "email_notifica" in table_cols and email_notifica:
            payload["email_notifica"] = email_notifica
        if "utente_id" in table_cols and utente_id:
            payload["utente_id"] = utente_id

        if not payload:
            raise CommandError("Nessuna colonna utile disponibile per INSERT su anagrafica_dipendenti.")

        cols = list(payload.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        sql = f"INSERT INTO anagrafica_dipendenti ({', '.join(cols)}) VALUES ({placeholders})"
        with connections["default"].cursor() as cur:
            cur.execute(sql, [payload[c] for c in cols])
            # Recupera id appena inserito (compatibile SQL Server)
            cur.execute("SELECT TOP 1 id FROM anagrafica_dipendenti ORDER BY id DESC")
            row = cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])
        return 0

    def _sync_legacy_user(
        self,
        *,
        email_value: str,
        nome_display: str,
        ruolo_id: int | None,
        default_password: str,
        ad_managed: bool = False,
    ) -> tuple[UtenteLegacy, bool, bool]:
        """Restituisce (utente, created, updated)."""
        password_value = "*AD_MANAGED*" if ad_managed else generate_password_hash(default_password)
        u = UtenteLegacy.objects.filter(email__iexact=email_value).first()
        if u is None:
            u = UtenteLegacy.objects.create(
                nome=nome_display[:200],
                email=email_value,
                password=password_value,
                ruolo="utente",
                ruolo_id=ruolo_id,
                attivo=True,
                deve_cambiare_password=False,
            )
            return u, True, False

        fields = []
        if (u.nome or "").strip() != nome_display[:200]:
            u.nome = nome_display[:200]
            fields.append("nome")
        if not bool(u.attivo):
            u.attivo = True
            fields.append("attivo")
        if fields:
            u.save(update_fields=fields)
        return u, False, bool(fields)
