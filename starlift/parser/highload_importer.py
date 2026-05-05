"""
Import Highload-parsed rows into Django models (Speaker, Event) with deduplication.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from django.db import transaction

from starlift.models import Event, Speaker

from parser.highload import parse_records_from_html, record_is_valid

logger = logging.getLogger(__name__)

DEFAULT_HIGHLOAD_URLS = [
    "https://highload.ru/moscow/2025/abstracts",
    "https://highload.ru/spb/2026/abstracts",
]


def _int_from_env(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_from_env(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def get_highload_urls() -> list[str]:
    raw = os.getenv("HIGHLOAD_URLS", "").strip()
    if not raw:
        return list(DEFAULT_HIGHLOAD_URLS)
    return [u.strip() for u in raw.split(",") if u.strip()]


def get_highload_interval_minutes() -> int:
    return max(1, _int_from_env("HIGHLOAD_INTERVAL_MINUTES", 30))


def get_request_timeout() -> float:
    return max(1.0, _float_from_env("HIGHLOAD_REQUEST_TIMEOUT", 20.0))


def get_max_retries() -> int:
    return max(1, min(10, _int_from_env("HIGHLOAD_MAX_RETRIES", 3)))


def _clip(s: str, max_len: int) -> str:
    if not s:
        return ""
    return s if len(s) <= max_len else s[:max_len]


def normalized_display_name(name: str) -> str:
    return " ".join((name or "").split()).strip()


def _merge_text(keep: str | None, new_val: str | None) -> str | None:
    new_strip = (new_val or "").strip()
    if not new_strip:
        return keep
    return new_strip


def _speaker_queryset(author: str, company: str, stack: str):
    name = normalized_display_name(author)
    company_stripped = (company or "").strip()
    stack_stripped = " ".join((stack or "").split()).strip()
    if company_stripped:
        return Speaker.objects.filter(name__iexact=name, sub__iexact=company_stripped)
    return Speaker.objects.filter(name__iexact=name, stack__iexact=stack_stripped)


def find_speaker(author: str, company: str, stack: str) -> Speaker | None:
    return _speaker_queryset(author, company, stack).first()


def find_event(*, link: str, title: str, date: str) -> Event | None:
    link = (link or "").strip()
    if link:
        found = Event.objects.filter(link=link).first()
        if found:
            return found
    t = normalized_display_name(title)
    d = (date or "").strip()
    if not t:
        return None
    if d:
        return Event.objects.filter(title__iexact=t, date=d).first()
    return Event.objects.filter(title__iexact=t).filter(date__in=["", None]).first()


IMG_FALLBACK = "0"

_SPEAKER_CITY_DEFAULT = "Не указан"


@dataclass
class ImportCounters:
    parsed: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0

    def log_summary(self, log: logging.Logger) -> None:
        log.info(
            "highload import pass: parsed=%s inserted=%s updated=%s skipped=%s failed=%s",
            self.parsed,
            self.inserted,
            self.updated,
            self.skipped,
            self.failed,
        )


def retry_call(fn, *, max_retries: int | None = None, operation: str = "operation") -> None:
    """Run fn with exponential backoff; last failure re-raises."""
    attempts = max_retries if max_retries is not None else get_max_retries()
    delay = 1.0
    last_err: BaseException | None = None
    for attempt in range(attempts):
        try:
            fn()
            return
        except Exception as e:  # noqa: BLE001 — intentional: retry broad, log on failure
            last_err = e
            if attempt + 1 >= attempts:
                break
            logger.warning(
                "%s failed (attempt %s/%s): %s; retry in %ss",
                operation,
                attempt + 1,
                attempts,
                e,
                delay,
            )
            time.sleep(delay)
            delay *= 2.0
    assert last_err is not None
    raise last_err


def import_parsed_row(rec: dict[str, str], *, counters: ImportCounters | None = None) -> None:
    """Persist one normalized dict; updates counters. Raises after retries exhausted."""
    if counters is None:
        counters = ImportCounters()

    if not record_is_valid(rec):
        counters.skipped += 1
        return

    author = rec["author"]
    company = rec["company"]
    stack = rec["stack"]
    title = rec["title"]
    date_val = rec["date"]
    description = rec["description"]
    link = rec["link"]
    avatar = rec["author_avatar"]

    def _write() -> None:
        with transaction.atomic():
            speaker = find_speaker(author, company, stack)
            event = find_event(link=link, title=title, date=date_val)

            if speaker is None:
                speaker = Speaker(
                    name=normalized_display_name(author) or author,
                    sub=_clip(company.strip(), 200) if company else "",
                    stack=_clip(stack.strip(), 200) if stack else "",
                    city=_SPEAKER_CITY_DEFAULT,
                    status=Speaker.STATUS_UNAUTHORIZED,
                    nps=0,
                    img=_clip(avatar, 100) if avatar else IMG_FALLBACK,
                )
                speaker.save()
                counters.inserted += 1
            else:
                changed = False
                if company:
                    new_sub = _clip(company.strip(), 200)
                    if speaker.sub != new_sub:
                        speaker.sub = new_sub
                        changed = True
                if stack:
                    new_stack = _clip(stack.strip(), 200)
                    if speaker.stack != new_stack:
                        speaker.stack = new_stack
                        changed = True
                new_img = _clip(avatar, 100) if avatar else ""
                if new_img and speaker.img != new_img:
                    speaker.img = new_img
                    changed = True
                if changed:
                    speaker.save()
                    counters.updated += 1

            if event is None:
                event = Event(
                    title=_clip(title, 200),
                    status="future",
                    date=date_val or None,
                    link=link or None,
                    description=description or None,
                    topic=_clip(stack, 100) if stack else None,
                    is_external=True,
                    source="parser",
                )
                event.save()
                counters.inserted += 1
            else:
                ev_changed = False
                nt = _merge_text(event.description, description)
                if nt != event.description:
                    event.description = nt
                    ev_changed = True
                nd = _merge_text(event.date, date_val)
                if nd != event.date:
                    event.date = nd
                    ev_changed = True
                if stack:
                    ntpc = _clip(stack, 100)
                    if ntpc != (event.topic or ""):
                        event.topic = ntpc
                        ev_changed = True
                if not event.link and link:
                    event.link = link
                    ev_changed = True
                if ev_changed:
                    event.save()
                    counters.updated += 1

            speaker.refresh_from_db()
            event.refresh_from_db()
            if not event.speakers.filter(pk=speaker.pk).exists():
                event.speakers.add(speaker)

    retry_call(_write, operation="highload_db_write")


def run_import_pass(
    *,
    records: list[dict[str, str]],
    counters: ImportCounters | None = None,
) -> ImportCounters:
    """
    Import all parsed records; one bad row does not stop the batch.
    """
    if counters is None:
        counters = ImportCounters()
    counters.parsed += len(records)

    for rec in records:
        if not record_is_valid(rec):
            counters.skipped += 1
            continue
        try:
            import_parsed_row(rec, counters=counters)
        except Exception as e:  # noqa: BLE001
            logger.error("highload row failed after retries: %s rec=%r", e, rec)
            counters.failed += 1

    return counters


def fetch_and_parse_url(url: str, *, timeout: float, session) -> list[dict[str, str]]:
    from parser.highload import fetch_html

    html_text: str | None = None

    def _http() -> None:
        nonlocal html_text
        html_text = fetch_html(url, timeout=timeout, session=session)

    retry_call(_http, operation=f"highload_http({url})")
    assert html_text is not None
    return parse_records_from_html(html_text)


def sync_all_urls(
    *,
    urls: list[str] | None = None,
    timeout: float | None = None,
    session=None,
    counters: ImportCounters | None = None,
) -> ImportCounters:
    """Fetch configured URLs, parse, import. HTTP retry per URL inside fetch."""
    if urls is None:
        urls = get_highload_urls()
    if timeout is None:
        timeout = get_request_timeout()
    if counters is None:
        counters = ImportCounters()

    if session is None:
        import requests

        session = requests.Session()

    for url in urls:
        try:
            records = fetch_and_parse_url(url, timeout=timeout, session=session)
        except Exception as e:  # noqa: BLE001
            logger.error("highload URL failed after retries: %s url=%s", e, url)
            counters.failed += 1
            continue
        run_import_pass(records=records, counters=counters)

    return counters
