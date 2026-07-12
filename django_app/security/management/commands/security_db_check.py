from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "Check the configured Security Center AI database connection and migration status."

    def handle(self, *args, **options):
        db_config = connections["default"].settings_dict

        self.stdout.write(f"Database engine: {db_config.get('ENGINE', 'unknown')}")
        self.stdout.write(f"Database vendor: {connection.vendor}")
        self.stdout.write(f"Database name: {db_config.get('NAME', '')}")

        try:
            connection.ensure_connection()
            self.stdout.write("Connection: ok")

            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
            if not row or row[0] != 1:
                raise CommandError("SELECT 1 did not return the expected result.")
            self.stdout.write("SELECT 1: ok")

            pending_migrations = self._pending_migrations()
        except CommandError:
            raise
        except Exception as exc:
            self.stderr.write(f"Database check failed: {exc.__class__.__name__}")
            raise CommandError(
                "Database check failed. Verify the database host, name, credentials, "
                "ODBC driver, and network access."
            ) from exc

        if pending_migrations is None:
            self.stdout.write("Migrations: could not verify")
        elif pending_migrations:
            self.stdout.write("Migrations: pending")
            for app_label, migration_name in pending_migrations:
                self.stdout.write(f"- {app_label}.{migration_name}")
        else:
            self.stdout.write("Migrations: up to date")

    def _pending_migrations(self):
        try:
            executor = MigrationExecutor(connection)
            targets = executor.loader.graph.leaf_nodes()
            plan = executor.migration_plan(targets)
        except Exception as exc:
            self.stderr.write(f"Migration status check skipped: {exc.__class__.__name__}")
            return None

        return [
            (migration.app_label, migration.name)
            for migration, backwards in plan
            if not backwards
        ]
