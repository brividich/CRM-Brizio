from django.core.management.base import BaseCommand

from security.ai.services.memory.document_indexer import _replace_chunks
from security.ai.services.memory.chunker import chunk_text
from security.ai.services.memory.embedding_indexer import rebuild_embeddings
from security.ai.services.memory.embedding_provider import get_embedding_provider
from security.ai.services.memory.embedding_diagnostics import (
    get_active_embedding_provider,
    is_embedding_provider_configured,
    is_pgvector_available,
)
from security.models import AIKnowledgeDocument, AIKnowledgeEmbedding


class Command(BaseCommand):
    help = "Rebuild AI memory chunks and embeddings with configurable providers."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simulate without writing")
        parser.add_argument("--source-type", default="", help="Filter by source type")
        parser.add_argument("--document-id", type=int, help="Filter by document ID")
        parser.add_argument("--reset-embeddings", action="store_true", help="Reset existing embeddings")
        parser.add_argument("--reset-chunks", action="store_true", help="Reset existing chunks")
        parser.add_argument("--batch-size", type=int, default=100, help="Batch size for processing")
        parser.add_argument(
            "--provider",
            default="deterministic_hash",
            help="Embedding provider (deterministic_hash, openai_compatible, nvidia_nim, local_http)",
        )
        parser.add_argument(
            "--mode",
            choices=["chunks", "embeddings", "all"],
            default="all",
            help="Operation mode",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Fail on provider errors instead of continuing",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit number of chunks to process",
        )

    def handle(self, *args, **options):
        provider_name = options["provider"]
        provider = get_embedding_provider(provider_name)
        configured = is_embedding_provider_configured()
        pgvector_available = is_pgvector_available()

        # Output provider information
        self.stdout.write(f"Provider: {provider.provider_name}")
        self.stdout.write(f"Model: {provider.model_name}")
        self.stdout.write(f"Dimensions: {provider.dimensions}")
        self.stdout.write(f"Configured: {configured}")
        self.stdout.write(f"pgvector available: {pgvector_available}")
        self.stdout.write(f"Dry run: {options['dry_run']}")
        self.stdout.write(f"Strict mode: {options['strict']}")
        self.stdout.write("")

        # Build queryset
        queryset = AIKnowledgeDocument.objects.order_by("id")
        if options["source_type"]:
            queryset = queryset.filter(source_type=options["source_type"])
        if options["document_id"]:
            queryset = queryset.filter(document_id=options["document_id"])

        counts = {
            "documents_seen": queryset.count(),
            "chunks_created": 0,
            "chunks_updated": 0,
            "embeddings_created": 0,
            "embeddings_updated": 0,
            "embeddings_skipped": 0,
            "provider_errors": 0,
            "rate_limit_hits": 0,
            "errors": 0,
            "duration_seconds": 0,
            "dry_run": options["dry_run"],
            "fallback_used": False,
        }

        import time

        start_time = time.time()

        if options["mode"] in {"chunks", "all"}:
            for document in queryset:
                try:
                    before = document.chunks.count()
                    if options["dry_run"]:
                        after = len(chunk_text(document.raw_text))
                        counts["chunks_created"] += max(0, after - before)
                        counts["chunks_updated"] += min(before, after)
                    elif options["reset_chunks"]:
                        _replace_chunks(document, document.raw_text)
                        after = document.chunks.count()
                        counts["chunks_created"] += max(0, after - before)
                        counts["chunks_updated"] += min(before, after)
                    else:
                        counts["chunks_skipped"] = counts.get("chunks_skipped", 0) + before
                except Exception as e:
                    counts["errors"] += 1
                    self.stderr.write(f"Error processing document {document.id}: {str(e)[:200]}")

        if options["mode"] in {"embeddings", "all"}:
            if options["reset_embeddings"] and not options["dry_run"]:
                embedding_queryset = AIKnowledgeEmbedding.objects.filter(chunk__document__in=queryset)
                embedding_queryset.delete()

            embedding_stats = rebuild_embeddings(
                provider_name=provider_name,
                dry_run=options["dry_run"],
                source_type=options["source_type"] or None,
                document_id=options["document_id"],
                reset_embeddings=False,
                batch_size=options["batch_size"],
                limit=options.get("limit"),
                strict=options["strict"],
            )
            counts["embeddings_created"] += embedding_stats.embeddings_created
            counts["embeddings_updated"] += embedding_stats.embeddings_updated
            counts["embeddings_skipped"] += embedding_stats.embeddings_skipped
            counts["provider_errors"] += embedding_stats.provider_errors
            counts["rate_limit_hits"] += embedding_stats.rate_limit_hits
            counts["errors"] += embedding_stats.errors

        counts["duration_seconds"] = time.time() - start_time

        # Output results
        self.stdout.write("")
        self.stdout.write("Results:")
        for key in [
            "documents_seen",
            "chunks_created",
            "chunks_updated",
            "embeddings_created",
            "embeddings_updated",
            "embeddings_skipped",
            "provider_errors",
            "rate_limit_hits",
            "errors",
            "duration_seconds",
            "dry_run",
            "fallback_used",
        ]:
            value = counts.get(key, 0)
            if key == "duration_seconds":
                self.stdout.write(f"{key}: {value:.2f}")
            elif key in ("dry_run", "fallback_used"):
                self.stdout.write(f"{key}: {value}")
            else:
                self.stdout.write(f"{key}: {value}")
