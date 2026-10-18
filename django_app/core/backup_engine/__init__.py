"""Motore di backup verificabile di NOVICROM HUB (BUILD_SPEC R1).

Ogni backup è un *set* con manifest versionato, artefatti con SHA-256, verifica
(`RESTORE VERIFYONLY`), stato leggibile anche a DB spento e retention GFS.

Moduli: ``config`` (impostazioni), ``sqlserver`` (sqlcmd), ``transfer`` (copia
verificata), ``files`` (store content-addressed), ``host_manifest`` (macchina),
``manifest`` (schema), ``retention`` (GFS), ``status`` (file di stato), ``engine``
(orchestrazione usata da ``manage.py hub_backup``).
"""
