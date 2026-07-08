"""Modelli del modulo Suggestion Corner (SMS — Sistema di Miglioramento/Segnalazione).

Vedi docs/superpowers/specs/2026-07-08-suggestion-corner-design.md e
docs/BUILD_SPEC_suggestion_corner.md.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django_fsm import FSMField
