"""Driver delle CNC: l'unico punto in cui il collector tocca una libreria che parla con la macchina.

Ogni driver avvolge la libreria in un ``ProxySolaLettura`` (``base.py``) che espone solo un insieme
chiuso di metodi di lettura: qualunque altro accesso solleva ``PermissionError``. I nomi delle
funzioni di scrittura che non devono mai comparire in questo package sono in ``../vietati.py``,
verificati da un test statico.
"""
