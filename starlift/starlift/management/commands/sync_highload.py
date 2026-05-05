"""Management command: sync Highload abstracts into Speaker/Event via ORM."""
from __future__ import annotations

import logging
import time

from django.core.management.base import BaseCommand

from parser.highload_importer import ImportCounters, get_highload_interval_minutes, sync_all_urls

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Fetch Highload abstract pages, parse talks, upsert Speaker and Event rows in PostgreSQL "
        "(no CSV). Default interval 30 minutes unless --once."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run a single sync pass and exit (no periodic loop).",
        )
        parser.add_argument(
            "--interval-minutes",
            type=int,
            default=None,
            help="Sleep between passes (default: HIGHLOAD_INTERVAL_MINUTES or 30). Ignored with --once.",
        )
        parser.add_argument(
            "--max-cycles",
            type=int,
            default=None,
            help="Stop after N passes (useful for tests). Infinite when omitted and not --once.",
        )

    def handle(self, *args, **opts):
        once = opts["once"]
        interval = opts["interval_minutes"]
        if interval is None:
            interval = get_highload_interval_minutes()
        max_cycles = opts["max_cycles"]

        def _pass() -> ImportCounters:
            self.stdout.write(self.style.NOTICE("highload sync: starting pass"))
            logger.info("highload sync: starting pass")
            counters = sync_all_urls()
            counters.log_summary(logger)
            msg = (
                f"highload sync: done parsed={counters.parsed} inserted={counters.inserted} "
                f"updated={counters.updated} skipped={counters.skipped} failed={counters.failed}"
            )
            self.stdout.write(self.style.SUCCESS(msg))
            logger.info(msg)
            return counters

        if once:
            _pass()
            return

        cycles = 0
        while True:
            _pass()
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                self.stdout.write(self.style.NOTICE(f"highload sync: stopping after {cycles} cycle(s)"))
                break
            sleep_s = max(1, int(interval) * 60)
            self.stdout.write(f"highload sync: sleeping {sleep_s}s")
            logger.info("highload sync: sleeping %ss until next pass", sleep_s)
            time.sleep(sleep_s)
