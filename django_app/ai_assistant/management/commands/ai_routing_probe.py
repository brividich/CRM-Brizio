"""Sonda il routing semantico dei tool AI: per ogni prompt mostra i domini più
vicini (score coseno) e quali si attivano con soglia/margine/top-K correnti.

Serve a RITARARE ``AI_TOOL_ROUTING_THRESHOLD`` / ``_MARGIN`` / ``_TOP_K`` quando si
aggiungono nuovi domini/tool (es. contatori, schede_sicurezza, suggestioni): le
soglie erano calibrate sui domini storici e su un dato modello di embedding.

Va eseguito DOVE gli embeddings sono live (prod: TEI/Ollama). Senza embeddings il
routing gira in keyword-only e il comando lo segnala (nessuno score da misurare).

    python manage.py ai_routing_probe                 # batch di sonde predefinite
    python manage.py ai_routing_probe --prompt "..."  # singolo prompt
    python manage.py ai_routing_probe --top 5         # quanti domini mostrare
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

# Sonde: frasi FUORI dal vocabolario dei seed di ``_DOMAIN_ROUTING_SEEDS``, per
# misurare il RECALL semantico (il gate keyword già copre le frasi "in vocabolario").
# (dominio_atteso, prompt)
_PROBES = (
    ("contatori", "quante copie abbiamo stampato in ufficio quest'anno?"),
    ("contatori", "qual e' il reparto che consuma piu' toner e stampe?"),
    ("schede_sicurezza", "che precauzioni e protezioni servono per l'acetone?"),
    ("schede_sicurezza", "la scheda del diluente e' ancora valida o va aggiornata?"),
    ("suggestioni", "come procede il miglioramento continuo in produzione?"),
    ("suggestioni", "ci sono idee di miglioramento ferme da troppo tempo?"),
    # Baseline domini storici (per verificare che i nuovi non "rubino" il routing).
    ("assets", "quali attrezzature sono in riparazione?"),
    ("carichi", "quanto e' occupata la fresa questa settimana?"),
)


class Command(BaseCommand):
    help = "Sonda il routing semantico dei tool AI (score per dominio + attivazione)."

    def add_arguments(self, parser):
        parser.add_argument("--prompt", help="Prompt singolo da sondare (invece del batch).")
        parser.add_argument("--top", type=int, default=4, help="Quanti domini mostrare per prompt.")
        # Override temporanei (solo per questa esecuzione, non toccano il .env): servono
        # allo sweep di soglie candidate senza riavviare/riconfigurare l'app.
        parser.add_argument("--threshold", type=float, help="Override AI_TOOL_ROUTING_THRESHOLD per questa run.")
        parser.add_argument("--margin", type=float, help="Override AI_TOOL_ROUTING_MARGIN per questa run.")
        parser.add_argument("--top-k", type=int, dest="top_k", help="Override AI_TOOL_ROUTING_TOP_K per questa run.")

    def handle(self, *args, **options):
        from ai_assistant import services
        from ai_assistant.tools import _rank_domains, _semantic_active_domains

        # Override in-process (settings mutabili a runtime; ogni invocazione e' un
        # processo a se', quindi non contamina l'app in esecuzione).
        if options.get("threshold") is not None:
            settings.AI_TOOL_ROUTING_THRESHOLD = float(options["threshold"])
        if options.get("margin") is not None:
            settings.AI_TOOL_ROUTING_MARGIN = float(options["margin"])
        if options.get("top_k") is not None:
            settings.AI_TOOL_ROUTING_TOP_K = int(options["top_k"])

        thr = getattr(settings, "AI_TOOL_ROUTING_THRESHOLD", 0.70)
        margin = getattr(settings, "AI_TOOL_ROUTING_MARGIN", 0.04)
        top_k = getattr(settings, "AI_TOOL_ROUTING_TOP_K", 2)
        enabled = bool(getattr(settings, "AI_TOOL_ROUTING_ENABLED", True))

        self.stdout.write(
            f"Routing: enabled={enabled} threshold={thr} margin={margin} top_k={top_k}"
        )
        if not enabled:
            self.stdout.write(self.style.WARNING(
                "AI_TOOL_ROUTING_ENABLED=False: routing semantico spento (solo keyword)."
            ))
            return
        if not services.embeddings_enabled():
            self.stdout.write(self.style.WARNING(
                "Embeddings non disponibili: routing in keyword-only. Esegui questo comando "
                "DOVE TEI/Ollama sono live (prod) per misurare gli score dei nuovi domini."
            ))
            return

        top = max(1, int(options["top"]))
        if options.get("prompt"):
            probes = [(None, options["prompt"])]
        else:
            probes = list(_PROBES)

        mismatches = 0
        for expected, prompt in probes:
            ranked = _rank_domains(prompt)
            active = _semantic_active_domains(prompt)
            head = ", ".join(f"{d}={s:.3f}" for d, s in ranked[:top]) or "(nessuno)"
            act = ", ".join(sorted(active)) or "(nessun dominio attivo)"
            flag = ""
            if expected:
                ok = expected in active
                if not ok:
                    mismatches += 1
                flag = self.style.SUCCESS(" OK") if ok else self.style.ERROR(f" MISS (atteso {expected})")
            self.stdout.write(f"\n> {prompt}")
            self.stdout.write(f"  top:    {head}")
            self.stdout.write(f"  attivi: {act}{flag}")

        if not options.get("prompt"):
            tot = len(_PROBES)
            self.stdout.write(
                f"\nSonde col dominio atteso attivo: {tot - mismatches}/{tot}.\n"
                "Troppe MISS sui nuovi domini -> abbassa AI_TOOL_ROUTING_THRESHOLD (o alza "
                "TOP_K/MARGIN), poi ri-sonda; verifica che i domini errati NON si attivino "
                "(falsi positivi). Il gate keyword resta comunque attivo a prescindere."
            )
