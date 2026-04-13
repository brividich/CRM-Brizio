import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def execute_teams_notification(action_config, context_payload):
    """
    Invia una notifica a un canale Microsoft Teams.
    Config previsto in action_config (allineato ai preset):
    - teams_webhook_url
    - teams_title_template
    - teams_text_template
    - teams_theme_color
    - teams_facts_text (formato: Chiave = {valore}\nAltra = {valore})
    """
    webhook_url = action_config.get('teams_webhook_url')
    if not webhook_url:
        logger.error("Azione Teams fallita: URL Webhook mancante.")
        return False

    # Risoluzione dinamica dei segnaposto
    try:
        title = action_config.get('teams_title_template', 'Notifica Hub').format(**context_payload)
        summary = action_config.get('teams_summary_template', 'Evento rilevato').format(**context_payload)
        text = action_config.get('teams_text_template', '').format(**context_payload)
        
        # Gestione dei Facts (dettagli tabellari nella card Teams)
        facts = []
        facts_raw = action_config.get('teams_facts_text', '')
        if facts_raw:
            for line in facts_raw.splitlines():
                if '=' in line:
                    k, v = line.split('=', 1)
                    facts.append({
                        "name": k.strip(),
                        "value": v.strip().format(**context_payload)
                    })
    except KeyError as e:
        logger.error(f"Errore formattazione template Teams: segnaposto {e} non trovato nel payload.")
        return False
    
    teams_payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": action_config.get('teams_theme_color', '2563EB'),
        "summary": summary,
        "sections": [{
            "activityTitle": title,
            "text": text,
            "facts": facts,
            "markdown": True
        }]
    }

    try:
        response = requests.post(webhook_url, json=teams_payload, timeout=15)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.exception(f"Errore durante l'invio della notifica Teams: {e}")
        return False