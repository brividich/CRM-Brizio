"""``{% dispense_del_corso corso %}``: riquadro con le dispense del corso che chi guarda può aprire."""
from django import template

register = template.Library()


@register.inclusion_tag("anagrafica/dispense/_riquadro.html", takes_context=True)
def dispense_del_corso(context, corso, stile="fmd"):
    request = context.get("request")
    voci = []
    if request is not None and corso is not None:
        try:
            from anagrafica.services import dispense as srv
            ctx = srv.Contesto.da_request(request)
            atts = list(srv.visibili(ctx).filter(corso=corso).order_by("tipo", "titolo", "pk"))
            letture = srv.letture_di(ctx.legacy_id, [a.pk for a in atts])
            voci = [srv.scheda(a, letture=letture) for a in atts]
        except Exception:
            voci = []
    return {"voci": voci, "corso": corso, "stile": stile}
