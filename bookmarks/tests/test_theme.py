from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from bookmarks.models import UserProfile
from bookmarks.tests.helpers import BookmarkFactoryMixin, HtmlTestMixin


class ThemeToggleTestCase(TestCase, BookmarkFactoryMixin, HtmlTestMixin):
    def setUp(self) -> None:
        self.user = self.get_or_create_test_user()
        self.client.force_login(self.user)

    def test_switch_to_dark(self):
        response = self.client.post(
            reverse("linkding:settings.theme"),
            {"theme": "dark", "return_url": reverse("linkding:bookmarks.archived")},
        )

        self.assertRedirects(response, reverse("linkding:bookmarks.archived"))
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.theme, UserProfile.THEME_DARK)

    def test_switch_to_light(self):
        self.user.profile.theme = UserProfile.THEME_DARK
        self.user.profile.save()

        self.client.post(reverse("linkding:settings.theme"), {"theme": "light"})

        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.theme, UserProfile.THEME_LIGHT)

    def test_rejects_invalid_theme(self):
        response = self.client.post(
            reverse("linkding:settings.theme"), {"theme": "auto"}
        )

        self.assertEqual(response.status_code, 400)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.theme, UserProfile.THEME_AUTO)

    def test_rejects_get(self):
        response = self.client.get(reverse("linkding:settings.theme"))

        self.assertEqual(response.status_code, 405)

    def test_ignores_unsafe_return_url(self):
        response = self.client.post(
            reverse("linkding:settings.theme"),
            {"theme": "dark", "return_url": "https://example.com"},
        )

        self.assertRedirects(response, reverse("linkding:bookmarks.index"))

    def test_requires_login(self):
        self.client.logout()

        response = self.client.post(
            reverse("linkding:settings.theme"), {"theme": "dark"}
        )

        self.assertRedirects(
            response,
            settings.LOGIN_URL + "?next=" + reverse("linkding:settings.theme"),
            fetch_redirect_response=False,
        )

    def test_toggle_is_rendered_in_nav(self):
        response = self.client.get(reverse("linkding:bookmarks.index"))
        soup = self.make_soup(response.content.decode())

        forms = soup.select("form.theme-toggle")
        # Desktop and mobile navigation
        self.assertEqual(len(forms), 2)
        form = forms[0]
        self.assertEqual(form["action"], reverse("linkding:settings.theme"))
        values = [button["value"] for button in form.select("button[name=theme]")]
        self.assertEqual(values, ["dark", "light"])
        return_url = form.select_one("input[name=return_url]")["value"]
        self.assertEqual(return_url, reverse("linkding:bookmarks.index"))


class ThemePaletteTestCase(TestCase, BookmarkFactoryMixin, HtmlTestMixin):
    def setUp(self) -> None:
        self.user = self.get_or_create_test_user()
        self.client.force_login(self.user)

    def get_stylesheets(self):
        response = self.client.get(reverse("linkding:bookmarks.index"))
        soup = self.make_soup(response.content.decode())
        return [
            link["href"].split("?")[0]
            for link in soup.select("head link[rel=stylesheet]")
        ]

    def set_profile(self, theme, palette):
        self.user.profile.theme = theme
        self.user.profile.theme_palette = palette
        self.user.profile.save()

    def test_default_palette(self):
        self.set_profile(UserProfile.THEME_AUTO, UserProfile.THEME_PALETTE_DEFAULT)

        self.assertEqual(
            self.get_stylesheets(),
            ["/static/theme-dark.css", "/static/theme-light.css"],
        )

    def test_rose_pine_palette_auto(self):
        self.set_profile(UserProfile.THEME_AUTO, UserProfile.THEME_PALETTE_ROSE_PINE)

        self.assertEqual(
            self.get_stylesheets(),
            ["/static/theme-rosepine-dark.css", "/static/theme-rosepine-light.css"],
        )

    def test_rose_pine_palette_light(self):
        self.set_profile(UserProfile.THEME_LIGHT, UserProfile.THEME_PALETTE_ROSE_PINE)

        self.assertEqual(self.get_stylesheets(), ["/static/theme-rosepine-light.css"])

    def test_rose_pine_palette_dark(self):
        self.set_profile(UserProfile.THEME_DARK, UserProfile.THEME_PALETTE_ROSE_PINE)

        self.assertEqual(self.get_stylesheets(), ["/static/theme-rosepine-dark.css"])

    def test_palette_can_be_changed_in_settings(self):
        response = self.client.get(reverse("linkding:settings.general"))
        soup = self.make_soup(response.content.decode())

        options = [
            option["value"] for option in soup.select("select#id_theme_palette option")
        ]
        self.assertEqual(options, ["default", "rose_pine"])
