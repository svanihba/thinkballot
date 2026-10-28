"""The official statewide ballot measure results feed, and a strict parser for it.

Source: California Secretary of State, the JSON API behind https://electionresults.sos.ca.gov/

    GET https://api.sos.ca.gov/returns/ballot-measures
    200, content-type: application/json; charset=UTF-8   (checked 2026-10-27 with one request)

    {
      "raceTitle": "Ballot Measures - Statewide Results",
      "Reporting": "0.1% (21 of 23,863) precincts reporting",
      "ReportingTime": "October 27, 2026, 2:58 p.m.",          <- Pacific time, no zone given
      "ballot-measures": [
        {"Name": "Authorizes Bonds For Housing Affordability Programs. Legislative Statute.",
         "Number": "01", "yesVotes": "211", "yesPercent": "23.7", "noVotes": "681", "noPercent": "76.3"},
        ...
      ]
    }

Every value is a string. The feed names no election and no date other than ReportingTime, and the
Secretary of State publishes test numbers in the same format before election night (on 2026-10-27 it
already listed this election's 14 propositions with made-up counts). So a feed is accepted only when:

- ReportingTime is after the polls close on election day (8 p.m. Pacific) and within RESULTS_WINDOW_DAYS;
- every entry parses exactly (whole numbers, one-decimal percentages that agree with the counts);
- every number matches a proposition on this ballot AND its name starts with that proposition's official
  title (so another election's "Prop 1" is never shown as ours).

Anything else is rejected as a whole: nothing new is shown, and the last good copy stays.
"""

import datetime as dt
import json
import re
from zoneinfo import ZoneInfo

SOURCE_URL = "https://api.sos.ca.gov/returns/ballot-measures"
SOURCE_PAGE = "https://electionresults.sos.ca.gov/returns/ballot-measures"
SOURCE_NAME = "California Secretary of State"
PACIFIC = ZoneInfo("America/Los_Angeles")
POLLS_CLOSE = dt.time(20, 0)
RESULTS_WINDOW_DAYS = 120  # certification is 38 days after the election; keep a margin, then stop
MAX_BYTES = 512 * 1024

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"])}
TIME_RE = re.compile(r"^(?P<month>[A-Z][a-z]+) (?P<day>\d{1,2}), (?P<year>\d{4}),? "
                     r"(?P<hour>\d{1,2}):(?P<minute>\d{2}) ?(?P<ampm>a\.m\.|p\.m\.|am|pm|AM|PM|A\.M\.|P\.M\.)$")
REPORTING_RE = re.compile(r"^(?P<pct>\d{1,3}(?:\.\d)?)% \((?P<done>\d{1,3}(?:,\d{3})*|\d+) of "
                          r"(?P<total>\d{1,3}(?:,\d{3})*|\d+)\) precincts reporting$")
COUNT_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)$")
PERCENT_RE = re.compile(r"^\d{1,3}(?:\.\d{1,2})?$")
NUMBER_RE = re.compile(r"^\d{1,3}$")


class FeedError(ValueError):
    """The feed is not in the expected format, or is not this election's. Nothing from it is used."""


def polls_close(election_date):
    """Election day, 8 p.m. Pacific, as an aware datetime. election_date: "2026-11-03"."""
    return dt.datetime.combine(dt.date.fromisoformat(election_date), POLLS_CLOSE, tzinfo=PACIFIC)


def in_window(now, election_date):
    """True from the polls closing until RESULTS_WINDOW_DAYS later: the only time results are fetched."""
    start = polls_close(election_date)
    return start <= now <= start + dt.timedelta(days=RESULTS_WINDOW_DAYS)


def parse_time(text):
    m = TIME_RE.match(text) if isinstance(text, str) else None
    if not m or m["month"] not in MONTHS:
        raise FeedError(f"unexpected ReportingTime {text!r}")
    hour = int(m["hour"])
    if not 1 <= hour <= 12:
        raise FeedError(f"unexpected ReportingTime {text!r}")
    hour = hour % 12 + (12 if m["ampm"].lower().startswith("p") else 0)
    try:
        return dt.datetime(int(m["year"]), MONTHS[m["month"]], int(m["day"]), hour, int(m["minute"]), tzinfo=PACIFIC)
    except ValueError as exc:
        raise FeedError(f"unexpected ReportingTime {text!r}") from exc


def _count(value, what):
    if not isinstance(value, str) or not COUNT_RE.match(value):
        raise FeedError(f"unexpected {what} {value!r}")
    return int(value.replace(",", ""))


def _percent(value, what):
    if not isinstance(value, str) or not PERCENT_RE.match(value) or float(value) > 100:
        raise FeedError(f"unexpected {what} {value!r}")
    return float(value)


def _words(text):
    """Lowercase words for comparing titles: "Limit's Voters'" and "Limits Voters'" compare equal."""
    return re.sub(r"[^a-z0-9% ]+", "", text.lower().replace("-", " ")).split()


def name_matches(feed_name, title):
    """The feed's name is the official title followed by the measure type ("... Initiative Statute.")."""
    want, got = _words(title), _words(feed_name)
    return bool(want) and got[:len(want)] == want


def parse(body, election_date, measures):
    """Strictly parse one feed response (bytes or str) into results for this election.

    measures: {"1": "Authorizes Bonds for Housing Affordability Programs.", ...}  (number -> official title)
    Returns {"as_of": iso, "reporting": {...} or None, "measures": {"1": {...}}}; raises FeedError.
    """
    if isinstance(body, bytes):
        if len(body) > MAX_BYTES:
            raise FeedError("response too large")
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FeedError("not UTF-8") from exc
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise FeedError("not JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("ballot-measures"), list):
        raise FeedError("no ballot-measures list")
    if data.get("raceTitle") != "Ballot Measures - Statewide Results":
        raise FeedError(f"unexpected raceTitle {data.get('raceTitle')!r}")

    as_of = parse_time(data.get("ReportingTime"))
    if not in_window(as_of, election_date):
        raise FeedError(f"ReportingTime {as_of.isoformat()} is not after the {election_date} polls closed "
                        "(test data or another election)")

    reporting = None
    if "Reporting" in data:
        m = REPORTING_RE.match(data["Reporting"]) if isinstance(data["Reporting"], str) else None
        if not m:
            raise FeedError(f"unexpected Reporting {data['Reporting']!r}")
        done, total = int(m["done"].replace(",", "")), int(m["total"].replace(",", ""))
        if total == 0 or done > total:
            raise FeedError(f"unexpected Reporting {data['Reporting']!r}")
        reporting = {"percent": float(m["pct"]), "precincts": done, "precincts_total": total,
                     "text": data["Reporting"]}

    out, seen = {}, set()
    for entry in data["ballot-measures"]:
        if not isinstance(entry, dict):
            raise FeedError("entry is not an object")
        raw_number = entry.get("Number")
        if not isinstance(raw_number, str) or not NUMBER_RE.match(raw_number):
            raise FeedError(f"unexpected Number {raw_number!r}")
        number = str(int(raw_number))
        if number in seen:
            raise FeedError(f"Prop {number} listed twice")
        seen.add(number)
        if number not in measures:
            raise FeedError(f"Prop {number} is not on this ballot (another election?)")
        if not isinstance(entry.get("Name"), str) or not name_matches(entry["Name"], measures[number]):
            raise FeedError(f"Prop {number} name {entry.get('Name')!r} does not match its official title")
        yes, no = _count(entry.get("yesVotes"), "yesVotes"), _count(entry.get("noVotes"), "noVotes")
        yes_pct, no_pct = _percent(entry.get("yesPercent"), "yesPercent"), _percent(entry.get("noPercent"), "noPercent")
        total = yes + no
        if total:
            # The percentages must be the counts' own shares (rounded by the SoS to one decimal).
            if abs(yes_pct - 100 * yes / total) > 0.06 or abs(no_pct - 100 * no / total) > 0.06:
                raise FeedError(f"Prop {number} percentages do not match its counts")
        elif yes_pct or no_pct:
            raise FeedError(f"Prop {number} has percentages but no votes")
        if not total:
            continue  # no votes counted yet: nothing to show for this one
        out[number] = {"number": number, "name": entry["Name"], "yes_votes": yes, "no_votes": no,
                       "yes_percent": entry["yesPercent"], "no_percent": entry["noPercent"]}
    if not out:
        raise FeedError("no votes counted yet")
    return {"as_of": as_of.isoformat(), "reporting": reporting, "measures": out}
