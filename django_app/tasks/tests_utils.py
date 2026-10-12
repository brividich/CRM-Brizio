"""Helper condivisi dai test del modulo tasks."""
from __future__ import annotations


from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso
from core.models import Profile, UserOnboarding

from .models import (
    Project,
)

User = get_user_model()


# I ruoli del team sono M2M: i test continuano a scrivere il caso comune
# "una persona per ruolo" con la vecchia forma a keyword singola.
_TEAM_KWARGS = {
    "project_manager": "project_managers",
    "capo_commessa": "capi_commessa",
    "programmer": "programmers",
    "caporeparto": "caporeparti",
}


def make_project(**kwargs) -> Project:
    """Crea un Project accettando anche i referenti singoli del team."""
    team: dict[str, object] = {}
    for kwarg, field in _TEAM_KWARGS.items():
        if kwarg in kwargs:
            team[field] = kwargs.pop(kwarg)
    project = Project.objects.create(**kwargs)
    for field, user in team.items():
        if user is not None:
            getattr(project, field).add(user)
    return project


TASK_ACTIONS = ("tasks_view", "tasks_create", "tasks_edit", "tasks_comment", "tasks_admin")


def _ensure_legacy_acl_tables() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ruoli (
                    id INTEGER PRIMARY KEY,
                    nome VARCHAR(100) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS utenti (
                    id INTEGER PRIMARY KEY,
                    nome VARCHAR(200) NOT NULL,
                    email VARCHAR(200) NULL,
                    password VARCHAR(500) NOT NULL,
                    ruolo VARCHAR(100) NULL,
                    attivo INTEGER NOT NULL DEFAULT 1,
                    deve_cambiare_password INTEGER NOT NULL DEFAULT 0,
                    ruolo_id INTEGER NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS permessi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    modulo VARCHAR(100) NOT NULL,
                    azione VARCHAR(100) NOT NULL,
                    ruolo_id INTEGER NOT NULL,
                    consentito INTEGER NULL,
                    can_view INTEGER NULL,
                    can_edit INTEGER NULL,
                    can_delete INTEGER NULL,
                    can_approve INTEGER NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('ruoli', 'U') IS NULL
                CREATE TABLE ruoli (
                    id INT NOT NULL PRIMARY KEY,
                    nome NVARCHAR(100) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                IF OBJECT_ID('utenti', 'U') IS NULL
                CREATE TABLE utenti (
                    id INT NOT NULL PRIMARY KEY,
                    nome NVARCHAR(200) NOT NULL,
                    email NVARCHAR(200) NULL,
                    password NVARCHAR(500) NOT NULL,
                    ruolo NVARCHAR(100) NULL,
                    attivo BIT NOT NULL DEFAULT 1,
                    deve_cambiare_password BIT NOT NULL DEFAULT 0,
                    ruolo_id INT NULL
                )
                """
            )
            cursor.execute(
                """
                IF OBJECT_ID('permessi', 'U') IS NULL
                CREATE TABLE permessi (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    modulo NVARCHAR(100) NOT NULL,
                    azione NVARCHAR(100) NOT NULL,
                    ruolo_id INT NOT NULL,
                    consentito INT NULL,
                    can_view INT NULL,
                    can_edit INT NULL,
                    can_delete INT NULL,
                    can_approve INT NULL
                )
                """
            )


def _clear_legacy_acl_tables() -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM permessi")
        cursor.execute("DELETE FROM utenti")
        cursor.execute("DELETE FROM ruoli")


def _legacy_table_has_identity(table_name: str) -> bool:
    if connection.vendor == "sqlite":
        return False
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT COLUMNPROPERTY(OBJECT_ID('{table_name}'),'id','IsIdentity')"
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def _legacy_upsert_by_id(table_name: str, record_id: int, values: dict[str, object]) -> None:
    assignments = ", ".join(f"{column} = %s" for column in values)
    insert_columns = ["id", *values.keys()]
    insert_placeholders = ", ".join(["%s"] * len(insert_columns))
    update_params = [*values.values(), record_id]
    insert_params = [record_id, *values.values()]

    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table_name} SET {assignments} WHERE id = %s", update_params)
        if cursor.rowcount and cursor.rowcount > 0:
            return

        if _legacy_table_has_identity(table_name):
            cursor.execute(f"SET IDENTITY_INSERT {table_name} ON")
            try:
                cursor.execute(
                    f"INSERT INTO {table_name} ({', '.join(insert_columns)}) VALUES ({insert_placeholders})",
                    insert_params,
                )
            finally:
                cursor.execute(f"SET IDENTITY_INSERT {table_name} OFF")
            return

        cursor.execute(
            f"INSERT INTO {table_name} ({', '.join(insert_columns)}) VALUES ({insert_placeholders})",
            insert_params,
        )


def _ensure_assenze_table() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS assenze (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    copia_nome VARCHAR(200) NULL,
                    email_esterna VARCHAR(200) NULL,
                    data_inizio DATETIME NULL,
                    data_fine DATETIME NULL,
                    tipo_assenza VARCHAR(100) NULL,
                    moderation_status INTEGER NULL,
                    consenso VARCHAR(100) NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('assenze', 'U') IS NULL
                CREATE TABLE assenze (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    copia_nome NVARCHAR(200) NULL,
                    email_esterna NVARCHAR(200) NULL,
                    data_inizio DATETIME NULL,
                    data_fine DATETIME NULL,
                    tipo_assenza NVARCHAR(100) NULL,
                    moderation_status INT NULL,
                    consenso NVARCHAR(100) NULL
                )
                """
            )


def _clear_assenze_table() -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM assenze")


def _ensure_role(role_id: int, name: str) -> None:
    _legacy_upsert_by_id("ruoli", role_id, {"nome": name})


def _grant_role_actions(role_id: int, actions: list[str]) -> None:
    for action in actions:
        Permesso.objects.update_or_create(
            ruolo_id=role_id,
            modulo="tasks",
            azione=action,
            defaults={
                "can_view": 1,
                "consentito": 1,
                "can_edit": 1,
                "can_delete": 1,
                "can_approve": 1,
            },
        )


def _create_user_with_legacy(*, username: str, legacy_user_id: int, role_id: int, role_name: str):
    user = User.objects.create_user(username=username, password="pass12345")
    UserOnboarding.objects.create(user=user, completed=True, completed_at=timezone.now())
    Profile.objects.create(
        user=user,
        legacy_user_id=legacy_user_id,
        legacy_ruolo_id=role_id,
        legacy_ruolo=role_name,
    )
    _legacy_upsert_by_id(
        "utenti",
        legacy_user_id,
        {
            "nome": username,
            "email": f"{username}@example.local",
            "password": "x",
            "ruolo": role_name,
            "attivo": True,
            "deve_cambiare_password": False,
            "ruolo_id": role_id,
        },
    )
    return user


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TasksBaseTestCase(TestCase):
    def setUp(self):
        super().setUp()
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()

    def _refresh_acl_cache(self):
        cache.clear()
        bump_legacy_cache_version()
