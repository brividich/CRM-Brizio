"""Storage per i file statici.

``ForgivingManifestStaticFilesStorage`` evita che ``collectstatic`` fallisca per
i **sourcemap mancanti** referenziati dalle librerie vendored (``//# sourceMappingURL=*.map``):
in prod non spediamo i ``.map``, ma ``ManifestStaticFilesStorage`` prova comunque
a risolverli e solleva ``ValueError``. Qui il riferimento al ``.map`` assente viene
lasciato invariato; ogni ALTRO asset realmente mancante continua a far fallire la
build (nessuna perdita di rigore sui veri errori).
"""
from __future__ import annotations

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class ForgivingManifestStaticFilesStorage(ManifestStaticFilesStorage):
    def url_converter(self, name, hashed_files, template=None):
        base_converter = super().url_converter(name, hashed_files, template)

        def converter(matchobj):
            try:
                return base_converter(matchobj)
            except ValueError as exc:
                # Tollera SOLO i sourcemap mancanti; rilancia per qualsiasi altro
                # asset davvero assente (così un errore reale resta bloccante).
                if ".map" in str(exc):
                    return matchobj.group(0)
                raise

        return converter
