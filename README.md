# World Cup 2026 Fantasy Pool Tracker

A free, auto-updating leaderboard for our 7-player World Cup draft pool. It lives at a
public URL, is built for phones, and needs **no server and no login** for viewers.

- **GitHub Pages** serves a static `index.html` (the page everyone opens on their phone).
- **GitHub Actions** runs a Python script every 2 hours that pulls results from
  [football-data.org](https://www.football-data.org/) (free tier), recomputes the
  standings, and commits `standings.json` back to the repo.
- The page reads `standings.json` and renders the leaderboard, auto-refreshing itself
  every couple of minutes so an open tab stays current.

## Scoring

Each team scores points for the **furthest stage it reaches**, times its **pot multiplier**.

**Match points** (earned every round, group stage included):

| Result | Points |
|--------|:------:|
| Win    | 0.75   |
| Draw   | 0.25   |
| Loss   | 0      |

**Advance bonus** — the single furthest round a team reaches (does *not* stack per round):

| Furthest round | Bonus |
|----------------|:-----:|
| Round of 32    | 2     |
| Round of 16    | 3     |
| Quarterfinal   | 5     |
| Semifinal      | 7     |
| Final          | 10    |
| Champion       | 14    |

**Team points = (match points + advance bonus) × pot multiplier.** A team scores
nothing until it actually plays — no floor for simply being in the field. Deeper
runs and bigger underdogs are worth progressively more.

| Pot | Multiplier |
|-----|:----------:|
| 1   | ×1   |
| 2   | ×1.5 |
| 3   | ×2   |
| 4   | ×3   |

A player's score is the sum of their ~6 teams. Most points wins.

## One-time setup

### 1. Get a free API token
Register at <https://www.football-data.org/client/register>. The free tier includes the
FIFA World Cup (competition code `WC`) and allows ~10 calls/min — plenty, since the
workflow polls once per run.

### 2. Create a **public** repo and push these files
Keep it public so GitHub Actions and Pages stay free.

```
git init
git add .
git commit -m "World Cup 2026 pool tracker"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

Files in this repo:

| File                          | What it is |
|-------------------------------|------------|
| `index.html`                  | The mobile leaderboard (what you share). |
| `update_standings.py`         | Fetches results and writes `standings.json`. |
| `standings.json`              | Generated output the page reads. Committed by the bot. |
| `pots.json`                   | All 48 teams → pot tier + team ID. |
| `draft.json`                  | Team → player mapping (you fill in after the draft). |
| `fetch_teams.py`              | One-time helper to fill team IDs in `pots.json`. |
| `.github/workflows/update.yml`| The scheduled GitHub Action. |

### 3. Add the API token as a repo secret
**Settings → Secrets and variables → Actions → New repository secret**
- Name: `FOOTBALL_DATA_TOKEN`
- Value: your token

Never hardcode the token in any file.

### 4. Enable GitHub Pages
**Settings → Pages → Build and deployment → Source: "Deploy from a branch"**, branch
`main`, folder `/ (root)`. After a minute you'll get a public URL like
`https://<you>.github.io/<repo>/` — **this is the link you share with the league.**

### 5. Fill in team IDs in `pots.json`
The `id` fields start as `null`. Once the token is set, run the helper:

```
FOOTBALL_DATA_TOKEN=xxxxx python3 fetch_teams.py
```

It prints every team's `id ↔ name` from the API and auto-fills the IDs by name
(handling the known spelling differences: Turkiye/Turkey, Ivory Coast/Côte d'Ivoire,
Curacao/Curaçao, DR Congo/Congo DR, United States/USA, South Korea/Korea Republic,
Czechia/Czech Republic, etc.). Any team it can't match is left `null` with a printed
warning — fill those in by hand from the list.

> Note: football-data.org may not publish the WC team list until closer to the
> tournament/draw. If `fetch_teams.py` returns no teams, try again later, or fill the
> IDs by hand once they're available. Commit `pots.json` after editing.

### 6. Fill in the draft in `draft.json`
After the snake draft, map each drafted team to its player. Keys can be a team **ID**
(preferred) or a team **name** exactly as in `pots.json`:

```json
{
  "Spain": "Drew",
  "724":   "Eriku",
  "manualOverrides": {}
}
```

Players: **Drew, Eriku, Rain, Andy, Dev, Gav, Rea**. 42 of 48 teams get drafted.

`manualOverrides` lets you force a team's furthest stage if the API ever mislabels
something — key is a team id/name, value is a stage name:
`GROUP_STAGE | LAST_32 | LAST_16 | QUARTER_FINALS | SEMI_FINALS | FINAL | CHAMPION`.

### 7. Run it
Commit your `pots.json` and `draft.json` changes, then go to the **Actions** tab and
click **Run workflow** on "Update standings" to generate the first real `standings.json`.
After that it runs automatically every 2 hours. Open your Pages URL on a phone to check it.

## Local testing

Run the scorer against a saved/mock matches file without touching the API:

```
python3 update_standings.py --mock mock_matches.json
```

Preview the page locally:

```
python3 -m http.server 8000      # then open http://localhost:8000
```

## How "furthest stage" is decided

A team is credited with a stage as soon as it **appears in a fixture at that stage** —
to be in a Round-of-16 match it must have advanced out of the Round of 32. The
**Champion** bonus (10 base) is only awarded once the Final is `FINISHED` and a winner is
recorded. Before teams are slotted into a knockout bracket, those fixtures carry "TBD"
placeholders (no team ID) and are ignored, so everyone correctly sits at 0 until results
come in.
