from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserProfile
from assistant.agent.tools import TOOL_REGISTRY
from assistant.agent.tools import me  # noqa: F401  (register tools)
from starlift.models import (
    Event,
    EventInvitation,
    EventRequest,
    Feedback,
    Speaker,
)

User = get_user_model()


def _speaker_user(username, speaker):
    u = User.objects.create_user(username, password="x")
    UserProfile.objects.filter(user=u).update(role="speaker")
    speaker.user = u
    speaker.save()
    return User.objects.get(pk=u.pk)


class MyFeedbackSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.me_speaker = Speaker.objects.create(name="Me", stack="ML", nps=0)
        cls.other = Speaker.objects.create(name="Other", stack="Go", nps=0)
        cls.user = _speaker_user("me", cls.me_speaker)
        cls.ev = Event.objects.create(title="Talk", status="past")
        cls.ev.speakers.add(cls.me_speaker)
        other_ev = Event.objects.create(title="OtherTalk", status="past")
        other_ev.speakers.add(cls.other)
        for sc, c in [(10, "отлично"), (9, "супер"), (5, "скучно")]:
            Feedback.objects.create(speaker=cls.me_speaker, event=cls.ev, score=sc, comment=c)
        # Foreign feedback must never appear.
        Feedback.objects.create(speaker=cls.other, event=other_ev, score=1, comment="LEAK")

    def test_summary_is_scoped_to_self(self):
        result = TOOL_REGISTRY["my_feedback_summary"].invoke({}, _user=self.user)
        self.assertEqual(result["speaker"], "Me")
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["promoters"], 2)
        self.assertEqual(result["detractors"], 1)
        comments = " ".join(c["comment"] for c in result["recent_comments"])
        self.assertNotIn("LEAK", comments)

    def test_non_speaker_gets_marker(self):
        admin = User.objects.create_user("adm", password="x")
        UserProfile.objects.filter(user=admin).update(role="admin")
        result = TOOL_REGISTRY["my_feedback_summary"].invoke({}, _user=admin)
        self.assertEqual(result["error"], "not_a_speaker")


class FindOpenEventsForMeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.me_speaker = Speaker.objects.create(name="Me2", stack="ML", nps=0)
        cls.user = _speaker_user("me2", cls.me_speaker)
        today = date.today()
        cls.open_ev = Event.objects.create(
            title="Open Future", status="future",
            event_date=today + timedelta(days=30),
            application_deadline=today + timedelta(days=10),
        )
        cls.closed_ev = Event.objects.create(
            title="Deadline Passed", status="future",
            application_deadline=today - timedelta(days=1),
        )
        cls.already_on = Event.objects.create(
            title="Already Mine", status="future",
            application_deadline=today + timedelta(days=5),
        )
        cls.already_on.speakers.add(cls.me_speaker)

    def test_lists_only_open_and_unjoined(self):
        result = TOOL_REGISTRY["find_open_events_for_me"].invoke({}, _user=self.user)
        titles = [e["title"] for e in result["events"]]
        self.assertIn("Open Future", titles)
        self.assertNotIn("Deadline Passed", titles)
        self.assertNotIn("Already Mine", titles)


class MyApplicationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.me_speaker = Speaker.objects.create(name="Me3", stack="ML", nps=0)
        cls.other = Speaker.objects.create(name="Other3", stack="Go", nps=0)
        cls.user = _speaker_user("me3", cls.me_speaker)
        EventRequest.objects.create(
            kind=EventRequest.KIND_CREATE, speaker=cls.me_speaker,
            proposed_title="My idea", status=EventRequest.STATUS_PENDING,
        )
        EventRequest.objects.create(
            kind=EventRequest.KIND_CREATE, speaker=cls.other,
            proposed_title="FOREIGN", status=EventRequest.STATUS_PENDING,
        )
        ev = Event.objects.create(title="Invited Event", status="future")
        EventInvitation.objects.create(
            event=ev, speaker=cls.me_speaker, status=EventInvitation.STATUS_PENDING,
            message="приходи",
        )

    def test_returns_own_requests_and_invites(self):
        result = TOOL_REGISTRY["my_applications"].invoke({}, _user=self.user)
        self.assertEqual(result["requests"]["pending"], 1)
        titles = [r["title"] for r in result["requests"]["recent"]]
        self.assertIn("My idea", titles)
        self.assertNotIn("FOREIGN", titles)
        invite_titles = [i["title"] for i in result["invitations_awaiting_response"]]
        self.assertEqual(invite_titles, ["Invited Event"])
