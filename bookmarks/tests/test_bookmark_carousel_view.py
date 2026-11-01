from django.test import TestCase
from django.urls import reverse

from bookmarks.models import UserProfile
from bookmarks.tests.helpers import BookmarkFactoryMixin, HtmlTestMixin


class BookmarkCarouselViewTestCase(TestCase, BookmarkFactoryMixin, HtmlTestMixin):
    def setUp(self) -> None:
        self.user = self.get_or_create_test_user()
        self.client.force_login(self.user)

    def set_carousel_view(self):
        self.user.profile.bookmark_view_mode = UserProfile.BOOKMARK_VIEW_MODE_CAROUSEL
        self.user.profile.save()

    def get_soup(self, url="bookmarks.index", query=""):
        response = self.client.get(reverse(f"linkding:{url}") + query)
        return self.make_soup(response.content.decode())

    def get_groups(self, soup):
        groups = {}
        for group in soup.select(".bookmark-carousels .carousel-group"):
            name = group.select_one(".carousel-header h2 a").text.strip()
            ids = [li["data-bookmark-id"] for li in group.select("ul.carousel > li")]
            groups[name] = ids
        return groups

    def test_switch_to_carousel_persists_for_user(self):
        response = self.client.post(
            reverse("linkding:bookmarks.view_mode"), {"view_mode": "carousel"}
        )

        self.assertRedirects(response, reverse("linkding:bookmarks.index"))
        self.user.profile.refresh_from_db()
        self.assertEqual(
            self.user.profile.bookmark_view_mode,
            UserProfile.BOOKMARK_VIEW_MODE_CAROUSEL,
        )

    def test_list_view_does_not_render_carousels(self):
        self.setup_bookmark()

        soup = self.get_soup()

        self.assertIsNone(soup.select_one(".bookmark-carousels"))
        self.assertEqual(len(soup.select("ul.bookmark-list > li")), 1)

    def test_groups_bookmarks_by_tag(self):
        self.set_carousel_view()
        python = self.setup_tag(name="python")
        web = self.setup_tag(name="Web")
        both = self.setup_bookmark(tags=[python, web])
        only_python = self.setup_bookmark(tags=[python])
        untagged = self.setup_bookmark()

        groups = self.get_groups(self.get_soup())

        self.assertEqual(list(groups.keys()), ["#python", "#Web", "Untagged"])
        self.assertCountEqual(groups["#python"], [str(both.id), str(only_python.id)])
        self.assertEqual(groups["#Web"], [str(both.id)])
        self.assertEqual(groups["Untagged"], [str(untagged.id)])

    def test_omits_untagged_group_when_all_bookmarks_are_tagged(self):
        self.set_carousel_view()
        self.setup_bookmark(tags=[self.setup_tag(name="python")])

        groups = self.get_groups(self.get_soup())

        self.assertEqual(list(groups.keys()), ["#python"])

    def test_only_groups_bookmarks_of_current_page(self):
        self.set_carousel_view()
        self.user.profile.items_per_page = 2
        self.user.profile.save()
        tag = self.setup_tag(name="python")
        for _ in range(3):
            self.setup_bookmark(tags=[tag])

        soup = self.get_soup()

        self.assertEqual(len(self.get_groups(soup)["#python"]), 2)
        self.assertIsNotNone(soup.select_one(".bookmark-pagination"))

    def test_carousels_on_archived_page(self):
        self.set_carousel_view()
        self.setup_bookmark(is_archived=True, tags=[self.setup_tag(name="old")])

        groups = self.get_groups(self.get_soup("bookmarks.archived"))

        self.assertEqual(list(groups.keys()), ["#old"])

    def test_carousel_toggle_is_active(self):
        self.set_carousel_view()
        self.setup_bookmark()

        soup = self.get_soup()

        active = soup.select(".view-mode-toggle button.active")
        self.assertEqual([button["value"] for button in active], ["carousel"])

    def test_bulk_action_handles_bookmark_submitted_once_per_tag(self):
        self.set_carousel_view()
        bookmark = self.setup_bookmark(
            tags=[self.setup_tag(name="a"), self.setup_tag(name="b")]
        )

        self.client.post(
            reverse("linkding:bookmarks.index.action"),
            {
                "bulk_action": "bulk_archive",
                "bulk_execute": [""],
                "bookmark_id": [str(bookmark.id), str(bookmark.id)],
            },
        )

        bookmark.refresh_from_db()
        self.assertTrue(bookmark.is_archived)


class BookmarkCountTestCase(TestCase, BookmarkFactoryMixin, HtmlTestMixin):
    def setUp(self) -> None:
        self.user = self.get_or_create_test_user()
        self.client.force_login(self.user)

    def get_count(self, url="bookmarks.index"):
        response = self.client.get(reverse(f"linkding:{url}"))
        soup = self.make_soup(response.content.decode())
        return soup.select_one("#main-heading [data-bookmark-count]")

    def test_shows_total_number_of_bookmarks(self):
        self.user.profile.items_per_page = 2
        self.user.profile.save()
        for _ in range(3):
            self.setup_bookmark()

        count = self.get_count()

        self.assertEqual(count.text.strip(), "3")
        self.assertNotIn("d-none", count["class"])

    def test_hides_count_without_bookmarks(self):
        count = self.get_count()

        self.assertIn("d-none", count["class"])

    def test_shows_count_on_archived_page(self):
        self.setup_bookmark(is_archived=True)
        self.setup_bookmark()

        count = self.get_count("bookmarks.archived")

        self.assertEqual(count.text.strip(), "1")
