#!/usr/bin/env python3
"""
update_standings.py — recompute the fantasy-pool standings from live World Cup
results and write standings.json.

Scoring (see README): each team scores points for the FURTHEST stage it reaches,
multiplied by its pot multiplier.

    stage points : Round of 32 = 1, Round of 16 = 2, QF = 3, SF = 5,
                   Final = 7, Champion = 10  (out in group stage = 0)
    pot multiplier : Pot1 x1, Pot2 x1.5, Pot3 x2, Pot4 x3
    team points = stage points * pot multiplier
    player score = sum of their teams' points

Reads:  pots.json (team -> pot, id), draft.json (team -> player)
Writes: standings.json

Run:    FOOTBALL_DATA_TOKEN=xxxxx python3 update_standings.py
        python3 update_standings.py --mock mock_matches.json   # offline test
"""

import json
import os
import sys
import datetime
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
API_BASE = "https://api.football-data.org/v4"
COMPETITION = "WC"

# Furthest-stage BONUS (as the API reports it) -> (rank, label, bonus points).
# This stacks ON TOP of per-match win/draw points. Group stage is 0 — being in
# the field earns nothing; you score by winning matches and by advancing.
# Champion is derived from the FINAL winner, not a stage value. THIRD_PLACE
# shares the SEMI_FINALS tier; it never beats the FINAL/CHAMPION tiers.
# (rank, label) per stage. The actual POINTS come from STAGE_POINTS_BY_POT below,
# because the reward for reaching a stage depends on the team's pot.
STAGE_TABLE = {
    "GROUP_STAGE":     (0, "Group Stage"),
    "LAST_32":         (1, "Round of 32"),
    "LAST_16":         (2, "Round of 16"),
    "QUARTER_FINALS":  (3, "Quarterfinal"),
    "SEMI_FINALS":     (4, "Semifinal"),
    "THIRD_PLACE":     (4, "Semifinal"),   # 3rd-place game = reached SF
    "FINAL":           (5, "Final"),
}
CHAMPION_RANK = 6
CHAMPION_LABEL = "Champion"

# Stage points indexed by pot, then by rank-1 (R32..Champion = indices 0..5).
# A weaker pot earns a big premium for the SURPRISING early rounds, and that
# premium fades toward the final (a final is a final). Tuned by Monte-Carlo over
# the actual draft so strong teams score most, underdog runs pay off, and a
# Pot-4 finalist still sits below a Pot-1 champion (no instant win).
#                     R32  R16  QF   SF  Final Champ
STAGE_POINTS_BY_POT = {
    1: [ 4,  8, 15, 25, 41, 62],
    2: [ 8, 14, 22, 32, 48, 66],
    3: [17, 26, 35, 46, 59, 77],
    4: [28, 40, 50, 59, 67, 87],
}

# Per-match result points, awarded in EVERY round (group stage included),
# before the pot multiplier. A knockout tie decided on penalties counts as a
# WIN for whoever advanced (nobody draws their way out of a knockout).
WIN_POINTS = 2
DRAW_POINTS = 1
LOSS_POINTS = 0

# Stages we treat as "appeared => advanced". A team listed in a LAST_16 fixture
# has, by definition, advanced out of the Round of 32, so the mere existence of
# the fixture proves the stage was reached. We still require FINISHED matches to
# award the CHAMPION bonus (need a confirmed winner).
KNOCKOUT_STAGES = {"LAST_32", "LAST_16", "QUARTER_FINALS",
                   "SEMI_FINALS", "THIRD_PLACE", "FINAL"}


def match_result_points(matches, tracked_ids):
    """
    Tally FINISHED-match results per tracked team.
    Returns {team_id: {"win","draw","loss","matchPoints"}} (matchPoints is the
    raw, pre-multiplier sum). A penalty-shootout tie is resolved to the side
    that advanced via the penalties tally.
    """
    tally = {tid: {"win": 0, "draw": 0, "loss": 0, "matchPoints": 0.0}
             for tid in tracked_ids}

    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        home = (m.get("homeTeam") or {}).get("id")
        away = (m.get("awayTeam") or {}).get("id")
        if home not in tracked_ids and away not in tracked_ids:
            continue
        score = m.get("score") or {}
        winner = score.get("winner")

        # Resolve penalty-shootout "draws" to whoever advanced.
        if winner == "DRAW" and score.get("duration") == "PENALTY_SHOOTOUT":
            pens = score.get("penalties") or {}
            ph, pa = pens.get("home"), pens.get("away")
            if isinstance(ph, int) and isinstance(pa, int) and ph != pa:
                winner = "HOME_TEAM" if ph > pa else "AWAY_TEAM"

        for tid, is_home in ((home, True), (away, False)):
            if tid not in tracked_ids:
                continue
            if winner == "DRAW":
                tally[tid]["draw"] += 1
                tally[tid]["matchPoints"] += DRAW_POINTS
            elif (winner == "HOME_TEAM") == is_home:
                tally[tid]["win"] += 1
                tally[tid]["matchPoints"] += WIN_POINTS
            else:
                tally[tid]["loss"] += 1
                tally[tid]["matchPoints"] += LOSS_POINTS

    return tally


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_matches(token):
    url = f"{API_BASE}/competitions/{COMPETITION}/matches"
    req = urllib.request.Request(url, headers={"X-Auth-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            # The API reports remaining quota on every response (see docs:
            # X-Requests-Available = calls left, X-RequestCounter-Reset =
            # seconds until the counter resets). Log it so a near-limit run is
            # visible; one poll per run keeps us comfortably inside the free
            # tier's ~10 calls/min.
            avail = resp.headers.get("X-Requests-Available")
            reset = resp.headers.get("X-RequestCounter-Reset")
            if avail is not None:
                print(f"API quota: {avail} requests left "
                      f"(resets in {reset or '?'}s).")
            return json.loads(resp.read().decode("utf-8")).get("matches", [])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 429:
            reset = e.headers.get("X-RequestCounter-Reset")
            hint = (f" The counter resets in {reset}s." if reset else "")
            sys.exit(f"Rate limited (429). Free tier allows ~10 calls/min and "
                     f"this run does a single poll, so just try again shortly."
                     f"{hint}")
        sys.exit(f"HTTP {e.code} fetching matches: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error fetching matches: {e}")


def team_ids_in(match):
    home = (match.get("homeTeam") or {}).get("id")
    away = (match.get("awayTeam") or {}).get("id")
    return [t for t in (home, away) if t is not None]


def compute_furthest_stages(matches, tracked_ids):
    """
    Return {team_id: (rank, label)} for the furthest stage each tracked team
    reached. A team is credited with a stage if it appears in a fixture at that
    stage. The FINAL winner is upgraded to Champion. Stage POINTS are looked up
    later per pot (see STAGE_POINTS_BY_POT).
    """
    best = {}  # team_id -> (rank, label)

    for m in matches:
        info = STAGE_TABLE.get(m.get("stage"))
        if info is None:
            continue
        for tid in team_ids_in(m):
            if tid not in tracked_ids:
                continue
            if tid not in best or info[0] > best[tid][0]:
                best[tid] = info

    # Champion: winner of a FINISHED final.
    for m in matches:
        if m.get("stage") != "FINAL" or m.get("status") != "FINISHED":
            continue
        winner = (m.get("score") or {}).get("winner")
        winner_id = None
        if winner == "HOME_TEAM":
            winner_id = (m.get("homeTeam") or {}).get("id")
        elif winner == "AWAY_TEAM":
            winner_id = (m.get("awayTeam") or {}).get("id")
        if winner_id in tracked_ids:
            best[winner_id] = (CHAMPION_RANK, CHAMPION_LABEL)

    return best


def main():
    token = os.environ.get("FOOTBALL_DATA_TOKEN")

    # --mock <file> loads a saved matches payload instead of hitting the API.
    mock_path = None
    if "--mock" in sys.argv:
        mock_path = sys.argv[sys.argv.index("--mock") + 1]

    pots = load_json(os.path.join(HERE, "pots.json"))
    draft = load_json(os.path.join(HERE, "draft.json"))

    # team_id -> {name, pot}, and a name->id map for draft entries given by name.
    teams_by_id, name_to_id, missing_ids = {}, {}, []
    for t in pots["teams"]:
        if t["id"] is None:
            missing_ids.append(t["name"])
            continue
        teams_by_id[t["id"]] = {"name": t["name"], "pot": t["pot"]}
        name_to_id[t["name"].lower()] = t["id"]
    if missing_ids:
        print("WARNING: these teams have id=null in pots.json and will be "
              "skipped until you fill their IDs: " + ", ".join(missing_ids),
              file=sys.stderr)

    # draft.json maps team (id or name) -> player. Normalize keys to team IDs.
    overrides = draft.get("manualOverrides", {})
    team_to_player = {}
    for key, player in draft.items():
        if key == "manualOverrides" or key.startswith("_"):
            continue
        tid = None
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            tid = int(key)
        elif isinstance(key, str):
            tid = name_to_id.get(key.lower())
        if tid is None:
            print(f"WARNING: draft entry '{key}' -> '{player}' did not match "
                  f"any team id/name in pots.json; skipping.", file=sys.stderr)
            continue
        team_to_player[tid] = player

    # Fetch matches (live or mock).
    if mock_path:
        matches = load_json(mock_path).get("matches", [])
    else:
        if not token:
            sys.exit("FOOTBALL_DATA_TOKEN is not set (and no --mock given).")
        matches = fetch_matches(token)

    tracked_ids = set(teams_by_id.keys())
    furthest = compute_furthest_stages(matches, tracked_ids)
    results = match_result_points(matches, tracked_ids)

    # Apply manual overrides (force a team's furthest stage by stage name).
    # overrides: {"<teamId or name>": "FINAL" | "CHAMPION" | "QUARTER_FINALS" ...}
    for key, stage_name in overrides.items():
        tid = int(key) if str(key).isdigit() else name_to_id.get(str(key).lower())
        if tid is None:
            print(f"WARNING: override key '{key}' did not match a team.",
                  file=sys.stderr)
            continue
        if stage_name == "CHAMPION":
            furthest[tid] = (CHAMPION_RANK, CHAMPION_LABEL)
        elif stage_name in STAGE_TABLE:
            furthest[tid] = STAGE_TABLE[stage_name]
        else:
            print(f"WARNING: override stage '{stage_name}' for '{key}' is not "
                  f"a known stage; ignoring.", file=sys.stderr)

    # Build per-player breakdowns.
    # Team points = match win/draw points (FLAT, same for every pot)
    #               + stage points (looked up per pot from STAGE_POINTS_BY_POT).
    # Match points are flat so routine group wins aren't inflated; the per-pot
    # stage points reward an underdog for going FAR, with the premium fading
    # toward the final so no single deep run auto-wins the pool.
    # No floor: a team that hasn't played, or has only lost, scores 0.
    players = {}  # name -> {teams: [...], totalPoints, teamsAdvancedCount}
    for tid, player in team_to_player.items():
        meta = teams_by_id.get(tid)
        if meta is None:
            continue  # team drafted but id missing from pots.json
        pot = meta["pot"]
        stage = furthest.get(tid, STAGE_TABLE["GROUP_STAGE"])
        rank, label = stage[0], stage[1]
        # Stage points: 0 in the group stage, else the per-pot value for the
        # furthest knockout round reached (rank 1..6 -> index 0..5).
        stage_pts = STAGE_POINTS_BY_POT[pot][rank - 1] if rank >= 1 else 0
        rec = results.get(tid, {"win": 0, "draw": 0, "loss": 0, "matchPoints": 0.0})
        match_pts = rec["matchPoints"]
        pts = round(match_pts + stage_pts, 2)
        entry = players.setdefault(
            player, {"name": player, "teams": [], "totalPoints": 0.0,
                     "teamsAdvancedCount": 0})
        entry["teams"].append({
            "name": meta["name"], "pot": pot,
            "furthestStage": label, "stageRank": rank,
            "wins": rec["win"], "draws": rec["draw"], "losses": rec["loss"],
            "matchPoints": round(match_pts, 2), "stagePoints": stage_pts,
            "points": pts,
        })
        entry["totalPoints"] = round(entry["totalPoints"] + pts, 2)
        if rank > 0:  # advanced past the group stage
            entry["teamsAdvancedCount"] += 1

    # Sort each player's teams by points desc, then rank players.
    player_list = []
    for entry in players.values():
        entry["teams"].sort(key=lambda t: (-t["points"], -t["pot"], t["name"]))
        player_list.append(entry)
    player_list.sort(key=lambda p: (-p["totalPoints"], p["name"]))

    # Dense ranking with ties (1,1,3...).
    prev_pts, prev_rank = None, 0
    for i, p in enumerate(player_list, start=1):
        if p["totalPoints"] != prev_pts:
            prev_rank = i
            prev_pts = p["totalPoints"]
        p["rank"] = prev_rank

    # Upcoming matches (not yet finished), trimmed for the front-end.
    upcoming = []
    for m in matches:
        if m.get("status") == "FINISHED":
            continue
        home = (m.get("homeTeam") or {}).get("name") or "TBD"
        away = (m.get("awayTeam") or {}).get("name") or "TBD"
        upcoming.append({
            "utcDate": m.get("utcDate"),
            "stage": m.get("stage"),
            "status": m.get("status"),
            "homeTeam": home, "awayTeam": away,
        })
    upcoming.sort(key=lambda x: x.get("utcDate") or "")

    finished_count = sum(1 for m in matches if m.get("status") == "FINISHED")

    standings = {
        "lastUpdated": datetime.datetime.now(datetime.timezone.utc)
                       .isoformat().replace("+00:00", "Z"),
        "competition": "FIFA World Cup 2026",
        "totalMatches": len(matches),
        "finishedMatches": finished_count,
        "tournamentStarted": finished_count > 0,
        "players": player_list,
        "upcomingMatches": upcoming[:32],
        "scoringLegend": {
            "matchPoints": {"Win": WIN_POINTS, "Draw": DRAW_POINTS, "Loss": 0},
            "stagePointsByPot": {str(pot): vals
                                 for pot, vals in STAGE_POINTS_BY_POT.items()},
            "stageOrder": ["Round of 32", "Round of 16", "Quarterfinal",
                           "Semifinal", "Final", "Champion"],
            "note": "Match win/draw points are flat for every team. Stage points "
                    "depend on the team's pot — weaker pots earn more for the "
                    "same round, with the premium fading toward the final.",
        },
        "warnings": ([f"{len(missing_ids)} team(s) missing IDs in pots.json"]
                     if missing_ids else []),
    }

    out_path = os.path.join(HERE, "standings.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(standings, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Wrote {out_path}: {len(player_list)} players, "
          f"{finished_count}/{len(matches)} matches finished.")


if __name__ == "__main__":
    main()
