"""Valutazione del routing dei tool runtime dell'assistente AI.

Esegue una batteria di "golden query" e, per ognuna, mostra quali domini
verrebbero attivati dal gate keyword e dal routing semantico (embeddings),
confrontandoli con i domini attesi. Serve a tarare AI_TOOL_ROUTING_THRESHOLD /
MARGIN / TOP_K su dati reali e a non regredire quando si toccano keyword o seed.

Esempi:
    python manage.py ai_eval --settings=config.settings.dev
    python manage.py ai_eval --json
    python manage.py ai_eval --query "quanto tempo libero mi resta per le ferie"
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from ai_assistant import tools


# Mappa dominio -> gate keyword (funzione pura su prompt).
_KEYWORD_GATES = {
    "absence": tools._wants_absence_list,
    "modules": tools._wants_module_catalog,
    "tickets": tools._wants_ticket_context,
    "tasks": tools._wants_task_context,
    "assets": tools._wants_asset_context,
    "dpi": tools._wants_dpi_context,
    "anagrafica": tools._wants_anagrafica_context,
    "anomalie": tools._wants_anomalie_context,
    "procedure": tools._wants_procedure_context,
    "notizie": tools._wants_notizie_context,
    "sicurezza": tools._wants_sicurezza_context,
}

# (query, domini attesi). Coprono casi semplici, sinonimi fuori vocabolario e
# i falsi positivi noti (es. "ferie in scadenza" NON deve essere assets).
_GOLDEN: tuple[tuple[str, set[str]], ...] = (
    ("chi e' assente domani?", {"absence"}),
    ("chi e' in ferie questa settimana?", {"absence"}),
    ("elenca i dipendenti in ordine delle ferie piu elevate", {"anagrafica"}),
    ("chi ha piu ferie accumulate?", {"anagrafica"}),
    ("quante ore di permessi ho ancora?", {"anagrafica"}),
    ("quanto tempo libero mi resta da prendere quest'anno", {"anagrafica"}),
    ("ferie in scadenza dei dipendenti", {"anagrafica"}),
    ("quali ticket urgenti sono aperti?", {"tickets"}),
    ("ho una richiesta di assistenza in sospeso", {"tickets"}),
    ("quali task sono in ritardo?", {"tasks"}),
    ("scadenze dei progetti della prossima settimana", {"tasks"}),
    ("manutenzione del carroponte", {"assets"}),
    ("quali attrezzature sono in riparazione?", {"assets"}),
    ("ho dei dpi da ritirare?", {"dpi"}),
    ("anomalie aperte nel mio reparto", {"anomalie"}),
    ("ho procedure da leggere o quiz da fare?", {"procedure"}),
    ("ci sono notizie obbligatorie da confermare?", {"notizie"}),
    ("kpi di sicurezza near miss e incidenti", {"sicurezza"}),
    ("quali moduli posso usare nel portale?", {"modules"}),
)


class Command(BaseCommand):
    help = "Valuta il routing dei tool runtime AI su un set di golden query."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Output in JSON.")
        parser.add_argument(
            "--query",
            action="append",
            default=[],
            help="Valuta una query ad-hoc (ripetibile). Disattiva il set golden.",
        )

    def handle(self, *args, **options):
        as_json = bool(options.get("json"))
        custom = list(options.get("query") or [])

        threshold = float(getattr(settings, "AI_TOOL_ROUTING_THRESHOLD", 0.70) or 0.70)
        margin = float(getattr(settings, "AI_TOOL_ROUTING_MARGIN", 0.04) or 0.0)
        top_k = int(getattr(settings, "AI_TOOL_ROUTING_TOP_K", 2) or 2)
        embeddings_on = bool(getattr(settings, "OLLAMA_EMBED_ENABLED", False))

        if custom:
            cases = [(q, set()) for q in custom]
        else:
            cases = list(_GOLDEN)

        results = []
        hits = 0
        extras_total = 0
        for query, expected in cases:
            keyword_active = {d for d, gate in _KEYWORD_GATES.items() if gate(query)}
            ranked = tools._rank_domains(query)
            semantic_active = tools._active_from_ranked(ranked)
            final = keyword_active | semantic_active

            recall_ok = expected.issubset(final) if expected else None
            extras = sorted(final - expected) if expected else sorted(final)
            if expected:
                if recall_ok:
                    hits += 1
                extras_total += len(final - expected)

            results.append(
                {
                    "query": query,
                    "expected": sorted(expected),
                    "keyword": sorted(keyword_active),
                    "semantic": sorted(semantic_active),
                    "final": sorted(final),
                    "recall_ok": recall_ok,
                    "extras": extras,
                    "top_scores": {d: round(s, 3) for d, s in ranked[:4]},
                }
            )

        summary = {
            "embeddings_enabled": embeddings_on,
            "threshold": threshold,
            "margin": margin,
            "top_k": top_k,
            "cases": len(cases),
            "recall_hits": hits if not custom else None,
            "extras_total": extras_total if not custom else None,
        }

        if as_json:
            self.stdout.write(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
            return

        self.stdout.write(
            f"Embeddings: {'ON' if embeddings_on else 'OFF (solo keyword)'} | "
            f"soglia={threshold} margine={margin} top_k={top_k}"
        )
        self.stdout.write("-" * 78)
        for row in results:
            flag = "  " if row["recall_ok"] is None else ("OK" if row["recall_ok"] else "!!")
            self.stdout.write(f"[{flag}] {row['query']}")
            self.stdout.write(
                f"      atteso={row['expected']} keyword={row['keyword']} "
                f"semantico={row['semantic']}"
            )
            if row["top_scores"]:
                scores = ", ".join(f"{d}:{s}" for d, s in row["top_scores"].items())
                self.stdout.write(f"      top: {scores}")
            if row["recall_ok"] is False:
                self.stdout.write(self.style.ERROR(f"      MISS: atteso non attivato -> {row['expected']}"))
            elif row["extras"] and row["expected"]:
                self.stdout.write(f"      extra attivati: {row['extras']}")
        self.stdout.write("-" * 78)
        if not custom:
            self.stdout.write(
                f"Recall: {hits}/{len(cases)} golden con dominio atteso attivato. "
                f"Domini extra totali: {extras_total}."
            )
            if not embeddings_on:
                self.stdout.write(
                    self.style.WARNING(
                        "Embeddings spenti: valutato solo il gate keyword. "
                        "Attiva OLLAMA_EMBED_ENABLED per valutare il routing semantico."
                    )
                )
