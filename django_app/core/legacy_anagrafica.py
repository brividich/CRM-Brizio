from __future__ import annotations

from django.db import connections, transaction

from .legacy_utils import legacy_table_columns


_ANAGRAFICA_REQUIRED_EXTRAS = {
    "mansione": {"sqlite": "TEXT", "default": "NVARCHAR(200) NULL"},
    "email_notifica": {"sqlite": "TEXT", "default": "NVARCHAR(200) NULL"},
    "utente_id": {"sqlite": "INTEGER", "default": "INT NULL"},
    "matricola": {"sqlite": "TEXT", "default": "NVARCHAR(100) NULL"},
    "ruolo": {"sqlite": "TEXT", "default": "NVARCHAR(200) NULL"},
    "attivo": {"sqlite": "INTEGER", "default": "BIT NULL"},
}


def normalize_legacy_alias(raw: str) -> str:
    txt = (raw or "").strip().lower()
    if not txt:
        return ""
    if "\\" in txt:
        txt = txt.split("\\")[-1]
    if "@" in txt:
        txt = txt.split("@", 1)[0]
    return txt.strip()


def split_display_name(raw: str) -> tuple[str, str]:
    parts = [chunk for chunk in str(raw or "").strip().split() if chunk]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _row_text(row: dict, field_name: str) -> str:
    return str(row.get(field_name) or "").strip()


def _normalized_key(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _is_all_caps_text(value: str) -> bool:
    text = "".join(ch for ch in str(value or "") if ch.isalpha())
    return bool(text) and text == text.upper()


def _anagrafica_row_identity(row: dict) -> str:
    full_name = f"{_row_text(row, 'nome')} {_row_text(row, 'cognome')}".strip()
    key = _normalized_key(full_name)
    if key:
        return key
    return _normalized_key(_row_text(row, "aliasusername"))


def _anagrafica_row_score(row: dict) -> tuple[int, int, int, int, int, int]:
    nome = _row_text(row, "nome")
    cognome = _row_text(row, "cognome")
    return (
        1 if row.get("utente_id") else 0,
        1 if nome and not _is_all_caps_text(nome) else 0,
        1 if cognome and not _is_all_caps_text(cognome) else 0,
        1 if _row_text(row, "aliasusername") else 0,
        1 if row.get("attivo") not in {None, 0, False, "0"} else 0,
        int(row.get("id") or 0),
    )


def merge_duplicate_anagrafica_rows(rows: list[dict]) -> list[dict]:
    merged_by_key: dict[str, dict] = {}
    ordered: list[dict] = []
    merge_fields = ["matricola", "reparto", "mansione", "ruolo", "email_notifica", "email", "aliasusername", "attivo"]

    for row in rows:
        key = _anagrafica_row_identity(row)
        if not key:
            ordered.append(dict(row))
            continue

        current = merged_by_key.get(key)
        if current is None:
            clone = dict(row)
            clone["_merged_ids"] = [int(row.get("id") or 0)]
            merged_by_key[key] = clone
            ordered.append(clone)
            continue

        preferred = current
        alternate = row
        if _anagrafica_row_score(row) > _anagrafica_row_score(current):
            preferred = dict(row)
            preferred["_merged_ids"] = list(current.get("_merged_ids") or [])
            alternate = current
            merged_by_key[key] = preferred
            ordered[ordered.index(current)] = preferred

        merged_ids = {int(value) for value in list(preferred.get("_merged_ids") or []) if int(value or 0) > 0}
        merged_ids.add(int(alternate.get("id") or 0))
        preferred["_merged_ids"] = sorted(merged_ids)

        for field_name in merge_fields:
            if _row_text(preferred, field_name):
                continue
            value = alternate.get(field_name)
            if value not in {None, ""}:
                preferred[field_name] = value

    return ordered


def ensure_anagrafica_schema() -> set[str]:
    cols = set(legacy_table_columns("anagrafica_dipendenti"))
    if not cols:
        return set()

    vendor = connections["default"].vendor
    missing = [name for name in _ANAGRAFICA_REQUIRED_EXTRAS if name not in cols]
    if not missing:
        return cols

    for col_name in missing:
        spec = _ANAGRAFICA_REQUIRED_EXTRAS[col_name]
        col_type = spec["sqlite"] if vendor == "sqlite" else spec["default"]
        with connections["default"].cursor() as cur:
            if vendor == "sqlite":
                cur.execute(f"ALTER TABLE anagrafica_dipendenti ADD COLUMN {col_name} {col_type}")
            else:
                cur.execute(f"ALTER TABLE anagrafica_dipendenti ADD {col_name} {col_type}")

    cache_clear = getattr(legacy_table_columns, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()
    return set(legacy_table_columns("anagrafica_dipendenti"))


def fetch_anagrafica_rows(*, ids: list[int] | None = None, deduplicate: bool = False) -> list[dict]:
    cols = ensure_anagrafica_schema()
    if not cols:
        return []

    select_cols = [
        col
        for col in [
            "id",
            "aliasusername",
            "nome",
            "cognome",
            "mansione",
            "reparto",
            "ruolo",
            "matricola",
            "attivo",
            "email",
            "email_notifica",
            "utente_id",
        ]
        if col in cols
    ]
    if not select_cols:
        return []

    sql = f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti"
    params: list[object] = []
    if ids:
        safe_ids = [int(value) for value in ids if int(value or 0) > 0]
        if not safe_ids:
            return []
        sql += " WHERE id IN (" + ", ".join(["%s"] * len(safe_ids)) + ")"
        params.extend(safe_ids)

    with connections["default"].cursor() as cur:
        cur.execute(sql, params)
        headers = [str(col[0]).lower() for col in cur.description]
        rows = [dict(zip(headers, row)) for row in cur.fetchall()]
    if deduplicate:
        return merge_duplicate_anagrafica_rows(rows)
    return rows


def count_anagrafica_statuses(*, deduplicate: bool = True) -> dict[str, int]:
    if deduplicate:
        rows = fetch_anagrafica_rows(deduplicate=True)
        return {
            "active": sum(1 for row in rows if row.get("attivo") not in {None, 0, False, "0"}),
            "inactive": sum(1 for row in rows if row.get("attivo") in {0, False, "0"}),
        }

    cols = ensure_anagrafica_schema()
    if not cols or "attivo" not in cols:
        total = len(fetch_anagrafica_rows())
        return {"active": total, "inactive": 0}

    with connections["default"].cursor() as cur:
        cur.execute(
            """
            SELECT
                SUM(CASE WHEN COALESCE(attivo, 1) = 1 THEN 1 ELSE 0 END) AS active_count,
                SUM(CASE WHEN COALESCE(attivo, 1) = 0 THEN 1 ELSE 0 END) AS inactive_count
            FROM anagrafica_dipendenti
            """
        )
        row = cur.fetchone() or (0, 0)
    return {
        "active": int(row[0] or 0),
        "inactive": int(row[1] or 0),
    }


def cleanup_duplicate_anagrafica_rows() -> dict[str, int]:
    rows = fetch_anagrafica_rows(deduplicate=False)
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        key = _anagrafica_row_identity(row)
        if not key:
            continue
        grouped.setdefault(key, []).append(row)

    summary = {
        "groups": 0,
        "rows_deleted": 0,
        "rows_updated": 0,
        "timbri_operatori_merged": 0,
        "timbri_records_moved": 0,
    }
    merge_fields = ["matricola", "reparto", "mansione", "ruolo", "email_notifica", "email", "aliasusername", "attivo"]

    with transaction.atomic():
        for duplicate_rows in grouped.values():
            if len(duplicate_rows) < 2:
                continue

            summary["groups"] += 1
            preferred = sorted(duplicate_rows, key=_anagrafica_row_score, reverse=True)[0]
            duplicate_ids = [int(row.get("id") or 0) for row in duplicate_rows if int(row.get("id") or 0) != int(preferred.get("id") or 0)]
            if not duplicate_ids:
                continue

            updates: dict[str, object] = {}
            for field_name in merge_fields:
                if _row_text(preferred, field_name):
                    continue
                for candidate in duplicate_rows:
                    value = candidate.get(field_name)
                    if value not in {None, ""}:
                        updates[field_name] = value
                        preferred[field_name] = value
                        break

            if updates:
                set_sql = ", ".join(f"{field_name} = %s" for field_name in updates)
                with connections["default"].cursor() as cur:
                    cur.execute(
                        f"UPDATE anagrafica_dipendenti SET {set_sql} WHERE id = %s",
                        [*updates.values(), int(preferred["id"])],
                    )
                summary["rows_updated"] += 1

            try:
                from timbri.models import OperatoreTimbri, RegistroTimbro

                target_operatore = OperatoreTimbri.objects.filter(legacy_anagrafica_id=int(preferred["id"])).first()
                duplicate_operatori = list(OperatoreTimbri.objects.filter(legacy_anagrafica_id__in=duplicate_ids).order_by("id"))
                for operatore in duplicate_operatori:
                    if target_operatore is None:
                        operatore.legacy_anagrafica_id = int(preferred["id"])
                        operatore.save(update_fields=["legacy_anagrafica_id", "updated_at"])
                        target_operatore = operatore
                        continue
                    moved = RegistroTimbro.objects.filter(operatore=operatore).update(operatore=target_operatore)
                    summary["timbri_records_moved"] += int(moved)
                    operatore.delete()
                    summary["timbri_operatori_merged"] += 1
            except Exception:
                pass

            with connections["default"].cursor() as cur:
                cur.execute(
                    "DELETE FROM anagrafica_dipendenti WHERE id IN (" + ", ".join(["%s"] * len(duplicate_ids)) + ")",
                    duplicate_ids,
                )
            summary["rows_deleted"] += len(duplicate_ids)

    return summary


def _find_existing_row(
    *,
    row_id: int | None = None,
    utente_id: int | None = None,
    email: str = "",
    aliasusername: str = "",
    nome: str = "",
    cognome: str = "",
) -> dict | None:
    cols = ensure_anagrafica_schema()
    if not cols:
        return None

    select_cols = [
        col
        for col in [
            "id",
            "aliasusername",
            "nome",
            "cognome",
            "mansione",
            "reparto",
            "ruolo",
            "matricola",
            "attivo",
            "email",
            "email_notifica",
            "utente_id",
        ]
        if col in cols
    ]
    if not select_cols:
        return None

    def query_one(where_sql: str, params: list[object]) -> dict | None:
        with connections["default"].cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(select_cols)} FROM anagrafica_dipendenti WHERE {where_sql}",
                params,
            )
            row = cur.fetchone()
            if not row:
                return None
            headers = [str(col[0]).lower() for col in cur.description]
            return dict(zip(headers, row))

    if row_id and "id" in cols:
        found = query_one("id = %s", [int(row_id)])
        if found:
            return found
    if utente_id and "utente_id" in cols:
        found = query_one("utente_id = %s", [int(utente_id)])
        if found:
            return found
    if email and "email" in cols:
        found = query_one("LOWER(COALESCE(email, '')) = LOWER(%s)", [email.strip()])
        if found:
            return found
    if aliasusername and "aliasusername" in cols:
        found = query_one("LOWER(COALESCE(aliasusername, '')) = LOWER(%s)", [aliasusername.strip()])
        if found:
            return found
    if nome and cognome and {"nome", "cognome"}.issubset(cols):
        with connections["default"].cursor() as cur:
            cur.execute(
                f"""
                SELECT {', '.join(select_cols)}
                FROM anagrafica_dipendenti
                WHERE LOWER(COALESCE(nome, '')) = LOWER(%s)
                  AND LOWER(COALESCE(cognome, '')) = LOWER(%s)
                """,
                [nome.strip(), cognome.strip()],
            )
            rows = cur.fetchall()
            if len(rows) == 1:
                headers = [str(col[0]).lower() for col in cur.description]
                return dict(zip(headers, rows[0]))
    return None


def upsert_anagrafica_dipendente(
    *,
    row_id: int | None = None,
    aliasusername: str = "",
    nome: str = "",
    cognome: str = "",
    reparto: str = "",
    mansione: str = "",
    ruolo: str = "",
    matricola: str = "",
    email: str = "",
    email_notifica: str = "",
    attivo: bool | None = True,
    utente_id: int | None = None,
    detach_account: bool = False,
) -> dict:
    cols = ensure_anagrafica_schema()
    if not cols:
        raise RuntimeError("Tabella anagrafica_dipendenti non disponibile.")

    cleaned = {
        "aliasusername": normalize_legacy_alias(aliasusername or email),
        "nome": str(nome or "").strip(),
        "cognome": str(cognome or "").strip(),
        "reparto": str(reparto or "").strip(),
        "mansione": str(mansione or "").strip(),
        "ruolo": str(ruolo or "").strip(),
        "matricola": str(matricola or "").strip(),
        "email": str(email or "").strip(),
        "email_notifica": str(email_notifica or "").strip(),
    }

    existing = _find_existing_row(
        row_id=row_id,
        utente_id=utente_id,
        email=cleaned["email"],
        aliasusername=cleaned["aliasusername"],
        nome=cleaned["nome"],
        cognome=cleaned["cognome"],
    )

    payload: dict[str, object] = {}
    for field_name, value in cleaned.items():
        if field_name in cols and value:
            payload[field_name] = value
    if "attivo" in cols and attivo is not None:
        payload["attivo"] = 1 if bool(attivo) else 0
    if "utente_id" in cols:
        if detach_account:
            payload["utente_id"] = None
        elif utente_id is not None:
            payload["utente_id"] = int(utente_id)

    if existing:
        updates: dict[str, object] = {}
        for field_name, value in payload.items():
            current = existing.get(field_name)
            if current != value:
                updates[field_name] = value
        if updates:
            set_sql = ", ".join(f"{field_name} = %s" for field_name in updates)
            with connections["default"].cursor() as cur:
                cur.execute(
                    f"UPDATE anagrafica_dipendenti SET {set_sql} WHERE id = %s",
                    [*updates.values(), int(existing["id"])],
                )
        return _find_existing_row(row_id=int(existing["id"])) or existing

    if not cleaned["nome"] and not cleaned["cognome"] and not cleaned["aliasusername"]:
        raise RuntimeError("Dati dipendente insufficienti per creare una nuova anagrafica.")

    insert_payload = payload.copy()
    if "nome" in cols and "nome" not in insert_payload:
        insert_payload["nome"] = cleaned["nome"]
    if "cognome" in cols and "cognome" not in insert_payload:
        insert_payload["cognome"] = cleaned["cognome"]
    if "aliasusername" in cols and "aliasusername" not in insert_payload and cleaned["aliasusername"]:
        insert_payload["aliasusername"] = cleaned["aliasusername"]
    if not insert_payload:
        raise RuntimeError("Nessuna colonna utile disponibile per creare il dipendente.")

    col_names = list(insert_payload.keys())
    placeholders = ", ".join(["%s"] * len(col_names))
    with connections["default"].cursor() as cur:
        cur.execute(
            f"INSERT INTO anagrafica_dipendenti ({', '.join(col_names)}) VALUES ({placeholders})",
            [insert_payload[name] for name in col_names],
        )
        if connections["default"].vendor == "sqlite":
            new_id = int(cur.lastrowid)
        else:
            cur.execute("SELECT TOP 1 id FROM anagrafica_dipendenti ORDER BY id DESC")
            row = cur.fetchone()
            new_id = int(row[0]) if row and row[0] is not None else 0

    found = _find_existing_row(row_id=new_id)
    if not found:
        raise RuntimeError("Dipendente creato ma non riletto dalla tabella anagrafica_dipendenti.")
    return found


def sync_anagrafica_from_legacy_user(legacy_user, *, force_active: bool | None = None) -> dict:
    display_name = str(getattr(legacy_user, "nome", "") or "").strip()
    nome, cognome = split_display_name(display_name)
    email = str(getattr(legacy_user, "email", "") or "").strip()
    is_active = bool(getattr(legacy_user, "attivo", False)) if force_active is None else bool(force_active)
    return upsert_anagrafica_dipendente(
        aliasusername=normalize_legacy_alias(email or display_name),
        nome=nome or display_name,
        cognome=cognome,
        email=email,
        attivo=is_active,
        utente_id=int(getattr(legacy_user, "id", 0) or 0) if is_active else None,
        detach_account=not is_active,
    )
