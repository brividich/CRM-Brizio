from __future__ import annotations

from django.conf import settings
from django.test.runner import DiscoverRunner


class NovicromDiscoverRunner(DiscoverRunner):
    """Use the release-suite labels when test discovery is invoked bare."""

    def build_suite(self, test_labels=None, **kwargs):
        if not test_labels:
            test_labels = list(getattr(settings, "DEFAULT_TEST_LABELS", ()))
        return super().build_suite(test_labels, **kwargs)
