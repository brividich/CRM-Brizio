from security_center_ai.celery import app


@app.task
def run_security_parsers_task():
    from security.services.parser_engine import run_pending_parsers

    return run_pending_parsers()


@app.task
def evaluate_security_rules_task():
    from security.services.rule_engine import evaluate_security_rules

    return evaluate_security_rules()
