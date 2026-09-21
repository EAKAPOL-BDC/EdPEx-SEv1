"""Escaped switchable copy. Submitted values are never translated."""
from django import template
from django.utils.html import format_html
register = template.Library()

@register.simple_tag
def review_text(value):
    th, separator, en = str(value).partition(' / ')
    if not separator:
        return value
    return format_html('<span class="review-th" lang="th">{}</span><span class="review-en" lang="en">{}</span>', th, en)
