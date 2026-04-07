#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def _default_settings_module(argv: list[str]) -> str:
    if any(arg == "--settings" or arg.startswith("--settings=") for arg in argv[1:]):
        return "config.settings.dev"
    if len(argv) > 1 and argv[1] == "test":
        return "config.settings.test"
    return "config.settings.dev"


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", _default_settings_module(sys.argv))
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
