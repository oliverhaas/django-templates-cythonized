"""Custom template tags for testing — simulates what a real user would write."""

from django import template
from django.utils.html import format_html

register = template.Library()


# --- simple_tag: basic, with args, with takes_context ---


@register.simple_tag
def greeting(name):
    """Simple tag that returns a greeting string."""
    return f"Hello, {name}!"


@register.simple_tag
def add_numbers(a, b):
    """Simple tag with multiple arguments."""
    return a + b


@register.simple_tag(takes_context=True)
def current_user_greeting(context):
    """Simple tag that reads from the template context."""
    user = context.get("user_name", "Anonymous")
    return f"Welcome back, {user}"


@register.simple_tag
def format_price(amount, currency="$"):
    """Simple tag with a keyword argument."""
    return f"{currency}{amount:.2f}"


# --- inclusion_tag ---


@register.inclusion_tag("_badge.html")
def badge(label, kind="info"):
    """Inclusion tag that renders a badge template."""
    return {"label": label, "kind": kind}


@register.inclusion_tag("_user_card.html", takes_context=True)
def user_card(context):
    """Inclusion tag that reads from context."""
    return {
        "user_name": context.get("user_name", "Anonymous"),
        "role": context.get("role", "guest"),
    }


# --- Custom Node subclass (manual tag parsing) ---


class RepeatNode(template.Node):
    """Repeats its contents N times: {% repeat N %}...{% endrepeat %}"""

    def __init__(self, count_expr, nodelist):
        self.count_expr = count_expr
        self.nodelist = nodelist

    def render(self, context):
        count = self.count_expr.resolve(context)
        parts = []
        for _ in range(int(count)):
            parts.append(self.nodelist.render(context))
        return "".join(parts)


@register.tag("repeat")
def do_repeat(parser, token):
    bits = token.split_contents()
    if len(bits) != 2:
        raise template.TemplateSyntaxError(f"'repeat' tag requires one argument, got {len(bits) - 1}")
    count_expr = parser.compile_filter(bits[1])
    nodelist = parser.parse(("endrepeat",))
    parser.delete_first_token()
    return RepeatNode(count_expr, nodelist)


# --- Another custom Node: {% upper %}...{% endupper %} ---


class UpperNode(template.Node):
    """Uppercases all content: {% upper %}...{% endupper %}"""

    def __init__(self, nodelist):
        self.nodelist = nodelist

    def render(self, context):
        output = self.nodelist.render(context)
        return output.upper()


@register.tag("upper")
def do_upper(parser, token):
    nodelist = parser.parse(("endupper",))
    parser.delete_first_token()
    return UpperNode(nodelist)
