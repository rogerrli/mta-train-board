"""Transfer-crowding comfort hints for the watched lines (#28).

When two trains reach the same transfer complex back-to-back, the second one
often boards crowded: riders spill off the first train and pile onto the next one
going their way. This module turns that pattern into a light, advisory hint --
flag a train on your line that closely *follows* another line's arriving train
(likely crowded), and mark one that arrives *ahead of* it (beats the crowd) -- so
the board can gently prefer the comfortable train.

Scope (#28, owner's calls):

* **Config it manually per complex.** A ``[[transfer_crowding]]`` block names the
  transfer complex (by station name, same convention as ``[[stations]]``), the
  ``line`` on your commute to annotate, and the ``feeders`` -- the other lines
  whose arriving riders crowd it. Both your line and the feeders must already be
  configured ``[[stations]]`` at that complex, so their live arrivals are on the
  board; crowding reads those computed :class:`~app.arrivals.ArrivalGroup`\\s
  rather than fetching anything itself.
* **Any direction in the complex feeds the crowd.** A feeder train in *either*
  direction can dump transferring riders, so a feeder arrival counts regardless
  of its N/S -- we compare against your train purely on arrival time.
* **A short adjacency window.** A feeder arriving within
  ``transfer_crowd_window_minutes`` (default :data:`DEFAULT_CROWD_WINDOW_MINUTES`)
  *before* your train flags it ``crowded``; your train arriving within that window
  before a feeder is ``beats_crowd``. A simultaneous feeder counts as crowded.

The whole thing is advisory: :func:`annotate_crowding` only sets each arrival's
``crowding`` field -- it never drops, reorders, or hides a train. The board (#7)
and the arrive-by recommendation (#27) use the hint as a comfort tiebreaker, never
a hard filter, so a train you actually need to catch is never de-prioritized.

Both public functions are pure and offline (config resolution takes a prebuilt
:class:`~app.stops.StopIndex` in tests), so the adjacency detection is fully
unit-testable with fixture arrivals.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from app.arrivals import ArrivalGroup, CrowdingHint
from app.stops import StopIndex

# Default adjacency window: a feeder train within this many minutes of your train
# counts as "back-to-back". Tunable via ``transfer_crowd_window_minutes`` in
# config; the issue's open question landed on ~2 min as the sensible default.
DEFAULT_CROWD_WINDOW_MINUTES = 2.0


class CrowdingConfigError(Exception):
    """A ``[[transfer_crowding]]`` block is malformed or names an unusable line."""


@dataclass(frozen=True)
class CrowdingRule:
    """One resolved transfer-crowding rule: a line to annotate + its feeders.

    ``station`` is the canonical complex name (matching
    :attr:`ArrivalGroup.station`); ``line`` the line whose trains get the hint;
    ``feeders`` the other lines whose arriving crowd packs it (sorted, de-duped,
    never containing ``line``).
    """

    station: str
    line: str
    feeders: tuple[str, ...]


def validated_crowd_window(config: dict[str, Any]) -> float:
    """Return ``transfer_crowd_window_minutes`` from config, validated non-negative.

    Raises :class:`CrowdingConfigError` on a negative or non-numeric value so a bad
    config is caught at the boundary rather than silently mis-flagging trains.
    """
    window = config.get("transfer_crowd_window_minutes", DEFAULT_CROWD_WINDOW_MINUTES)
    if isinstance(window, bool) or not isinstance(window, (int, float)) or window < 0:
        raise CrowdingConfigError(
            f"transfer_crowd_window_minutes must be a non-negative number, "
            f"got {window!r}."
        )
    return float(window)


def resolve_crowding_rules(
    config: dict[str, Any], *, index: StopIndex | None = None
) -> list[CrowdingRule]:
    """Resolve every ``[[transfer_crowding]]`` block to a :class:`CrowdingRule`.

    Validates that each block names a real station serving both ``line`` and every
    ``feeder`` (so a typo fails loudly, like the other config), that feeders are
    non-empty and exclude ``line``, and that no (station, line) pair repeats.
    Returns ``[]`` when none are configured. Pass a prebuilt ``index`` to keep
    resolution offline (tests); otherwise the vendored station data is used.
    """
    rule_cfgs = config.get("transfer_crowding", [])
    if not rule_cfgs:
        return []
    if index is None:
        index = StopIndex.from_csv()

    resolved: list[CrowdingRule] = []
    seen: set[tuple[str, str]] = set()
    for cfg in rule_cfgs:
        name = str(cfg.get("name", "")).strip()
        line = str(cfg.get("line", "")).strip()
        feeders_raw = cfg.get("feeders", [])
        if not name or not line:
            raise CrowdingConfigError(
                "A [[transfer_crowding]] block needs a 'name' (the transfer "
                "complex) and a 'line' (the line to annotate)."
            )
        if not isinstance(feeders_raw, (list, tuple)) or not feeders_raw:
            raise CrowdingConfigError(
                f"transfer_crowding {name!r} line {line!r}: 'feeders' must be a "
                f"non-empty list of the other lines that crowd it."
            )
        # De-dupe (order-preserving) and drop the annotated line if it snuck in.
        feeders = tuple(
            f for f in dict.fromkeys(str(x).strip() for x in feeders_raw) if f
        )
        if line in feeders:
            raise CrowdingConfigError(
                f"transfer_crowding {name!r}: 'line' {line!r} must not also be a "
                f"feeder of itself."
            )
        if not feeders:
            raise CrowdingConfigError(
                f"transfer_crowding {name!r} line {line!r}: no valid feeders given."
            )

        matches = index.stations_named(name)
        if not matches:
            raise CrowdingConfigError(
                f"transfer_crowding: unknown station name {name!r}."
            )
        canonical = matches[0].name
        served = {route for s in matches for route in s.routes}
        for needed in (line, *feeders):
            if needed not in served:
                raise CrowdingConfigError(
                    f"transfer_crowding {name!r}: line {needed!r} is not served "
                    f"there. Lines here: {sorted(served)}."
                )

        key = (canonical, line)
        if key in seen:
            raise CrowdingConfigError(
                f"Duplicate transfer_crowding rule for {canonical!r} line {line!r}."
            )
        seen.add(key)
        resolved.append(CrowdingRule(station=canonical, line=line, feeders=feeders))
    return resolved


def _hint(
    when: datetime, feeder_times: list[datetime], window: timedelta
) -> CrowdingHint | None:
    """Classify one train's arrival against the feeder arrival times.

    ``crowded`` if a feeder lands in ``[when - window, when]`` (just before, so its
    crowd is already on the platform); else ``beats_crowd`` if one lands in
    ``(when, when + window]`` (this train slips out ahead of it). A simultaneous
    feeder falls in the first window, so it reads as crowded.
    """
    if any(when - window <= f <= when for f in feeder_times):
        return "crowded"
    if any(when < f <= when + window for f in feeder_times):
        return "beats_crowd"
    return None


def annotate_crowding(
    groups: list[ArrivalGroup],
    rules: list[CrowdingRule],
    *,
    window_minutes: float = DEFAULT_CROWD_WINDOW_MINUTES,
) -> list[ArrivalGroup]:
    """Return ``groups`` with each rule's line tagged with a crowding hint (#28).

    For every rule, gathers the feeder lines' arrival times across the complex (any
    direction) and re-emits the rule's line groups with each arrival's ``crowding``
    set per :func:`_hint`. Groups not covered by a rule pass through unchanged.
    Pure and offline: a function of (groups, rules, window) only.
    """
    if not rules:
        return groups
    window = timedelta(minutes=window_minutes)

    # Feeder arrival times per rule: every feeder-line arrival at the complex,
    # regardless of direction (owner's call -- a crowd transfers either way).
    feeder_times: dict[tuple[str, str], list[datetime]] = {}
    for rule in rules:
        feeders = set(rule.feeders)
        feeder_times[(rule.station, rule.line)] = [
            a.arrival
            for g in groups
            if g.station == rule.station and g.line in feeders
            for a in g.arrivals
        ]

    by_line = {(r.station, r.line): r for r in rules}
    out: list[ArrivalGroup] = []
    for g in groups:
        key = (g.station, g.line)
        if key not in by_line:
            out.append(g)
            continue
        times = feeder_times[key]
        out.append(
            replace(
                g,
                arrivals=[
                    replace(a, crowding=_hint(a.arrival, times, window))
                    for a in g.arrivals
                ],
            )
        )
    return out
