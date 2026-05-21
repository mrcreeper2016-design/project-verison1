"""Tests for the analytics dashboard.

Covers the two most important guarantees of the StarLift MVP:
1. NPS is calculated according to the textbook formula
   (promoters% - detractors%) * 100 with the correct buckets.
2. The nomination-candidate picker respects the ≥ 9.4 avg-score threshold,
   the ≥ 2 events / 6-months frequency rule and honours the ``recommended`` flag.
"""

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.http.request import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import analytics as analytics_lib
from . import home_metrics
from .models import Event, Feedback, Speaker

from parser.highload import parse_records_from_html
from parser.highload_importer import ImportCounters, run_import_pass, sync_all_urls


def _login_admin(client):
    from accounts.models import UserProfile

    User = get_user_model()
    user = User.objects.create_user(
        username="admintest",
        email="admin@example.com",
        password="Secret!234",
    )
    user.profile.role = UserProfile.ROLE_ADMIN
    user.profile.email_verified = True
    user.profile.save(update_fields=["role", "email_verified"])
    client.login(username="admintest", password="Secret!234")
    return user


class QrAccessTests(TestCase):
    def setUp(self):
        self.sp_me = _make_speaker("MeSpeaker")
        self.sp_other = _make_speaker("OtherSpeaker")
        self.ev_ok = _make_event("My Talk")
        self.ev_foreign = _make_event("Foreign Event")
        self.ev_ok.speakers.add(self.sp_me)
        self.ev_foreign.speakers.add(self.sp_other)

        User = get_user_model()
        from accounts.models import UserProfile

        self.user_sp = User.objects.create_user(
            username="spqr",
            email="spqr@example.com",
            password="Secret!234",
        )
        self.user_sp.profile.role = UserProfile.ROLE_SPEAKER
        self.user_sp.profile.email_verified = True
        self.user_sp.profile.save(update_fields=["role", "email_verified"])
        self.sp_me.user = self.user_sp
        self.sp_me.save(update_fields=["user"])

    def test_speaker_qr_page_locks_speaker_to_self(self):
        self.client.login(username="spqr", password="Secret!234")
        r = self.client.get(reverse("qr_generator"))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Speaker name is rendered as the readonly input value.
        self.assertIn('value="MeSpeaker"', body)
        self.assertIn('readonly', body)
        # Their own events appear; foreign events do not.
        self.assertIn("My Talk", body)
        self.assertNotIn("Foreign Event", body)

    def test_admin_qr_page_lists_all_speakers(self):
        _login_admin(self.client)
        r = self.client.get(reverse("qr_generator"))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("MeSpeaker", body)
        self.assertIn("OtherSpeaker", body)
        # The combobox input is present and not readonly for admins.
        self.assertIn('id="speakerInput"', body)
        self.assertNotIn('id="speakerSelect"', body)

    def test_speaker_can_generate_qr_only_own_event(self):
        self.client.login(username="spqr", password="Secret!234")
        url = reverse("generate_qr", kwargs={"speaker_id": self.sp_me.id, "event_id": self.ev_ok.id})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_speaker_forbidden_other_speaker(self):
        self.client.login(username="spqr", password="Secret!234")
        url = reverse("generate_qr", kwargs={"speaker_id": self.sp_other.id, "event_id": self.ev_ok.id})
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_speaker_forbidden_event_not_linked(self):
        self.client.login(username="spqr", password="Secret!234")
        url = reverse("generate_qr", kwargs={"speaker_id": self.sp_me.id, "event_id": self.ev_foreign.id})
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_admin_can_generate_any_pair(self):
        _login_admin(self.client)
        url = reverse("generate_qr", kwargs={"speaker_id": self.sp_other.id, "event_id": self.ev_foreign.id})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_unlinked_speaker_sees_warning_and_no_form(self):
        self.sp_me.user = None
        self.sp_me.save(update_fields=["user"])
        self.client.login(username="spqr", password="Secret!234")
        r = self.client.get(reverse("qr_generator"))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("привязанная карточка", body)
        # No generate button when there's no data to work with.
        self.assertNotIn('id="generateBtn"', body)

    def test_admin_cannot_generate_qr_for_non_participating_pair(self):
        """Defence-in-depth: even if admin crafts the URL by hand, the server refuses."""
        _login_admin(self.client)
        # sp_me is on ev_ok only; sp_other on ev_foreign only.
        url = reverse(
            "generate_qr",
            kwargs={"speaker_id": self.sp_me.id, "event_id": self.ev_foreign.id},
        )
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_qr_poster_returns_png_for_valid_pair(self):
        _login_admin(self.client)
        url = reverse(
            "qr_poster",
            kwargs={"speaker_id": self.sp_me.id, "event_id": self.ev_ok.id},
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertIn("attachment", resp["Content-Disposition"])
        # PNG magic bytes
        self.assertTrue(resp.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_qr_poster_forbidden_for_invalid_pair(self):
        _login_admin(self.client)
        url = reverse(
            "qr_poster",
            kwargs={"speaker_id": self.sp_me.id, "event_id": self.ev_foreign.id},
        )
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_qr_poster_forbidden_for_other_speaker(self):
        self.client.login(username="spqr", password="Secret!234")
        url = reverse(
            "qr_poster",
            kwargs={"speaker_id": self.sp_other.id, "event_id": self.ev_foreign.id},
        )
        self.assertEqual(self.client.get(url).status_code, 403)


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
        name=name, sub="Sub", stack=stack, city=city, nps=0, img="1"
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


HIGHLOAD_FIXTURE_HTML = """
<div class="thesis__list">
  <div>
    <div>
      <h2 class="thesis__item-title">
        <a class="thesis__item-title-link" href="/talk/one">Talk One</a>
      </h2>
      <div class="thesis__tags"><div>Python</div><div>Backend</div></div>
      <div class="thesis__authors">
        <div class="thesis__author">
          <a class="thesis__author-name">Jane Doe</a>
          <p class="thesis__author-company">ACME Corp</p>
          <a class="thesis__author-img" style="background-image: url('/static/jane.png');"></a>
        </div>
      </div>
      <a class="thesis__item-schedule-text">12 марта, 10:00</a>
      <div class="thesis__text">Abstract body</div>
    </div>
  </div>
</div>
"""


class HighloadParserTests(TestCase):
    def test_parses_expected_fields(self):
        rows = parse_records_from_html(HIGHLOAD_FIXTURE_HTML, base_url="https://highload.ru")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["author"], "Jane Doe")
        self.assertEqual(r["company"], "ACME Corp")
        self.assertEqual(r["title"], "Talk One")
        self.assertEqual(r["date"], "12 марта")
        self.assertEqual(r["stack"], "Python, Backend")
        self.assertEqual(r["description"], "Abstract body")
        self.assertEqual(r["link"], "https://highload.ru/talk/one")
        self.assertTrue(r["author_avatar"].endswith("/static/jane.png"))

    def test_missing_thesis_list_returns_empty(self):
        self.assertEqual(parse_records_from_html("<html><body></body></html>"), [])

    def test_broken_inner_blocks_skipped_without_crash(self):
        bad = """
        <div class="thesis__list"><div><div>
          <h2 class="thesis__item-title"></h2>
        </div></div></div>
        """
        self.assertEqual(parse_records_from_html(bad), [])


class HighloadImporterTests(TestCase):
    def _sample_record(self) -> dict[str, str]:
        return {
            "author": "Jane Doe",
            "author_avatar": "https://highload.test/a.png",
            "company": "ACME Corp",
            "title": "Talk One",
            "date": "12 марта",
            "stack": "Python",
            "description": "Abstract body",
            "link": "https://highload.ru/talk/one",
        }

    def test_import_creates_speaker_event_and_m2m(self):
        run_import_pass(records=[self._sample_record()])
        self.assertEqual(Speaker.objects.count(), 1)
        self.assertEqual(Event.objects.count(), 1)
        sp = Speaker.objects.get()
        ev = Event.objects.get()
        self.assertEqual(sp.name, "Jane Doe")
        self.assertEqual(sp.sub, "ACME Corp")
        self.assertEqual(sp.city, "Не указан")
        self.assertEqual(sp.status, Speaker.STATUS_UNAUTHORIZED)
        self.assertEqual(ev.title, "Talk One")
        self.assertEqual(ev.status, "future")
        self.assertEqual(ev.source, "parser")
        self.assertTrue(ev.is_external)
        self.assertIn(sp, ev.speakers.all())

    def test_second_import_no_duplicates(self):
        rec = self._sample_record()
        run_import_pass(records=[rec])
        n_sp, n_ev = Speaker.objects.count(), Event.objects.count()
        run_import_pass(records=[rec])
        self.assertEqual(Speaker.objects.count(), n_sp)
        self.assertEqual(Event.objects.count(), n_ev)

    def test_empty_author_skipped(self):
        bad = self._sample_record()
        bad["author"] = ""
        c = run_import_pass(records=[bad])
        self.assertEqual(c.skipped, 1)
        self.assertEqual(Speaker.objects.count(), 0)

    @patch.object(Speaker, "save", side_effect=RuntimeError("db down"))
    def test_failed_row_counts_failed(self, _mock_save):
        rec = self._sample_record()
        c = run_import_pass(records=[rec])
        self.assertEqual(c.failed, 1)
        self.assertEqual(Speaker.objects.count(), 0)

    @patch("parser.highload.fetch_html")
    def test_sync_all_urls_no_network(self, mock_fetch):
        mock_fetch.return_value = HIGHLOAD_FIXTURE_HTML
        import requests

        sync_all_urls(urls=["https://example.invalid/abstracts"], session=requests.Session())
        self.assertTrue(Speaker.objects.filter(name="Jane Doe").exists())
        mock_fetch.assert_called()


class SyncHighloadCommandTests(TestCase):
    @patch("starlift.management.commands.sync_highload.sync_all_urls")
    def test_once_calls_sync_once(self, mock_sync):
        mock_sync.return_value = ImportCounters()
        call_command("sync_highload", "--once")
        mock_sync.assert_called_once()

    @patch("time.sleep", return_value=None)
    @patch("starlift.management.commands.sync_highload.sync_all_urls")
    def test_max_cycles_runs_n_times(self, mock_sync, _sleep):
        mock_sync.return_value = ImportCounters()
        call_command("sync_highload", "--max-cycles=2", "--interval-minutes=1")
        self.assertEqual(mock_sync.call_count, 2)


class SpeakerLikeTests(TestCase):
    def setUp(self):
        from accounts.models import UserProfile
        User = get_user_model()

        self.user = User.objects.create_user(
            username="liker", email="liker@x.io", password="Secret!234"
        )
        self.user.profile.role = UserProfile.ROLE_SPEAKER
        self.user.profile.email_verified = True
        self.user.profile.save(update_fields=["role", "email_verified"])

        self.speaker = _make_speaker("Hearted")

    def test_like_toggle_creates_then_removes(self):
        self.client.login(username="liker", password="Secret!234")
        url = f"/api/speakers/{self.speaker.id}/like/"

        # First POST → liked
        r1 = self.client.post(url)
        self.assertEqual(r1.status_code, 200)
        d1 = r1.json()
        self.assertTrue(d1["liked"])
        self.assertEqual(d1["like_count"], 1)

        # Second POST → unliked
        r2 = self.client.post(url)
        self.assertEqual(r2.status_code, 200)
        d2 = r2.json()
        self.assertFalse(d2["liked"])
        self.assertEqual(d2["like_count"], 0)

    def test_like_get_not_allowed(self):
        self.client.login(username="liker", password="Secret!234")
        r = self.client.get(f"/api/speakers/{self.speaker.id}/like/")
        self.assertEqual(r.status_code, 405)

    def test_like_requires_login(self):
        r = self.client.post(f"/api/speakers/{self.speaker.id}/like/")
        # @member_required redirects anon to login (302).
        self.assertIn(r.status_code, (302, 403))

    def test_speakers_api_includes_liked_flag_after_like(self):
        self.client.login(username="liker", password="Secret!234")
        self.client.post(f"/api/speakers/{self.speaker.id}/like/")
        r = self.client.get("/api/speakers/")
        self.assertEqual(r.status_code, 200)
        items = r.json()
        mine = next((s for s in items if s["id"] == self.speaker.id), None)
        self.assertIsNotNone(mine)
        self.assertTrue(mine["liked"])
        self.assertEqual(mine["like_count"], 1)

    def test_speakers_api_zero_likes_by_default(self):
        self.client.login(username="liker", password="Secret!234")
        r = self.client.get("/api/speakers/")
        self.assertEqual(r.status_code, 200)
        items = r.json()
        mine = next((s for s in items if s["id"] == self.speaker.id), None)
        self.assertIsNotNone(mine)
        self.assertFalse(mine["liked"])
        self.assertEqual(mine["like_count"], 0)


class SpeakerRecommendTests(TestCase):
    def setUp(self):
        self.admin = _login_admin(self.client)
        self.speaker = _make_speaker("RecMe")
        self.assertFalse(self.speaker.recommended)

    def test_recommend_toggle_flips_flag(self):
        url = f"/api/speakers/{self.speaker.id}/recommend/"
        r1 = self.client.post(url)
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json()["recommended"])
        self.speaker.refresh_from_db()
        self.assertTrue(self.speaker.recommended)

        r2 = self.client.post(url)
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json()["recommended"])
        self.speaker.refresh_from_db()
        self.assertFalse(self.speaker.recommended)

    def test_recommend_get_not_allowed(self):
        r = self.client.get(f"/api/speakers/{self.speaker.id}/recommend/")
        self.assertEqual(r.status_code, 405)

    def test_recommend_forbidden_for_non_admin(self):
        from accounts.models import UserProfile
        User = get_user_model()
        speaker_user = User.objects.create_user(
            username="notadmin", email="na@x.io", password="Secret!234"
        )
        speaker_user.profile.role = UserProfile.ROLE_SPEAKER
        speaker_user.profile.save(update_fields=["role"])
        self.client.logout()
        self.client.login(username="notadmin", password="Secret!234")
        r = self.client.post(f"/api/speakers/{self.speaker.id}/recommend/")
        self.assertEqual(r.status_code, 403)

    def test_speakers_api_includes_recommended(self):
        self.speaker.recommended = True
        self.speaker.save(update_fields=["recommended"])
        r = self.client.get("/api/speakers/")
        item = next((s for s in r.json() if s["id"] == self.speaker.id), None)
        self.assertIsNotNone(item)
        self.assertTrue(item["recommended"])
