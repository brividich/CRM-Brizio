from django.core.management.base import BaseCommand

from security.models import AIMemoryFact


DEFAULT_FACTS = [
    (
        "threatsync_low_closed_aggregation",
        "Gli eventi ThreatSync Low/Closed non generano alert singoli; vengono aggregati in KPI/report salvo anomalie di volume o concentrazione.",
        "watchguard",
    ),
    (
        "defender_critical_cve_remediation",
        "Le vulnerabilita Defender con severity Critical, CVSS >= 9.0 ed exposed_devices > 0 generano alert Critical, Evidence Container e ticket remediation deduplicato.",
        "defender",
    ),
    (
        "backup_positive_and_missing_policy",
        "I backup completati sono KPI positivi; fallimenti, backup mancanti o anomalie generano alert.",
        "backup",
    ),
    (
        "no_evidence_no_invention",
        "Se mancano evidenze interne sufficienti, l'AI deve dichiararlo e non inventare.",
        "safety",
    ),
]


class Command(BaseCommand):
    help = "Seed approved operational AI memory facts with synthetic project rules."

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for key, value, category in DEFAULT_FACTS:
            _, was_created = AIMemoryFact.objects.update_or_create(
                scope="global",
                key=key,
                category=category,
                defaults={
                    "value": value,
                    "confidence": 1.0,
                    "is_approved": True,
                    "source": "seed_ai_memory",
                    "metadata": {"seed": True},
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"AI memory facts seeded: {created} created, {updated} updated"))
