"""End-to-end admin view rendering: stock Django vs cythonized engine.

Renders actual Django admin pages with both template backends via the Django
test client and asserts identical HTML output.
"""

import os
import re

import pytest
from django.contrib.auth.models import Group, User
from django.test import override_settings

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_CONTEXT_PROCESSORS = [
    "django.template.context_processors.request",
    "django.contrib.auth.context_processors.auth",
    "django.contrib.messages.context_processors.messages",
]

STOCK_TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": _CONTEXT_PROCESSORS,
        },
    },
]

CYTH_TEMPLATES = [
    {
        "BACKEND": "django_templates_cythonized.backend.CythonizedTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": _CONTEXT_PROCESSORS,
        },
    },
]

# Non-deterministic content — normalize before comparison.
_CSRF_RE = re.compile(r'value="[A-Za-z0-9]{32,}"')
_TIME_RE = re.compile(r'value="\d{2}:\d{2}:\d{2}"')


def _normalize(html):
    """Remove non-deterministic content from admin HTML."""
    html = _CSRF_RE.sub('value="CSRF"', html)
    return _TIME_RE.sub('value="TIME"', html)


def _assert_admin_html(client, url, *, follow=False):
    """GET a URL with both engines and assert identical output."""
    with override_settings(TEMPLATES=STOCK_TEMPLATES):
        stock_resp = client.get(url, follow=follow)
    with override_settings(TEMPLATES=CYTH_TEMPLATES):
        cyth_resp = client.get(url, follow=follow)

    assert stock_resp.status_code == cyth_resp.status_code, (
        f"Status mismatch for {url}: stock={stock_resp.status_code}, cyth={cyth_resp.status_code}"
    )

    stock_html = _normalize(stock_resp.content.decode())
    cyth_html = _normalize(cyth_resp.content.decode())

    if stock_html != cyth_html:
        for i, (a, b) in enumerate(zip(stock_html, cyth_html)):
            if a != b:
                ctx = 80
                start = max(0, i - ctx)
                pytest.fail(
                    f"HTML mismatch at char {i} for {url}:\n"
                    f"  stock: ...{stock_html[start : i + ctx]!r}...\n"
                    f"  cyth:  ...{cyth_html[start : i + ctx]!r}...",
                )
        assert len(stock_html) == len(cyth_html), f"HTML length mismatch for {url}"


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="secret", email="admin@example.com")


@pytest.fixture
def admin_client(client, superuser):
    client.force_login(superuser)
    return client


# --- Unauthenticated ---


@pytest.mark.django_db
def test_login_page(client):
    """Admin login page renders identically."""
    _assert_admin_html(client, "/admin/login/")


# --- Admin index / app list ---


def test_admin_index(admin_client):
    """Admin dashboard with app list and recent actions."""
    _assert_admin_html(admin_client, "/admin/")


def test_app_index(admin_client):
    """Auth app model list."""
    _assert_admin_html(admin_client, "/admin/auth/")


# --- User admin (complex: custom UserAdmin, fieldsets, filters) ---


def test_user_changelist(admin_client):
    """User list view with table, filters, search."""
    _assert_admin_html(admin_client, "/admin/auth/user/")


def test_user_add_form(admin_client):
    """User creation form (custom two-step add)."""
    _assert_admin_html(admin_client, "/admin/auth/user/add/")


def test_user_change_form(admin_client, superuser):
    """User edit form with populated data and fieldsets."""
    _assert_admin_html(admin_client, f"/admin/auth/user/{superuser.pk}/change/")


def test_user_changelist_search(admin_client):
    """User list filtered by search query."""
    _assert_admin_html(admin_client, "/admin/auth/user/?q=admin")


def test_user_changelist_filter(admin_client):
    """User list filtered by is_staff."""
    _assert_admin_html(admin_client, "/admin/auth/user/?is_staff__exact=1")


def test_user_delete_confirmation(admin_client):
    """Delete confirmation page with related objects summary."""
    victim = User.objects.create_user("victim", "v@example.com", "pass")
    _assert_admin_html(admin_client, f"/admin/auth/user/{victim.pk}/delete/")


def test_user_password_change(admin_client, superuser):
    """Custom password change form."""
    _assert_admin_html(admin_client, f"/admin/auth/user/{superuser.pk}/password/")


def test_user_history(admin_client, superuser):
    """Object history page."""
    _assert_admin_html(admin_client, f"/admin/auth/user/{superuser.pk}/history/")


# --- Group admin (simpler, but has M2M permissions widget) ---


def test_group_changelist_empty(admin_client):
    """Group list with no groups (empty state)."""
    _assert_admin_html(admin_client, "/admin/auth/group/")


def test_group_add_form(admin_client):
    """Group creation form with M2M permissions widget."""
    _assert_admin_html(admin_client, "/admin/auth/group/add/")


def test_group_change_form(admin_client):
    """Group edit form with M2M permissions widget populated."""
    group = Group.objects.create(name="editors")
    _assert_admin_html(admin_client, f"/admin/auth/group/{group.pk}/change/")


def test_group_delete_confirmation(admin_client):
    """Group delete confirmation."""
    group = Group.objects.create(name="to-delete")
    _assert_admin_html(admin_client, f"/admin/auth/group/{group.pk}/delete/")


# --- Sorting and pagination ---


def test_user_changelist_sorted(admin_client):
    """User list sorted by username column."""
    _assert_admin_html(admin_client, "/admin/auth/user/?o=1")


# --- Auth views ---


def test_logout(admin_client):
    """Logout page renders identically."""
    _assert_admin_html(admin_client, "/admin/logout/")


def test_password_change_own(admin_client):
    """Logged-in user's own password change form."""
    _assert_admin_html(admin_client, "/admin/password_change/")


# --- Edge cases ---


def test_nonexistent_object_redirects(admin_client):
    """Non-existent object returns redirect (302) identically."""
    with override_settings(TEMPLATES=STOCK_TEMPLATES):
        stock_resp = admin_client.get("/admin/auth/user/99999/change/")
    with override_settings(TEMPLATES=CYTH_TEMPLATES):
        cyth_resp = admin_client.get("/admin/auth/user/99999/change/")
    assert stock_resp.status_code == cyth_resp.status_code
