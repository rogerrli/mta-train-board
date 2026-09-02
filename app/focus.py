"""Scheduled focus mode: dedicate the board to one trip in a known window (#39).

The board (#7) is a general glance view, but for a known daily commute there's
really only **one** train that matters in a given window. A *focus rule* says:
during these weekdays and this time-of-day window, drop everything else and give
the whole screen to a single configured trip's arrive-by recommendation (#27).

It's a config-driven **list** (``[[focus]]``), not a one-off: add more
known-schedule cases without new code. A rule only points at an existing
``[[trips]]`` block by ``name`` -- the *target arrival time is owned by that trip*
(#27), never redefined here. This module just answers "is a focus rule active
right now, and which trip?"; shaping the payload and rendering live elsewhere
(``app.server`` / the frontend).

    [[focus]]
    trip  = "morning-uptown"          # references a [[trips]] name
    days  = ["mon", "tue", "wed", "thu", "fri"]
    start = "08:00"                    # Eastern, 24h HH:MM, inclusive
    end   = "09:00"                    # exclusive

Zero rules = today's behavior (always the glance board). When two rules overlap,
the **first in config order wins** -- a deterministic, simple pick. Everything
here is pure and offline: :meth:`FocusRule.active_at` / :func:`active_focus` take
an explicit ``now`` so tests drive a fake weekday/clock with no wall-clock or
network dependence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from app.feeds import EASTERN
from app.trips import WEEKDAY_KEYS

# Weekday abbreviation -> ``datetime.weekday()`` index (Mon=0 .. Sun=6). Shares the
# vocabulary with a trip's target table (#27) so the two read the same.
_WEEKDAY_INDEX = {key: i for i, key in enumerate(WEEKDAY_KEYS)}


class FocusConfigError(Exception):
    """A ``[[focus]]`` block is malformed or references an unknown trip."""


@dataclass(frozen=True)
class FocusRule:
    """A resolved focus rule: which trip to dedicate the board to, and when.

    ``trip`` is a ``[[trips]]`` name (validated to exist). ``days`` are the
    weekday indices the rule covers (Mon=0..Sun=6); ``start``/``end`` bound the
    daily window in Eastern local time, half-open ``[start, end)`` so adjacent
    windows don't double-fire at the boundary minute.
    """

    trip: str
    days: frozenset[int]
    start: time
    end: time

    def active_at(self, now: datetime) -> bool:
        """Whether this rule covers ``now`` (Eastern weekday + ``[start, end)``)."""
        now = now.astimezone(EASTERN) if now.tzinfo else now.replace(tzinfo=EASTERN)
        if now.weekday() not in self.days:
            return False
        return self.start <= now.time() < self.end


def _parse_hhmm(rule_trip: str, field: str, value: Any) -> time:
    """Parse a ``"HH:MM"`` (24h) window bound into a :class:`datetime.time`."""
    try:
        hour, minute = (int(part) for part in str(value).split(":"))
        return time(hour, minute)
    except (ValueError, TypeError):
        raise FocusConfigError(
            f'Focus rule for trip {rule_trip!r}: {field!r} must be "HH:MM" (24h), '
            f"got {value!r}."
        ) from None


def _parse_days(rule_trip: str, days: Any) -> frozenset[int]:
    """Parse a rule's ``days`` list of weekday abbreviations into weekday indices."""
    if not isinstance(days, list) or not days:
        raise FocusConfigError(
            f"Focus rule for trip {rule_trip!r}: 'days' must be a non-empty list of "
            f"weekday abbreviations, e.g. days = {list(WEEKDAY_KEYS[:5])}."
        )
    indices: set[int] = set()
    for day in days:
        if day not in _WEEKDAY_INDEX:
            raise FocusConfigError(
                f"Focus rule for trip {rule_trip!r}: unknown day {day!r}; use "
                f"{list(WEEKDAY_KEYS)}."
            )
        indices.add(_WEEKDAY_INDEX[day])
    return frozenset(indices)


def resolve_focus_rules(
    config: dict[str, Any], trip_names: set[str]
) -> list[FocusRule]:
    """Resolve every ``[[focus]]`` block to a validated :class:`FocusRule`.

    ``trip_names`` is the set of configured ``[[trips]]`` names (a rule must point
    at one -- the trip owns the target time #39 reuses). Validates the day list and
    the ``[start, end)`` window (``start`` strictly before ``end``; a window
    crossing midnight isn't supported -- split it into two rules). Returns ``[]``
    when no focus rules are configured. Raises :class:`FocusConfigError` on any
    problem. Pure: no I/O.
    """
    rules: list[FocusRule] = []
    for cfg in config.get("focus", []):
        trip = str(cfg.get("trip", "")).strip()
        if not trip:
            raise FocusConfigError("A [[focus]] block is missing a 'trip'.")
        if trip not in trip_names:
            known = sorted(trip_names)
            raise FocusConfigError(
                f"Focus rule references unknown trip {trip!r}; configured trips are "
                f"{known or 'none'}. A focus rule points at a [[trips]] name."
            )
        if "start" not in cfg or "end" not in cfg:
            raise FocusConfigError(
                f"Focus rule for trip {trip!r}: 'start' and 'end' (HH:MM) are required."
            )
        start = _parse_hhmm(trip, "start", cfg["start"])
        end = _parse_hhmm(trip, "end", cfg["end"])
        if start >= end:
            raise FocusConfigError(
                f"Focus rule for trip {trip!r}: 'start' ({cfg['start']}) must be "
                f"before 'end' ({cfg['end']}); a window crossing midnight isn't "
                f"supported -- split it into two rules."
            )
        rules.append(
            FocusRule(
                trip=trip,
                days=_parse_days(trip, cfg.get("days")),
                start=start,
                end=end,
            )
        )
    return rules


def active_focus(rules: list[FocusRule], now: datetime) -> FocusRule | None:
    """The focus rule active at ``now``, or ``None``. First match in order wins."""
    for rule in rules:
        if rule.active_at(now):
            return rule
    return None
