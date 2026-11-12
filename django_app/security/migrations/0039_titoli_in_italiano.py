"""Titoli di alert e ticket già salvati: dai testi inglesi generati dal motore a quelli italiani.

Il motore delle regole e il ticketing scrivevano titoli in inglese («Source silent: …»,
«Remediate … on …»). Da questa versione li scrivono in italiano; qui si traducono quelli
già salvati, con gli stessi testi. Nessun codice dipende dal testo dei titoli (dedup su
``dedup_hash``). Il ritorno indietro non fa nulla: i titoli italiani restano.
"""
import re

from django.db import migrations
from django.db.models import Q

# (prefisso per la ricerca, espressione, sostituzione)
REGOLE = [
    ("Critical exposed vulnerability ", re.compile(r"^Critical exposed vulnerability (\S+) on (.+)$"), r"Vulnerabilità critica esposta \1 su \2"),
    ("Critical exposed vulnerability ", re.compile(r"^Critical exposed vulnerability (.+)$"), r"Vulnerabilità critica esposta \1"),
    ("Source silent: ", re.compile(r"^Source silent: (.*)$"), r"Sorgente silenziosa: \1"),
    ("Possible sender spoofing: ", re.compile(r"^Possible sender spoofing: (.*) report from (.*)$"), r"Possibile mittente falso: report \1 da \2"),
    ("Possible sender spoofing: ", re.compile(r"^Possible sender spoofing: (.*)$"), r"Possibile mittente falso: \1"),
    ("Unreadable vulnerability data for ", re.compile(r"^Unreadable vulnerability data for (.*) \(manual review\)$"),
     r"Dati della vulnerabilità illeggibili per \1 (verifica manuale)"),
    ("Unreadable vulnerability data for ", re.compile(r"^Unreadable vulnerability data for (\S+) on (.+)$"), r"Dati della vulnerabilità illeggibili per \1 su \2"),
    ("Unreadable vulnerability data for ", re.compile(r"^Unreadable vulnerability data for (.*)$"), r"Dati della vulnerabilità illeggibili per \1"),
    ("Backup job requires attention: ", re.compile(r"^Backup job requires attention: (.*)$"), r"Backup da controllare: \1"),
    ("VPN authentication spike detected", re.compile(r"^VPN authentication spike detected$"), "Picco di autenticazioni VPN"),
    ("WatchGuard alert candidate", re.compile(r"^WatchGuard alert candidate$"), "Alert WatchGuard da verificare"),
    ("Remediate ", re.compile(r"^Remediate (\d+) critical CVEs on (.*)$"), r"Correggere \1 CVE critiche su \2"),
    ("Remediate ", re.compile(r"^Remediate critical CVE on (.*)$"), r"Correggere CVE critica su \1"),
    ("Remediate ", re.compile(r"^Remediate (\S+) on (.*)$"), r"Correggere \1 su \2"),
    ("Investigate backup issue: ", re.compile(r"^Investigate backup issue: (.*)$"), r"Verificare il problema di backup: \1"),
]
PREFISSI = sorted({prefisso for prefisso, _re, _sost in REGOLE})


def traduci(titolo):
    for _prefisso, espressione, sostituzione in REGOLE:
        if espressione.match(titolo or ""):
            return espressione.sub(sostituzione, titolo, count=1)[:255]
    return titolo


def avanti(apps, schema_editor):
    filtro = Q()
    for prefisso in PREFISSI:
        filtro |= Q(title__startswith=prefisso)
    for nome in ("SecurityAlert", "SecurityRemediationTicket"):
        modello = apps.get_model("security", nome)
        for pk, titolo in modello.objects.filter(filtro).values_list("pk", "title").iterator():
            nuovo = traduci(titolo)
            if nuovo != titolo:
                modello.objects.filter(pk=pk).update(title=nuovo)


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0038_caso_attivita_cve_host"),
    ]

    operations = [
        migrations.RunPython(avanti, migrations.RunPython.noop),
    ]
