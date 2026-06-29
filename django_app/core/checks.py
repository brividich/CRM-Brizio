"""System check di igiene runtime, registrati da ``core.apps.CoreConfig.ready``.

Nati da due incidenti reali (2026-06-29):
- chiavi ``.env`` duplicate che shadoano silenziosamente il valore giusto
  (il loader tiene l'ULTIMA occorrenza nel file) -> ore di debug;
- ``MAX_ENTRIES`` del DatabaseCache < numero di chunk RAG -> gli embedding
  vengono cullati e ricalcolati ad ogni rebuild dell'indice (TTFT chat ~95s).

Entrambi sono economici (lettura file / lettura settings) e girano a ogni
``manage.py check`` e all'avvio.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.checks import Error, Warning, register


def _duplicate_env_keys(path: Path) -> dict[str, list[int]]:
    """Chiavi presenti su piu' righe nello stesso file .env.

    Il loader (`config.env_config.load_env_file_values`) costruisce un dict riga
    per riga: a parita' di chiave vince l'ULTIMA occorrenza, in silenzio. Un vecchio
    valore in alto puo' cosi' shadoware quello corretto aggiunto in fondo.
    """
    occurrences: dict[str, list[int]] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}
    for i, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            occurrences.setdefault(key, []).append(i)
    return {k: v for k, v in occurrences.items() if len(v) > 1}


@register()
def check_env_no_duplicate_keys(app_configs, **kwargs):
    """Fallisce se un file .env runtime contiene la stessa chiave su piu' righe."""
    errors: list[Error] = []
    try:
        from config.env_config import iter_runtime_env_paths
    except Exception:
        return errors

    seen: set[str] = set()
    for path in iter_runtime_env_paths():
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key in seen or not path.exists():
            continue
        seen.add(key)
        for env_key, line_nos in sorted(_duplicate_env_keys(path).items()):
            errors.append(
                Error(
                    f"Chiave .env duplicata '{env_key}' in {path} (righe {line_nos}).",
                    hint=(
                        "Il loader tiene l'ULTIMA occorrenza nel file: un vecchio valore in "
                        "alto puo' shadoware quello giusto. Lascia una sola riga per chiave."
                    ),
                    id="core.E001",
                )
            )
    return errors


@register()
def check_rag_cache_sizing(app_configs, **kwargs):
    """Avvisa se gli embeddings sono attivi ma il DatabaseCache e' troppo piccolo.

    Gli embedding del RAG (~1 per chunk: migliaia col corpus SGI) vivono nel cache
    ``default``. Se ``MAX_ENTRIES`` e' inferiore al numero di chunk, il culling li
    sfratta e ogni rebuild dell'indice li ricalcola via TEI (latenza alta in chat).
    """
    warnings: list[Warning] = []
    if not bool(getattr(settings, "OLLAMA_EMBED_ENABLED", False)):
        return warnings
    default_cache = (getattr(settings, "CACHES", {}) or {}).get("default", {}) or {}
    if "DatabaseCache" not in str(default_cache.get("BACKEND", "")):
        return warnings
    options = default_cache.get("OPTIONS", {}) or {}
    try:
        max_entries = int(options.get("MAX_ENTRIES", 300) or 300)
    except (TypeError, ValueError):
        max_entries = 300
    # Pavimento prudente: il corpus SGI da solo e' ~10k chunk.
    floor = 20000
    if max_entries < floor:
        warnings.append(
            Warning(
                f"OLLAMA_EMBED_ENABLED attivo ma DatabaseCache MAX_ENTRIES={max_entries} "
                f"e' basso (consigliato >= {floor}).",
                hint=(
                    "Gli embedding (~1 per chunk RAG) vivono nella cache: se MAX_ENTRIES < "
                    "numero di chunk vengono cullati e ogni rebuild indice li ricalcola "
                    "(TTFT chat alto). Alza DJANGO_CACHE_MAX_ENTRIES."
                ),
                id="core.W001",
            )
        )
    return warnings
