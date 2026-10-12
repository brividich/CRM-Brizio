"""Fasce d'età sui tipi di visita, esito «Eseguito», referti di laboratorio.

Configurazione iniziale dell'oculistica videoterminalisti (D.Lgs. 81/08 art. 176
c.3: quinquennale, biennale dai 50 anni): solo se a catalogo esistono ENTRAMBI i
tipi «...oculistic... terminalist... (quinquennale)» e «(biennale)», e solo sui
campi vuoti. Prima i due tipi non erano nella stessa famiglia e la biennale
veniva ignorata: chi ha superato i 50 anni risultava in regola fino alla scadenza
quinquennale. Nessuna visita viene toccata: le scadenze le ricalcola il motore
dei requisiti dopo la migrazione.
"""
import re
import unicodedata

import django.core.validators
from django.db import migrations, models

CATEGORIA_VDT = "Oculistica videoterminalisti"


def _norm(testo: str) -> str:
    testo = unicodedata.normalize("NFKD", testo or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", testo).strip().lower()


def configura_oculistica_vdt(apps, schema_editor):
    Tipo = apps.get_model("anagrafica", "TipoVisitaMedica")
    quinq, bien = [], []
    for tipo in Tipo.objects.all():
        nome = _norm(tipo.nome)
        if "oculist" not in nome or not ("terminalist" in nome or "vdt" in nome):
            continue
        if "quinquennal" in nome:
            quinq.append(tipo)
        elif "biennal" in nome:
            bien.append(tipo)
    if len(quinq) != 1 or len(bien) != 1:
        return  # assenti o ambigui: si configura a mano da Impostazioni
    q, b = quinq[0], bien[0]
    categorie = {t.categoria.strip() for t in (q, b) if (t.categoria or "").strip()}
    if len(categorie) > 1:
        return  # gia' in famiglie diverse per scelta: non si forza
    categoria = categorie.pop() if categorie else CATEGORIA_VDT
    if q.eta_minima is None and q.eta_massima is None:
        q.eta_massima = 49
    if b.eta_minima is None and b.eta_massima is None:
        b.eta_minima = 50
    for t in (q, b):
        t.categoria = t.categoria or categoria
        t.save(update_fields=["categoria", "eta_minima", "eta_massima"])
    print(f"\n  anagrafica 0166: «{q.nome}» fino a {q.eta_massima} anni, «{b.nome}» dai "
          f"{b.eta_minima} anni, famiglia «{categoria}».")


class Migration(migrations.Migration):

    dependencies = [
        ('anagrafica', '0166_visite_robustezza'),
    ]

    operations = [
        migrations.AddField(
            model_name='tipovisitamedica',
            name='eta_massima',
            field=models.PositiveSmallIntegerField(blank=True, help_text='Età fino a cui vale questo tipo (compresa). Vuoto = nessun limite.', null=True, validators=[django.core.validators.MaxValueValidator(120)]),
        ),
        migrations.AddField(
            model_name='tipovisitamedica',
            name='eta_minima',
            field=models.PositiveSmallIntegerField(blank=True, help_text='Età da cui vale questo tipo (compresa). Vuoto = nessun limite.', null=True, validators=[django.core.validators.MaxValueValidator(120)]),
        ),
        migrations.AlterField(
            model_name='refertointakeriga',
            name='tipo_referto',
            field=models.CharField(choices=[('IDONEITA', 'Certificato di idoneità'), ('OCULISTICA', 'Certificato oculistico'), ('ESAMI', 'Referto esami di laboratorio')], default='IDONEITA', help_text='Certificato di idoneità (stampato, letto per intero), certificato oculistico (data, nome ed esito scritti a mano: si completano in coda) o referto di laboratorio (esami ematici: tipo e data si confermano in coda).', max_length=12),
        ),
        migrations.AlterField(
            model_name='visitamedica',
            name='esito',
            field=models.CharField(choices=[('IDONEO', 'Idoneo'), ('IDONEO_MANS', 'Idoneo mansione specifica'), ('IDONEO_PRESCR', 'Idoneo con prescrizioni'), ('IDONEO_LIM', 'Idoneo con limitazioni'), ('IDONEO_LIM_PRESCR', 'Idoneo con limitazioni e prescrizioni'), ('NON_IDONEO_TEMP', 'Non idoneo (temporaneo)'), ('NON_IDONEO_DEF', 'Non idoneo (definitivo)'), ('ESEGUITO', 'Eseguito (accertamento senza giudizio)')], default='IDONEO', max_length=20),
        ),
        migrations.RunPython(configura_oculistica_vdt, migrations.RunPython.noop),
    ]
