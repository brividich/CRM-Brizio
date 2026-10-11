from django.conf import settings
from django.db import models


class ReportCorrection(models.Model):
    """Append-only revisions: restoring the source adds a revision, never deletes history."""

    report_slug = models.SlugField(max_length=80)
    scope = models.CharField(max_length=64)
    scope_params = models.JSONField(default=dict)
    target = models.CharField(max_length=64)
    target_label = models.CharField(max_length=500)
    revision = models.PositiveIntegerField()
    source_value = models.TextField(blank=True)
    value = models.TextField(blank=True)
    reason = models.TextField()
    restored = models.BooleanField(default=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    author_label = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(
            fields=["report_slug", "scope", "target", "revision"], name="rc_correction_revision_unique",
        )]
