from __future__ import annotations

from django import template
from django.utils.html import format_html

from core.icon_utils import (
    icon_looks_like_image,
    icon_text_or_fallback,
    render_semantic_icon,
    resolve_icon_src,
    resolve_semantic_icon_name,
)


register = template.Library()


@register.simple_tag
def render_icon(value, fallback: str = "", img_class: str = "ui-icon-img"):
    if icon_looks_like_image(value):
        src = resolve_icon_src(value)
        if src:
            return format_html('<img src="{}" alt="" class="{}" loading="lazy">', src, img_class)
    semantic_icon = resolve_semantic_icon_name(value, fallback)
    if semantic_icon:
        return render_semantic_icon(semantic_icon)
    return format_html("{}", icon_text_or_fallback(value, fallback))
