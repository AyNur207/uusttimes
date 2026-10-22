"""Donation page states and URL validation; no real payments or network calls."""

import unittest
from html.parser import HTMLParser

from uusttimes import create_app


class PaymentLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "donation-button" in attrs.get("class", "").split():
            self.links.append(attrs)


class SupportTests(unittest.TestCase):
    def render(self, url):
        app = create_app({
            "TESTING": True, "DONATION_URL": 'https://pay.cloudtips.ru/p/dc52cd81',
            "SECRET_KEY": "test-only-key", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        response = app.test_client().get("/support")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        links = PaymentLinks()
        links.feed(html)
        return html, links.links

    def test_no_link_shows_pending_state(self):
        html, links = self.render("")
        self.assertIn("Готовим приём донатов", html)
        self.assertEqual(links, [])

    def test_public_link_is_preserved_and_opens_separately(self):
        url = "https://pay.example.org/team?source=times&campaign=donations"
        html, links = self.render(f"  {url}  ")
        self.assertNotIn("Готовим приём донатов", html)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["href"], url)
        self.assertEqual(links[0]["target"], "_blank")
        self.assertEqual(set(links[0]["rel"].split()), {"noopener", "noreferrer"})
        self.assertEqual(links[0]["referrerpolicy"], "no-referrer")
        self.assertIn("pay.example.org", html)

    def test_unsafe_or_malformed_configuration_never_breaks_page(self):
        for url in (
            None, 123, "javascript:alert(1)", "http://example.org/pay",
            "//example.org/pay", "https:///pay", "https://[invalid",
            "https://example.org:invalid", "https://example.org:99999",
            "https://example.org:8080/pay", "https://user:password@example.org/pay",
            "https://example.org/\nredirect", "https://example.org\\@other.org/pay",
        ):
            with self.subTest(url=url):
                html, links = self.render(url)
                self.assertEqual(links, [])
                self.assertIn("Готовим приём донатов", html)

    def test_link_attribute_cannot_inject_html(self):
        url = 'https://example.org/pay?note="/><script>alert(1)</script>'
        html, links = self.render(url)
        self.assertNotIn("<script>", html)
        self.assertEqual(links[0]["href"], url)


if __name__ == "__main__":
    unittest.main()
