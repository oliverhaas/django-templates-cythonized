"""End-to-end admin view rendering: stock Django vs cythonized engine.

Renders actual Django admin pages with both template backends via the Django
test client and asserts identical HTML output. This catches subtle
incompatibilities in template inheritance, custom templatetags, context
processors, and the full request/response cycle that unit tests miss.
"""

import os
import re

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

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

# CSRF tokens are random per-request — normalize before comparison.
_CSRF_RE = re.compile(r'value="[A-Za-z0-9]{32,}"')


def _normalize(html):
    """Remove non-deterministic content from admin HTML."""
    return _CSRF_RE.sub('value="CSRF"', html)


class TestAdminRender(TestCase):
    """Compare admin view HTML between stock Django and cythonized engine."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username="admin", password="secret", email="admin@example.com"
        )

    def _get(self, url):
        """GET a URL with both engines and assert identical output."""
        with override_settings(TEMPLATES=STOCK_TEMPLATES):
            self.client.force_login(self.superuser)
            stock_resp = self.client.get(url)
        with override_settings(TEMPLATES=CYTH_TEMPLATES):
            self.client.force_login(self.superuser)
            cyth_resp = self.client.get(url)

        self.assertEqual(
            stock_resp.status_code,
            cyth_resp.status_code,
            f"Status mismatch for {url}: stock={stock_resp.status_code}, "
            f"cyth={cyth_resp.status_code}",
        )

        stock_html = _normalize(stock_resp.content.decode())
        cyth_html = _normalize(cyth_resp.content.decode())

        if stock_html != cyth_html:
            # Find first difference for a useful error message.
            for i, (a, b) in enumerate(zip(stock_html, cyth_html)):
                if a != b:
                    ctx = 80
                    start = max(0, i - ctx)
                    self.fail(
                        f"HTML mismatch at char {i} for {url}:\n"
                        f"  stock: ...{stock_html[start:i+ctx]!r}...\n"
                        f"  cyth:  ...{cyth_html[start:i+ctx]!r}..."
                    )
            # Different lengths
            self.assertEqual(len(stock_html), len(cyth_html),
                             f"HTML length mismatch for {url}")

        return stock_resp.status_code

    # --- Unauthenticated ---

    def test_login_page(self):
        """Admin login page renders identically."""
        with override_settings(TEMPLATES=STOCK_TEMPLATES):
            stock_resp = self.client.get("/admin/login/")
        with override_settings(TEMPLATES=CYTH_TEMPLATES):
            cyth_resp = self.client.get("/admin/login/")

        stock_html = _normalize(stock_resp.content.decode())
        cyth_html = _normalize(cyth_resp.content.decode())
        self.assertEqual(stock_html, cyth_html)

    # --- Admin index / app list ---

    def test_admin_index(self):
        """Admin dashboard with app list and recent actions."""
        self._get("/admin/")

    def test_app_index(self):
        """Auth app model list."""
        self._get("/admin/auth/")

    # --- User admin (complex: custom UserAdmin, fieldsets, filters) ---

    def test_user_changelist(self):
        """User list view with table, filters, search."""
        self._get("/admin/auth/user/")

    def test_user_add_form(self):
        """User creation form (custom two-step add)."""
        self._get("/admin/auth/user/add/")

    def test_user_change_form(self):
        """User edit form with populated data and fieldsets."""
        self._get(f"/admin/auth/user/{self.superuser.pk}/change/")

    def test_user_changelist_search(self):
        """User list filtered by search query."""
        self._get("/admin/auth/user/?q=admin")

    def test_user_changelist_filter(self):
        """User list filtered by is_staff."""
        self._get("/admin/auth/user/?is_staff__exact=1")

    def test_user_delete_confirmation(self):
        """Delete confirmation page with related objects summary."""
        victim = User.objects.create_user("victim", "v@example.com", "pass")
        self._get(f"/admin/auth/user/{victim.pk}/delete/")

    def test_user_password_change(self):
        """Custom password change form."""
        self._get(f"/admin/auth/user/{self.superuser.pk}/password/")

    # --- Group admin (simpler, but has M2M permissions widget) ---

    def test_group_changelist_empty(self):
        """Group list with no groups (empty state)."""
        self._get("/admin/auth/group/")

    def test_group_add_form(self):
        """Group creation form with M2M permissions widget."""
        self._get("/admin/auth/group/add/")

    # --- Edge cases ---

    def test_nonexistent_object_redirects(self):
        """Non-existent object returns redirect (302) identically."""
        with override_settings(TEMPLATES=STOCK_TEMPLATES):
            self.client.force_login(self.superuser)
            stock_resp = self.client.get("/admin/auth/user/99999/change/")
        with override_settings(TEMPLATES=CYTH_TEMPLATES):
            self.client.force_login(self.superuser)
            cyth_resp = self.client.get("/admin/auth/user/99999/change/")
        # Django admin redirects to changelist for nonexistent objects
        self.assertEqual(stock_resp.status_code, cyth_resp.status_code)
