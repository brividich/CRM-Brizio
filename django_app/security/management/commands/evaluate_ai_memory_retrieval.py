from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from security.ai.services.memory.evaluation import (
    DEFAULT_THRESHOLDS,
    format_evaluation_report,
    run_retrieval_evaluation,
)


class Command(BaseCommand):
    help = "Evaluate AI Memory retrieval quality against the synthetic benchmark corpus."

    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=["hybrid_keyword", "vector_json_fallback", "hybrid_pgvector"], default="hybrid_keyword")
        parser.add_argument("--top-k", type=int, default=5)
        parser.add_argument("--min-score", type=float)
        parser.add_argument("--format", choices=["text", "json"], default="text")
        parser.add_argument("--fail-under-hit-at-3", type=float)
        parser.add_argument("--fail-under-mrr", type=float)
        parser.add_argument("--include-safety", action="store_true", default=True)
        parser.add_argument("--rebuild-synthetic-corpus", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--output", default="")

    def handle(self, *args, **options):
        report = run_retrieval_evaluation(
            mode=options["mode"],
            top_k=options["top_k"],
            min_score=options["min_score"],
            include_safety=options["include_safety"],
            rebuild_synthetic_corpus=options["rebuild_synthetic_corpus"],
            dry_run=options["dry_run"],
        )
        rendered = format_evaluation_report(report, output_format=options["format"])
        output_path = str(options.get("output") or "").strip()
        if output_path:
            Path(output_path).write_text(rendered + "\n", encoding="utf-8")
        self.stdout.write(rendered)
        if options["dry_run"]:
            return

        aggregate = report["aggregate"]
        failures = []
        hit_threshold = options["fail_under_hit_at_3"]
        mrr_threshold = options["fail_under_mrr"]
        if hit_threshold is None:
            hit_threshold = DEFAULT_THRESHOLDS["hit_rate_at_3"]
        if mrr_threshold is not None and aggregate["mean_reciprocal_rank"] < float(mrr_threshold):
            failures.append(f"MRR {aggregate['mean_reciprocal_rank']:.4f} below {float(mrr_threshold):.4f}")
        if aggregate["hit_rate_at_3"] < float(hit_threshold):
            failures.append(f"hit@3 {aggregate['hit_rate_at_3']:.4f} below {float(hit_threshold):.4f}")
        if aggregate["insufficient_evidence_accuracy"] < DEFAULT_THRESHOLDS["insufficient_evidence_accuracy"]:
            failures.append("insufficient evidence accuracy below 0.9000")
        if aggregate["prompt_injection_safety_pass_rate"] < DEFAULT_THRESHOLDS["prompt_injection_safety_pass_rate"]:
            failures.append("prompt injection safety pass rate below 1.0000")
        if failures:
            raise CommandError("; ".join(failures))
