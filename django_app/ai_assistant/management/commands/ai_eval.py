"""Valutazione del routing dei tool runtime dell'assistente AI.

Esegue una batteria di "golden query" e, per ognuna, mostra quali domini
verrebbero attivati dal gate keyword e dal routing semantico (embeddings),
confrontandoli con i domini attesi. Serve a tarare AI_TOOL_ROUTING_THRESHOLD /
MARGIN / TOP_K su dati reali e a non regredire quando si toccano keyword o seed.

In modalita' ``--rag`` valuta invece il **retrieval documentale** (knowledge base
curata + RAG su file): per ogni golden query misura recall@k, MRR e rank-1, piu' la
copertura della KB (file non testati da alcuna golden). Funziona offline con BM25
(gli embeddings, opzionali, sono fail-safe), quindi serve a verificare che la
knowledge base risponda alle domande tipiche e a non regredire quando si toccano i file.

In modalita' ``--rag-live`` valuta la **copertura della KB sulle domande REALI**
memorizzate (``AiChatFeedback.prompt`` e, con ``--include-faq``, ``AiKnowledgeEntry``):
segnala i "gap" (domande che non recuperano alcun file di knowledge curato, al piu' il
README generico) come candidati per nuovi contenuti KB o nuove golden. Va eseguito dove
ci sono feedback raccolti (es. produzione). Non scrive nulla e non committa testo utente.

Esempi:
    python manage.py ai_eval --settings=config.settings.dev
    python manage.py ai_eval --json
    python manage.py ai_eval --query "quanto tempo libero mi resta per le ferie"
    python manage.py ai_eval --rag
    python manage.py ai_eval --rag --top-k 4 --json
    python manage.py ai_eval --rag-live --down-only
    python manage.py ai_eval --rag-live --include-faq --json
"""

from __future__ import annotations

import json
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand

from ai_assistant import services, tools


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


# (domanda, fonti accettabili). La "fonte attesa" e' un frammento del path del file
# di knowledge (di norma il nome file): la golden e' soddisfatta se almeno una delle
# fonti accettabili compare tra i primi --top-k chunk recuperati. Piu' frammenti
# convivono per i concetti trattati da piu' file (es. i ratei in Assenze e Glossario).
_RAG_GOLDEN: tuple[tuple[str, frozenset[str]], ...] = (
    ("che cos'e' novicrom hub?", frozenset({"01_portale_orientamento"})),
    ("come richiedo ferie o permessi?", frozenset({"02_assenze_ferie_permessi"})),
    ("cosa sono i ratei e le ferie residue?", frozenset({"02_assenze_ferie_permessi", "08_glossario"})),
    ("come apro una richiesta di assistenza?", frozenset({"03_tickets_assets_dpi"})),
    ("come funzionano i dpi?", frozenset({"03_tickets_assets_dpi", "08_glossario"})),
    ("dove leggo e confermo le procedure?", frozenset({"04_sicurezza_procedure_notizie"})),
    ("cosa devo fare oggi?", frozenset({"04_sicurezza_procedure_notizie"})),
    ("cosa sono le qualifiche e le abilitazioni?", frozenset({"05_anagrafica_qualifiche_formazione"})),
    ("come funziona l'e-learning e gli attestati?", frozenset({"05_anagrafica_qualifiche_formazione"})),
    ("a cosa serve il modulo anomalie?", frozenset({"06_anomalie_produzione"})),
    ("cosa significa aprire una rdc?", frozenset({"06_anomalie_produzione", "08_glossario"})),
    ("a cosa serve il modulo automazioni?", frozenset({"07_tasks_automazioni"})),
    ("come funzionano le approvazioni automatiche?", frozenset({"07_tasks_automazioni"})),
    ("quali task sono in ritardo?", frozenset({"07_tasks_automazioni"})),
    ("cosa significa rol?", frozenset({"08_glossario"})),
    ("cosa significa ordine di lavoro odl?", frozenset({"08_glossario"})),
    ("cosa sono le ex festivita?", frozenset({"08_glossario"})),
    ("cosa significa near miss quasi infortunio?", frozenset({"08_glossario", "04_sicurezza_procedure_notizie"})),
    ("come accedo al portale con autenticazione a due fattori?", frozenset({"09_accesso_account"})),
    ("non vedo un modulo nel menu, perche'?", frozenset({"09_accesso_account", "01_portale_orientamento"})),
    # Parafrasi colloquiali / sinonimi: esercitano la robustezza del retrieval BM25
    # (accent-folding, sinonimi) sulle stesse aree, come le direbbe un utente reale.
    ("quanti giorni di ferie mi restano?", frozenset({"02_assenze_ferie_permessi", "08_glossario"})),
    ("come segnalo un guasto del computer?", frozenset({"03_tickets_assets_dpi"})),
    ("quando scadono le mie abilitazioni?", frozenset({"05_anagrafica_qualifiche_formazione"})),
    ("a chi e' in carico un'anomalia?", frozenset({"06_anomalie_produzione"})),
    ("perche' ricevo email di promemoria dal portale?", frozenset({"07_tasks_automazioni"})),
    ("ho dimenticato la password, cosa faccio?", frozenset({"09_accesso_account"})),
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
        parser.add_argument(
            "--rag",
            action="store_true",
            help="Valuta il retrieval documentale (recall@k) invece del routing tool.",
        )
        parser.add_argument(
            "--top-k",
            type=int,
            default=0,
            help="N. di chunk considerati nel recall RAG (default OLLAMA_RAG_MAX_CHUNKS).",
        )
        parser.add_argument(
            "--sources",
            default="",
            help=(
                "Override CSV di OLLAMA_RAG_SOURCE_PATHS per il solo eval RAG. "
                "Usa 'README.md,django_app/ai_assistant/knowledge' per misurare il "
                "retrieval come in produzione (docs/ e' escluso dal pacchetto di deploy)."
            ),
        )
        parser.add_argument(
            "--rag-live",
            action="store_true",
            help=(
                "Valuta la COPERTURA della KB curata sulle domande REALI memorizzate "
                "(AiChatFeedback.prompt, opz. AiKnowledgeEntry). Segnala i 'gap' (domande "
                "che non recuperano alcun file di knowledge curato) come candidati per "
                "nuovi contenuti KB o nuove golden. Non scrive nulla; il testo non e' "
                "committato nel repo."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=200,
            help="Max domande reali distinte valutate in --rag-live (default 200).",
        )
        parser.add_argument(
            "--include-faq",
            action="store_true",
            help="In --rag-live includi anche le domande delle FAQ curate (AiKnowledgeEntry).",
        )
        parser.add_argument(
            "--down-only",
            action="store_true",
            help="In --rag-live considera solo i feedback negativi (risposte giudicate scarse).",
        )
        parser.add_argument(
            "--min-score",
            type=float,
            default=0.0,
            help=(
                "In --rag-live: soglia minima di score BM25 del miglior chunk KB perché la "
                "domanda conti come 'coperta'. Sotto soglia = gap 'debole' (match coincidente, "
                "risposta irrilevante). Default 0.0 = qualsiasi match conta; gli score sono "
                "mostrati sempre, quindi alza la soglia guardando la distribuzione reale."
            ),
        )

    def handle(self, *args, **options):
        as_json = bool(options.get("json"))
        custom = list(options.get("query") or [])

        if options.get("rag"):
            self._handle_rag(
                as_json=as_json,
                custom=custom,
                top_k=int(options.get("top_k") or 0),
                sources=str(options.get("sources") or "").strip(),
            )
            return

        if options.get("rag_live"):
            self._handle_rag_live(
                as_json=as_json,
                top_k=int(options.get("top_k") or 0),
                sources=str(options.get("sources") or "").strip(),
                limit=int(options.get("limit") or 200),
                include_faq=bool(options.get("include_faq")),
                down_only=bool(options.get("down_only")),
                min_score=float(options.get("min_score") or 0.0),
            )
            return

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
            self.stdout.write(
                self._safe(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
            )
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

    def _safe(self, text: str) -> str:
        """Rende il testo stampabile sulla console corrente (cp1252 su Windows).

        I file di knowledge curati sono ASCII/Latin, ma in dev il RAG indicizza
        anche docs/ai, che puo' contenere emoji nei titoli: senza questo filtro la
        stampa va in UnicodeEncodeError su console non-UTF8.
        """
        enc = getattr(getattr(self.stdout, "_out", None), "encoding", None) or "utf-8"
        try:
            text.encode(enc)
            return text
        except (UnicodeEncodeError, LookupError):
            return text.encode(enc, errors="replace").decode(enc, errors="replace")

    # ── Valutazione retrieval RAG (recall@k) ────────────────────────────────
    def _handle_rag(self, *, as_json: bool, custom: list[str], top_k: int, sources: str = "") -> None:
        rag_enabled = bool(getattr(settings, "OLLAMA_RAG_ENABLED", True))
        embeddings_on = services.embeddings_enabled()
        default_k = int(getattr(settings, "OLLAMA_RAG_MAX_CHUNKS", 4) or 4)
        k = top_k if top_k > 0 else default_k

        if sources:
            # Override prod-like dei path RAG per il solo eval (es. escludere docs/).
            override = [item.strip() for item in sources.split(",") if item.strip()]
            settings.OLLAMA_RAG_SOURCE_PATHS = override
            services.clear_knowledge_cache()

        index = services._load_knowledge_index()

        if custom:
            cases: list[tuple[str, frozenset[str]]] = [(q, frozenset()) for q in custom]
        else:
            cases = list(_RAG_GOLDEN)

        results = []
        hits = 0
        reciprocal_ranks: list[float] = []
        rank1 = 0
        for query, expected in cases:
            tokens = Counter(services._tokenize(query))
            ranked_full = services._select_chunk_indices(query, tokens, index)
            selected = ranked_full[:k]
            retrieved = [
                {"source": index.chunks[i].source, "title": index.chunks[i].title}
                for i in selected
            ]
            # Rank (1-based) del primo chunk con la fonte attesa nell'INTERA classifica:
            # cattura le regressioni di ordinamento che il recall@k non vede (un file
            # che scivola da rank 1 a rank 4 resta "hit" ma peggiora la risposta).
            rank = None
            if expected:
                for position, i in enumerate(ranked_full, start=1):
                    if any(frag in index.chunks[i].source for frag in expected):
                        rank = position
                        break
            recall_ok = None
            if expected:
                recall_ok = rank is not None and rank <= k
                if recall_ok:
                    hits += 1
                reciprocal_ranks.append(1.0 / rank if rank else 0.0)
                if rank == 1:
                    rank1 += 1
            results.append(
                {
                    "query": query,
                    "expected": sorted(expected),
                    "retrieved": retrieved,
                    "rank": rank,
                    "recall_ok": recall_ok,
                }
            )

        mrr = round(sum(reciprocal_ranks) / len(reciprocal_ranks), 3) if reciprocal_ranks else None
        coverage = self._kb_golden_coverage() if not custom else None
        summary = {
            "mode": "rag",
            "rag_enabled": rag_enabled,
            "embeddings_enabled": embeddings_on,
            "top_k": k,
            "source_paths": services._source_paths(),
            "chunks_indexed": len(index.chunks),
            "cases": len(cases),
            "recall_hits": hits if not custom else None,
            "mrr": mrr if not custom else None,
            "rank1_hits": rank1 if not custom else None,
            "kb_files_uncovered": coverage if not custom else None,
        }

        if as_json:
            self.stdout.write(
                self._safe(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
            )
            return

        retrieval_mode = "ibrido BM25+semantico" if embeddings_on else "BM25"
        self.stdout.write(
            f"RAG: {'ON' if rag_enabled else 'OFF'} | retrieval={retrieval_mode} | "
            f"top_k={k} | chunk indicizzati={len(index.chunks)}"
        )
        self.stdout.write(self._safe(f"sorgenti: {', '.join(services._source_paths())}"))
        self.stdout.write("-" * 78)
        for row in results:
            flag = "  " if row["recall_ok"] is None else ("OK" if row["recall_ok"] else "!!")
            rank_txt = f" (rank {row['rank']})" if row["rank"] else (" (non trovata)" if row["expected"] else "")
            self.stdout.write(self._safe(f"[{flag}] {row['query']}{rank_txt}"))
            if row["expected"]:
                self.stdout.write(f"      attesa fonte tra: {row['expected']}")
            for r in row["retrieved"]:
                self.stdout.write(self._safe(f"        - {r['source']} > {r['title']}"))
            if row["recall_ok"] is False:
                self.stdout.write(
                    self.style.ERROR("      MISS: fonte attesa non tra i primi top_k chunk")
                )
        self.stdout.write("-" * 78)
        if not custom:
            self.stdout.write(
                f"Recall@{k}: {hits}/{len(cases)} | rank-1: {rank1}/{len(cases)} | "
                f"MRR: {mrr}"
            )
            if coverage:
                self.stdout.write(
                    self.style.WARNING(
                        "File KB non coperti da alcuna golden: " + ", ".join(coverage)
                    )
                )
        if not index.chunks:
            self.stdout.write(
                self.style.WARNING(
                    "Nessun chunk indicizzato: verifica OLLAMA_RAG_ENABLED e OLLAMA_RAG_SOURCE_PATHS."
                )
            )

    def _kb_golden_coverage(self) -> list[str]:
        """File .md della KB pacchettizzata non esercitati da alcuna golden RAG.

        Guardia di completezza: se si aggiunge un file di knowledge senza una golden
        che lo punti, resta non testato (retrieval mai verificato). README.md della
        cartella e' meta-documentazione e non e' un bersaglio di risposta.
        """
        from pathlib import Path

        kb_dir = Path(services.__file__).resolve().parent / "knowledge"
        if not kb_dir.is_dir():
            return []
        expected_fragments = {frag for _q, expected in _RAG_GOLDEN for frag in expected}
        uncovered: list[str] = []
        for path in sorted(kb_dir.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            stem = path.stem
            if not any(frag in stem or stem in frag for frag in expected_fragments):
                uncovered.append(path.name)
        return uncovered

    @staticmethod
    def _is_curated_kb_chunk(source: str) -> bool:
        """True se il chunk proviene da un file di knowledge curato (non il README)."""
        normalized = source.replace("\\", "/")
        return "ai_assistant/knowledge/" in normalized and not normalized.lower().endswith("/readme.md")

    # ── Copertura KB sulle domande REALI (AiChatFeedback / FAQ) ─────────────
    def _handle_rag_live(
        self,
        *,
        as_json: bool,
        top_k: int,
        sources: str,
        limit: int,
        include_faq: bool,
        down_only: bool,
        min_score: float = 0.0,
    ) -> None:
        embeddings_on = services.embeddings_enabled()
        default_k = int(getattr(settings, "OLLAMA_RAG_MAX_CHUNKS", 4) or 4)
        k = top_k if top_k > 0 else default_k

        if sources:
            settings.OLLAMA_RAG_SOURCE_PATHS = [i.strip() for i in sources.split(",") if i.strip()]
            services.clear_knowledge_cache()
        index = services._load_knowledge_index()

        # Raccolta domande reali (in memoria, mai persistite ne' committate).
        harvested: list[tuple[str, str]] = []
        try:
            from ai_assistant.models import AiChatFeedback

            qs = AiChatFeedback.objects.all()
            if down_only:
                qs = qs.filter(rating="down")
            for text in qs.order_by("-created_at").values_list("prompt", flat=True)[: max(limit * 3, limit)]:
                cleaned = (text or "").strip()
                if cleaned:
                    harvested.append((cleaned, "feedback"))
        except Exception:
            pass
        if include_faq:
            try:
                from ai_assistant.models import AiKnowledgeEntry

                for text in (
                    AiKnowledgeEntry.objects.order_by("-updated_at").values_list("question", flat=True)[:limit]
                ):
                    cleaned = (text or "").strip()
                    if cleaned:
                        harvested.append((cleaned, "faq"))
            except Exception:
                pass

        seen: set[str] = set()
        deduped: list[tuple[str, str]] = []
        for text, origin in harvested:
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append((text, origin))
            if len(deduped) >= limit:
                break

        results = []
        covered = 0
        weak = 0
        for text, origin in deduped:
            tokens = Counter(services._tokenize(text))
            ranked = services._select_chunk_indices(text, tokens, index)[:k]
            top = [{"source": index.chunks[i].source, "title": index.chunks[i].title} for i in ranked]
            # Score BM25 (lessicale) del MIGLIOR chunk KB curato tra i top-k: misura
            # quanto il match e' davvero pertinente (vale anche in modalita' ibrida).
            kb_score = None
            for i in ranked:
                if self._is_curated_kb_chunk(index.chunks[i].source):
                    score = services._bm25_score(tokens, index.chunks[i], index.idf, index.avgdl)
                    if kb_score is None or score > kb_score:
                        kb_score = score
            has_kb = kb_score is not None
            is_covered = has_kb and kb_score >= min_score
            is_weak = has_kb and not is_covered  # recupera un file KB ma sotto soglia
            if is_covered:
                covered += 1
            if is_weak:
                weak += 1
            results.append(
                {
                    "prompt": text,
                    "origin": origin,
                    "covered": is_covered,
                    "weak": is_weak,
                    "kb_score": round(kb_score, 2) if kb_score is not None else None,
                    "top_source": top[0]["source"] if top else None,
                    "top_title": top[0]["title"] if top else None,
                }
            )

        n = len(deduped)
        gaps = [r for r in results if not r["covered"]]
        summary = {
            "mode": "rag-live",
            "embeddings_enabled": embeddings_on,
            "top_k": k,
            "min_score": min_score,
            "source_paths": services._source_paths(),
            "evaluated": n,
            "covered": covered,
            "gaps": len(gaps),
            "weak_gaps": weak,
            "coverage_pct": round(100.0 * covered / n, 1) if n else None,
            "down_only": down_only,
            "include_faq": include_faq,
        }

        if as_json:
            # Tronca i prompt (input utente reale) nel JSON: non serve l'intero testo.
            out_results = [{**r, "prompt": r["prompt"][:200]} for r in results]
            self.stdout.write(
                self._safe(json.dumps({"summary": summary, "results": out_results}, ensure_ascii=False, indent=2))
            )
            return

        mode = "ibrido BM25+semantico" if embeddings_on else "BM25"
        self.stdout.write(
            f"RAG-LIVE: retrieval={mode} | top_k={k} | min_score={min_score} | "
            f"domande reali valutate={n}"
        )
        self.stdout.write(self._safe(f"sorgenti KB: {', '.join(services._source_paths())}"))
        if n == 0:
            self.stdout.write(
                self.style.WARNING(
                    "Nessuna domanda reale trovata (AiChatFeedback vuoto). Esegui in un "
                    "ambiente con feedback raccolti (es. produzione), eventualmente con --include-faq."
                )
            )
            return
        self.stdout.write("-" * 78)
        self.stdout.write(
            self.style.WARNING(
                "NB: il testo sotto e' input reale degli utenti; non viene salvato ne' committato."
            )
        )
        for row in gaps:
            tag = "GAP-DEBOLE" if row["weak"] else "GAP"
            self.stdout.write(self._safe(f"[{tag}/{row['origin']}] {row['prompt'][:120]}"))
            if row["weak"]:
                self.stdout.write(
                    self._safe(
                        f"        recupera (debole, score {row['kb_score']} < {min_score}): "
                        f"{row['top_source']} > {row['top_title']}"
                    )
                )
            elif row["top_source"]:
                self.stdout.write(
                    self._safe(f"        recupera invece: {row['top_source']} > {row['top_title']}")
                )
            else:
                self.stdout.write("        recupera: (nessun chunk)")
        self.stdout.write("-" * 78)
        self.stdout.write(
            f"Copertura KB curata: {covered}/{n} ({summary['coverage_pct']}%) | "
            f"gap: {len(gaps)} (di cui deboli: {weak})"
        )
        self.stdout.write(
            "I gap sono candidati per nuovi contenuti KB o nuove golden (da curare a mano, "
            "senza committare testo utente reale). Alza --min-score per scremare i match deboli."
        )
