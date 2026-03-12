from django import template


register = template.Library()


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        return None


# Alias usato nel template utente_edit.html
dictlookup = register.filter("dictlookup", get_item)

