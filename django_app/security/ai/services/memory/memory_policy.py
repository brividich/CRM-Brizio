"""Policy helpers for approved operational AI memories."""

from ....models import AIMemoryFact


def get_approved_memory_facts(
    *,
    scope: str | None = None,
    category: str | None = None,
    limit: int = 10,
) -> list[AIMemoryFact]:
    queryset = AIMemoryFact.objects.filter(is_approved=True)
    if scope:
        queryset = queryset.filter(scope=scope)
    if category:
        queryset = queryset.filter(category=category)
    limit = max(1, min(int(limit or 10), 50))
    return list(queryset.order_by("scope", "category", "key")[:limit])


def serialize_memory_fact(fact: AIMemoryFact) -> dict:
    return {
        "id": fact.id,
        "scope": fact.scope,
        "key": fact.key,
        "value": fact.value,
        "category": fact.category,
        "confidence": fact.confidence,
        "is_approved": fact.is_approved,
        "source": fact.source,
        "source_object_type": fact.source_object_type,
        "source_object_id": fact.source_object_id,
        "metadata": fact.metadata,
    }
