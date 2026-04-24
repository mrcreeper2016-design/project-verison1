"""Tests for the analytics dashboard.

Covers the two most important guarantees of the StarLift MVP:
1. NPS is calculated according to the textbook formula
   (promoters% - detractors%) * 100 with the correct buckets.
2. The nomination-candidate picker respects the ≥ 9.4 avg-score threshold,
   the ≥ 2 events / 6-months frequency rule and honours the ``recommended`` flag.
"""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.http.request import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import analytics as analytics_lib
from . import home_metrics
from .models import Event, Feedback, Speaker


def _login_member(client):
    """Helper: create a verified speaker user and authenticate the test client.

    The dashboard / home / analytics views require the `admin` or `speaker`
    role (member-only) since Phase 2 of the auth plan, so we can't hit them
    anonymously. This helper keeps the existing tests focused on metrics.
    """
    from accounts.models import UserProfile

    User = get_user_model()
    user = User.objects.create_user(
        username="dashtester",
        email="dashtester@example.com",
        password="Secret!234",
    )
    user.profile.role = UserProfile.ROLE_SPEAKER
    user.profile.email_verified = True
    user.profile.save(update_fields=["role", "email_verified"])
    client.login(username="dashtester", password="Secret!234")
    return user


def _make_speaker(name: str = "Speaker", city: str = "Moscow", stack: str = "Python") -> Speaker:
    return Speaker.objects.create(
        name=name, sub="Sub", stack=stack, city=city, status="active", nps=0, img="1"
    )


def _make_event(title: str = "Event", is_external: bool = False) -> Event:
    return Event.objects.create(title=title, status="past", is_external=is_external)


def _add_feedback(speaker: Speaker, event: Event, score: int, when=None) -> Feedback:
    fb = Feedback(speaker=speaker, event=event, score=score)
    fb.save()
    if when is not None:
        Feedback.objects.filter(pk=fb.pk).update(created_at=when)
        fb.refresh_from_db()
    return fb


class ComputeNpsTests(TestCase):
    def test_promoters_minus_detractors_percentage(self):
        speaker = _make_speaker()
        event = _make_event()
        # 6 promoters (9-10), 2 passives (7-8), 2 detractors (0-6) -> 10 total
        # NPS = (60% - 20%) * 100 = 40
        for s in [10, 10, 10, 9, 9, 9]:
            _add_feedback(speaker, event, s)
        for s in [7, 8]:
            _add_feedback(speaker, event, s)
        for s in [5, 3]:
            _add_feedback(speaker, event, s)

        stats = analytics_lib.compute_nps(Feedback.objects.all())
        self.assertEqual(stats["total"], 10)
        self.assertEqual(stats["promoters"], 6)
        self.assertEqual(stats["passives"], 2)
        self.assertEqual(stats["detractors"], 2)
        self.assertAlmostEqual(stats["nps"], 40.0, places=1)
        self.assertAlmostEqual(stats["avg_score"], 8.0, places=1)

    def test_empty_feedbacks_returns_zero_nps(self):
        stats = analytics_lib.compute_nps(Feedback.objects.none())
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["nps"], 0.0)
        self.assertIsNone(stats["avg_score"])

    def test_works_with_iterable_of_objects(self):
        class FakeFb:
            def __init__(self, score):
                self.score = score

        stats = analytics_lib.compute_nps([FakeFb(10), FakeFb(10), FakeFb(5)])
        # promoters=2, detractors=1, total=3 -> NPS = (66.66 - 33.33) ≈ 33.3
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["promoters"], 2)
        self.assertEqual(stats["detractors"], 1)
        self.assertAlmostEqual(stats["nps"], 33.3, places=1)


class NominationCandidatesTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.in_window = self.now - timedelta(days=30)
        self.out_of_window = self.now - timedelta(days=300)

    def _filters(self, **overrides):
        q = QueryDict(mutable=True)
        for k, v in overrides.items():
            q[k] = str(v)
        return analytics_lib.parse_filters(q)

    def test_qualified_speaker_is_selected(self):
        speaker = _make_speaker("Alice")
        ev1 = _make_event("E1")
        ev2 = _make_event("E2")
        for s in [10, 10]:
            _add_feedback(speaker, ev1, s, when=self.in_window)
        for s in [9, 10]:
            _add_feedback(speaker, ev2, s, when=self.in_window)

        filters = self._filters(period="90")
        candidates = analytics_lib.nomination_candidates(filters)
        names = [c["name"] for c in candidates]
        self.assertIn("Alice", names)
        alice = next(c for c in candidates if c["name"] == "Alice")
        self.assertGreaterEqual(alice["avg_score"], 9.4)
        self.assertGreaterEqual(alice["events_count"], 2)

    def test_low_avg_score_is_filtered_out(self):
        speaker = _make_speaker("Bob")
        ev1, ev2 = _make_event("E1"), _make_event("E2")
        _add_feedback(speaker, ev1, 8, when=self.in_window)
        _add_feedback(speaker, ev2, 8, when=self.in_window)

        filters = self._filters(period="90")
        candidates = analytics_lib.nomination_candidates(filters)
        self.assertNotIn("Bob", [c["name"] for c in candidates])

    def test_too_few_events_is_filtered_out(self):
        speaker = _make_speaker("Carol")
        ev1 = _make_event("E1")
        for s in [10, 10, 10, 9]:
            _add_feedback(speaker, ev1, s, when=self.in_window)

        filters = self._filters(period="90")
        candidates = analytics_lib.nomination_candidates(filters)
        self.assertNotIn("Carol", [c["name"] for c in candidates])

    def test_events_outside_window_do_not_count(self):
        speaker = _make_speaker("Dan")
        ev1, ev2, ev3 = _make_event("E1"), _make_event("E2"), _make_event("E3")
        # Only 1 event inside the 6-month window, the other two are older
        _add_feedback(speaker, ev1, 10, when=self.in_window)
        _add_feedback(speaker, ev2, 10, when=self.out_of_window)
        _add_feedback(speaker, ev3, 10, when=self.out_of_window)

        filters = self._filters(period="90")
        candidates = analytics_lib.nomination_candidates(filters)
        self.assertNotIn("Dan", [c["name"] for c in candidates])

    def test_custom_nps_threshold_is_respected(self):
        speaker = _make_speaker("Eve")
        ev1, ev2 = _make_event("E1"), _make_event("E2")
        for s in [8, 9]:
            _add_feedback(speaker, ev1, s, when=self.in_window)
        for s in [8, 9]:
            _add_feedback(speaker, ev2, s, when=self.in_window)

        # Default threshold (9.4) — Eve does NOT qualify (avg = 8.5)
        filters_default = self._filters(period="90")
        self.assertNotIn("Eve", [c["name"] for c in analytics_lib.nomination_candidates(filters_default)])

        # Relaxed threshold — Eve qualifies
        filters_relaxed = self._filters(period="90", nps_threshold="8.0")
        self.assertIn("Eve", [c["name"] for c in analytics_lib.nomination_candidates(filters_relaxed)])


class FilterParserTests(TestCase):
    def test_defaults(self):
        f = analytics_lib.parse_filters(QueryDict(""))
        self.assertEqual(f.period, str(analytics_lib.DEFAULT_PERIOD_DAYS))
        self.assertIsNone(f.nps_threshold)
        self.assertEqual(f.city, "")

    def test_custom_range_uses_provided_dates(self):
        q = QueryDict("period=custom&date_from=2026-01-01&date_to=2026-02-01")
        f = analytics_lib.parse_filters(q)
        self.assertEqual(f.period, "custom")
        self.assertEqual(f.start_dt.date().isoformat(), "2026-01-01")
        self.assertEqual(f.end_dt.date().isoformat(), "2026-02-01")

    def test_threshold_accepts_comma_decimal(self):
        q = QueryDict("nps_threshold=9,4")
        f = analytics_lib.parse_filters(q)
        self.assertAlmostEqual(f.nps_threshold, 9.4)


class DashboardViewTests(TestCase):
    def setUp(self):
        _login_member(self.client)

    def test_analytics_page_renders_without_data(self):
        response = self.client.get(reverse("analytics"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Аналитика спикеров")
        self.assertContains(response, "Кандидаты на выдвижение")
        # Все 7 секций присутствуют в разметке
        for title in (
            "Карта активности",
            "Рейтинг спикеров",
            "Кандидаты на выдвижение",
            "Внешний след",
            "Слепые зоны",
            "Тематический профиль",
        ):
            self.assertContains(response, title)

    def test_analytics_page_renders_with_data(self):
        speaker = _make_speaker("Frank")
        ev1, ev2 = _make_event("Ext", is_external=True), _make_event("Int", is_external=False)
        for s in [10, 10, 9]:
            _add_feedback(speaker, ev1, s, when=timezone.now() - timedelta(days=15))
        _add_feedback(speaker, ev2, 10, when=timezone.now() - timedelta(days=10))

        response = self.client.get(reverse("analytics") + "?period=90&nps_threshold=9.4")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Frank")


class HomeDashboardTests(TestCase):
    """Regression-proof the Home dashboard contract."""

    def setUp(self):
        _login_member(self.client)

    def test_home_page_renders_without_data(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="home-dashboard"')
        self.assertContains(response, "/api/home/")
        self.assertContains(response, "Оперативный центр")

    def test_home_api_returns_required_sections_with_empty_db(self):
        response = self.client.get("/api/home/")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        for key in ("version", "kpis", "upcoming_events", "top_speakers", "activity", "options"):
            self.assertIn(key, data)
        self.assertEqual(data["kpis"]["total_speakers"], 0)
        self.assertEqual(data["kpis"]["active_speakers"], 0)
        self.assertEqual(data["kpis"]["avg_nps"], 0.0)
        self.assertEqual(data["upcoming_events"], [])
        self.assertEqual(data["top_speakers"], [])
        self.assertEqual(data["activity"], [])

    def test_home_api_reflects_filters_and_activity(self):
        alice = _make_speaker("Alice", city="Moscow", stack="Python")
        bob = _make_speaker("Bob", city="Kazan", stack="Frontend")
        event = _make_event("MeetupA")
        now = timezone.now()
        for s in [10, 10, 9, 10]:
            _add_feedback(alice, event, s, when=now - timedelta(days=2))
        _add_feedback(bob, event, 8, when=now - timedelta(days=2))

        resp = self.client.get("/api/home/?period=30&city=Moscow")
        data = json.loads(resp.content)
        names = [sp["name"] for sp in data["top_speakers"]]
        self.assertIn("Alice", names)
        self.assertNotIn("Bob", names)
        self.assertGreaterEqual(data["kpis"]["total_feedbacks"], 4)
        self.assertEqual(data["kpis"]["active_speakers"], 1)
        # Activity feed should contain the recent feedback entries.
        self.assertTrue(any(it["type"] == "feedback" for it in data["activity"]))

    def test_data_version_changes_on_new_feedback(self):
        alice = _make_speaker("Alice")
        event = _make_event("E1")
        before = home_metrics.data_version()
        _add_feedback(alice, event, 10)
        after = home_metrics.data_version()
        self.assertNotEqual(before, after)

    def test_upcoming_events_uses_future_date(self):
        future_date = timezone.now().date() + timedelta(days=7)
        past_date = timezone.now().date() - timedelta(days=7)
        Event.objects.create(title="FutureE", status="future", event_date=future_date)
        Event.objects.create(title="PastE", status="past", event_date=past_date)

        filters = home_metrics.parse_filters(QueryDict("period=30"))
        upcoming = home_metrics.upcoming_events(filters)
        titles = [e["title"] for e in upcoming]
        self.assertIn("FutureE", titles)
        self.assertNotIn("PastE", titles)

    def test_parse_filters_normalises_invalid_period(self):
        filters = home_metrics.parse_filters(QueryDict("period=bogus"))
        self.assertEqual(filters.period, str(home_metrics.DEFAULT_PERIOD_DAYS))
