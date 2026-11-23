"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
# Processo web (Waitress dietro IIS): i settings ne derivano il timeout delle query.
os.environ.setdefault("HUB_PROCESS_ROLE", "web")

application = get_wsgi_application()

# Rotte, cancelli del sottomenu e template pronti prima della prima richiesta: con più
# processi IIS ognuno pagava questo costo sui primi utenti (core/avvio.py).
try:
    from core.avvio import riscalda

    riscalda()
except Exception:  # noqa: BLE001 - il riscaldamento non deve mai fermare l'avvio
    pass
