#!/usr/bin/env python3
"""
fetch_teams.py — one-time helper to populate team IDs in pots.json.

Fetches the World Cup (competition code WC) team list from football-data.org v4,
prints every id<->name pair, then tries to auto-match each team in pots.json by
name (handling the known API spelling differences) and writes the IDs back.

Usage:
    FOOTBALL_DATA_TOKEN=xxxxx python3 fetch_teams.py            # match + write pots.json
    FOOTBALL_DATA_TOKEN=xxxxx python3 fetch_teams.py --print    # just list id<->name, don't write

The free tier includes the World Cup, but team data may only appear once the
draw/squads are published. If you get a 403/404 or an empty list, run again
closer to the tournament; you can also fill the IDs in pots.json by hand using
the printed list.
"""

import json
import os
import sys
import urllib.request
import urllib.error

API_BASE = "https://api.football-data.org/v4"
COMPETITION = "WC"
POTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pots.json")

# Map pots.json names -> the alternate spellings football-data.org might use.
# Matching is case-insensitive and ignores accents/punctuation (see normalize()).
NAME_ALIASES = {
    "Turkiye": ["Turkey", "Türkiye"],
    "Ivory Coast": ["Cote d'Ivoire", "Côte d'Ivoire", "Ivory Coast"],
    "Curacao": ["Curaçao", "Curacao"],
    "DR Congo": ["Congo DR", "DR Congo", "Democratic Republic of Congo",
                 "Congo (DR)", "DR Congo (Zaire)"],
    "United States": ["USA", "United States of America", "United States"],
    "South Korea": ["Korea Republic", "Republic of Korea", "South Korea"],
    "Czechia": ["Czech Republic", "Czechia"],
    "Bosnia and Herzegovina": ["Bosnia-Herzegovina", "Bosnia and Herzegovina",
                               "Bosnia & Herzegovina"],
    "Cape Verde": ["Cabo Verde", "Cape Verde"],
}


def normalize(s):
    """Lowercase, strip accents and non-alphanumerics for tolerant comparison."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())


def fetch_teams(token):
    url = f"{API_BASE}/competitions/{COMPETITION}/teams"
    req = urllib.request.Request(url, headers={"X-Auth-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            avail = resp.headers.get("X-Requests-Available")
            reset = resp.headers.get("X-RequestCounter-Reset")
            if avail is not None:
                print(f"API quota: {avail} requests left "
                      f"(resets in {reset or '?'}s).")
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 429:
            reset = e.headers.get("X-RequestCounter-Reset")
            sys.exit("Rate limited (429)." +
                     (f" Counter resets in {reset}s — try again then." if reset else ""))
        sys.exit(f"HTTP {e.code} fetching teams: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error fetching teams: {e}")
    return data.get("teams", [])


def main():
    token = os.environ.get("FOOTBALL_DATA_TOKEN")
    if not token:
        sys.exit("FOOTBALL_DATA_TOKEN env var is not set.")

    teams = fetch_teams(token)
    if not teams:
        print("WARNING: the API returned no teams for WC yet. "
              "Team data is usually published closer to the tournament.")
    print(f"\n=== {len(teams)} teams returned by the API ===")
    for t in sorted(teams, key=lambda x: x.get("name", "")):
        print(f"  {t.get('id'):>6}  {t.get('name')}  "
              f"(tla={t.get('tla')}, short={t.get('shortName')})")

    if "--print" in sys.argv:
        return

    # Build a normalized lookup of every API name + tla + shortName -> id.
    lookup = {}
    for t in teams:
        tid = t.get("id")
        for key in (t.get("name"), t.get("shortName"), t.get("tla")):
            if key:
                lookup[normalize(key)] = tid

    with open(POTS_PATH, "r", encoding="utf-8") as f:
        pots = json.load(f)

    matched, unmatched = 0, []
    for team in pots["teams"]:
        candidates = [team["name"]] + NAME_ALIASES.get(team["name"], [])
        found = None
        for cand in candidates:
            found = lookup.get(normalize(cand))
            if found is not None:
                break
        if found is not None:
            team["id"] = found
            matched += 1
        else:
            unmatched.append(team["name"])

    with open(POTS_PATH, "w", encoding="utf-8") as f:
        json.dump(pots, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\nMatched {matched}/{len(pots['teams'])} teams; wrote {POTS_PATH}")
    if unmatched:
        print("\n*** WARNING: these teams could not be matched (id left null). "
              "Fill them in by hand from the printed list above: ***")
        for name in unmatched:
            print(f"   - {name}")


if __name__ == "__main__":
    main()
