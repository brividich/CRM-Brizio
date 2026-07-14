"""Task in background del modulo security.

Nell'HUB NOVICROM questi task girano tramite **django-q2** (non Celery, non usato
dal portale). Sono funzioni pure, senza dipendenze da broker/decoratori: si
accodano con `django_q.tasks.async_task("security.tasks.run_security_parsers_task")`
oppure si pianificano con un `django_q.models.Schedule`. La stessa logica è anche
disponibile via management command (`run_security_parsers`, `evaluate_security_rules`).
"""


def run_security_parsers_task():
    """Esegue i parser sui messaggi/file in attesa. Ritorna il numero di report elaborati."""
    from security.services.parser_engine import run_pending_parsers

    return run_pending_parsers()


def evaluate_security_rules_task():
    """Valuta le regole di alert sugli eventi ingeriti. Ritorna il numero di regole valutate."""
    from security.services.rule_engine import evaluate_security_rules

    return evaluate_security_rules()


def ingest_security_mailboxes_task():
    """Ingestione delle sorgenti mailbox Graph/IMAP abilitate (per django-q2/Schedule).

    Ritorna il numero di sorgenti processate senza errore. Le credenziali vanno
    configurate come SecurityCenterSetting (Configuration Studio).
    """
    from security.models import SecurityMailboxSource
    from security.services.mailbox_ingestion import run_mailbox_ingestion

    ok = 0
    for src in SecurityMailboxSource.objects.filter(enabled=True).exclude(source_type="manual"):
        try:
            run_mailbox_ingestion(src)
            ok += 1
        except Exception:
            continue
    return ok
