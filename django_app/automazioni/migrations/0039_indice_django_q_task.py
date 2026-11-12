"""Indice su ``django_q_task.cluster`` (tabella di django-q, non nostra): chiesto da SQL Server in produzione.

Il 12/11/2026 ``sys.dm_db_missing_index_details`` lo dava al 98% di impatto stimato su 1.040 ricerche
(controlli del cluster sui task in corso). django-q non lo dichiara, quindi si crea qui, solo su SQL
Server e solo se manca; su SQLite (sviluppo e test) non fa niente.
"""

from django.db import migrations

NOME = "dq_task_cluster_stop_idx"


def crea(apps, schema_editor):
    if schema_editor.connection.vendor != "microsoft":
        return
    schema_editor.execute(
        f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{NOME}' AND object_id = OBJECT_ID('django_q_task')) "
        f"CREATE INDEX {NOME} ON django_q_task (cluster) INCLUDE (stopped)"
    )


def togli(apps, schema_editor):
    if schema_editor.connection.vendor != "microsoft":
        return
    schema_editor.execute(
        f"IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{NOME}' AND object_id = OBJECT_ID('django_q_task')) "
        f"DROP INDEX {NOME} ON django_q_task"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0038_indici_lentezza_prod"),
        ("django_q", "0018_task_success_index"),
    ]

    operations = [migrations.RunPython(crea, togli)]
