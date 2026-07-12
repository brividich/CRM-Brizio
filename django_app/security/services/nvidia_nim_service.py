"""
Legacy NVIDIA NIM Service

DEPRECATED: This module is a legacy compatibility wrapper.
Use security.ai.providers.nvidia_nim via security.ai.services.ai_gateway instead.

This module is retained for test compatibility only and is not used in runtime code.
All new code should use the AI Gateway abstraction layer.
"""

import hashlib
import json
import logging
import os
import re
from typing import Dict, List, Optional, Generator

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Cache settings
CACHE_TIMEOUT = 3600  # 1 hour


class AIProviderConfigurationError(Exception):
    """Raised when AI provider is not properly configured"""
    pass


class NVIDIA_NIM_Service:
    def __init__(self):
        self.api_key = NVIDIA_API_KEY
        self.api_url = NVIDIA_API_URL

    def _check_configuration(self):
        """Check if the service is properly configured"""
        if not self.api_key or not self.api_key.strip() or self.api_key == "your-api-key-here":
            raise AIProviderConfigurationError("NVIDIA_API_KEY not configured")

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _generate_cache_key(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate a stable cache key using SHA256"""
        key_data = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        key_string = json.dumps(key_data, sort_keys=True)
        hash_obj = hashlib.sha256(key_string.encode())
        return f"nim_chat:{hash_obj.hexdigest()}"

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "meta/llama-3.1-70b-instruct",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> Dict:
        """Invia richiesta di chat completion a NVIDIA NIM"""
        self._check_configuration()

        cache_key = self._generate_cache_key(messages, model, temperature, max_tokens)
        cached = cache.get(cache_key)
        if cached:
            return cached

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        try:
            response = requests.post(
                self.api_url,
                headers=self._get_headers(),
                json=payload,
                timeout=120,
            )
            response.raise_for_status()

            result = response.json()
            cache.set(cache_key, result, CACHE_TIMEOUT)
            return result
        except requests.exceptions.Timeout:
            logger.exception("NVIDIA API timeout")
            raise Exception("AI service temporarily unavailable")
        except requests.exceptions.HTTPError as e:
            logger.exception(f"NVIDIA API HTTP error: {e.response.status_code}")
            raise Exception("AI service temporarily unavailable")
        except requests.exceptions.RequestException as e:
            logger.exception("NVIDIA API request error")
            raise Exception("AI service temporarily unavailable")

    def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        model: str = "meta/llama-3.1-70b-instruct",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Generator[str, None, None]:
        """Invia richiesta di chat completion con streaming"""
        self._check_configuration()

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            response = requests.post(
                self.api_url,
                headers=self._get_headers(),
                json=payload,
                stream=True,
                timeout=120,
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode("utf-8").replace("data: ", ""))
                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue
        except requests.exceptions.Timeout:
            logger.exception("NVIDIA API timeout")
            raise Exception("AI service temporarily unavailable")
        except requests.exceptions.HTTPError as e:
            logger.exception(f"NVIDIA API HTTP error: {e.response.status_code}")
            raise Exception("AI service temporarily unavailable")
        except requests.exceptions.RequestException as e:
            logger.exception("NVIDIA API request error")
            raise Exception("AI service temporarily unavailable")

    def analyze_security_report(self, report_content: str) -> Dict:
        """Analizza un report di sicurezza"""
        system_prompt = """Sei un esperto di sicurezza informatica. Analizza il seguente report di sicurezza e fornisci:
1. Riassunto esecutivo (max 200 parole)
2. Vulnerabilità rilevate (CVE, severità, asset)
3. Raccomandazioni prioritarie
4. Rischi identificati
5. Azioni suggerite

Rispondi in formato JSON con le seguenti chiavi:
{
  "summary": "riassunto esecutivo",
  "vulnerabilities": [{"cve": "CVE-XXXX-XXXX", "severity": "high/medium/low", "asset": "hostname/IP", "description": "descrizione"}],
  "recommendations": ["raccomandazione 1", "raccomandazione 2"],
  "risks": ["rischio 1", "rischio 2"],
  "suggested_actions": ["azione 1", "azione 2"]
}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Analizza questo report:\n\n{report_content}"},
        ]

        response = self.chat_completion(
            messages=messages,
            model="meta/llama-3.1-70b-instruct",
            temperature=0.3,
            max_tokens=4096,
        )

        try:
            content = response["choices"][0]["message"]["content"]

            # Estrai JSON dal contenuto
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            # Pulisci caratteri di controllo non validi
            content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)

            return json.loads(content)
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"Error parsing AI response: {e}")
            return {
                "summary": "Impossibile analizzare il report",
                "vulnerabilities": [],
                "recommendations": [],
                "risks": [],
                "suggested_actions": [],
            }

    def suggest_alert_rule(self, context: str) -> Dict:
        """Suggerisce una regola di alert basata sul contesto"""
        system_prompt = """Sei un esperto di sicurezza informatica. Basandoti sul contesto fornito, suggerisci una regola di alert appropriata.

Rispondi in formato JSON con le seguenti chiavi:
{
  "rule_name": "nome della regola",
  "condition": "condizione che deve attivare l'alert",
  "severity": "critical/high/medium/low",
  "description": "descrizione della regola",
  "recommended_actions": ["azione 1", "azione 2"],
  "rationale": "spiegazione del perché questa regola è appropriata"
}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Contesto:\n\n{context}"},
        ]

        response = self.chat_completion(
            messages=messages,
            model="meta/llama-3.1-8b-instruct",
            temperature=0.5,
            max_tokens=1024,
        )

        try:
            content = response["choices"][0]["message"]["content"]

            # Estrai JSON dal contenuto (potrebbe essere racchiuso in blocchi di codice markdown)
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            # Pulisci caratteri di controllo non validi
            content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)

            return json.loads(content)
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"Error parsing AI response: {e}")
            return {
                "rule_name": "Regola generica",
                "condition": "condizione generica",
                "severity": "medium",
                "description": "Descrizione generica",
                "recommended_actions": [],
                "rationale": "Impossibile generare suggerimento",
            }

    def analyze_events(self, events: List[Dict]) -> Dict:
        """Analizza una serie di eventi per rilevare pattern"""
        system_prompt = """Sei un esperto di sicurezza informatica. Analizza la seguente serie di eventi e fornisci:
1. Pattern rilevati
2. Eventi anomali
3. Correlazioni tra eventi
4. Minacce potenziali
5. Raccomandazioni

Rispondi in formato JSON con le seguenti chiavi:
{
  "patterns": ["pattern 1", "pattern 2"],
  "anomalies": [{"event_id": "ID", "description": "descrizione"}],
  "correlations": ["correlazione 1", "correlazione 2"],
  "potential_threats": ["minaccia 1", "minaccia 2"],
  "recommendations": ["raccomandazione 1", "raccomandazione 2"]
}"""

        events_json = json.dumps(events, indent=2)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Eventi:\n\n{events_json}"},
        ]

        response = self.chat_completion(
            messages=messages,
            model="meta/llama-3.1-70b-instruct",
            temperature=0.4,
            max_tokens=4096,
        )

        try:
            content = response["choices"][0]["message"]["content"]

            # Estrai JSON dal contenuto
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            # Pulisci caratteri di controllo non validi
            content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)

            return json.loads(content)
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"Error parsing AI response: {e}")
            return {
                "patterns": [],
                "anomalies": [],
                "correlations": [],
                "potential_threats": [],
                "recommendations": [],
            }

    def generate_summary(self, data: Dict) -> str:
        """Genera un riassunto dei dati forniti"""
        system_prompt = """Sei un esperto di sicurezza informatica. Genera un riassunto conciso e informativo dei dati forniti.
Il riassunto deve essere in italiano, massimo 300 parole, e includere:
- Punti chiave
- Metriche importanti
- Raccomandazioni principali"""

        data_json = json.dumps(data, indent=2)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Dati:\n\n{data_json}"},
        ]

        response = self.chat_completion(
            messages=messages,
            model="meta/llama-3.1-8b-instruct",
            temperature=0.5,
            max_tokens=512,
        )

        try:
            return response["choices"][0]["message"]["content"]
        except KeyError:
            logger.warning("Error extracting summary from AI response")
            return "Impossibile generare riassunto"


# Singleton instance
nvidia_nim_service = NVIDIA_NIM_Service()
