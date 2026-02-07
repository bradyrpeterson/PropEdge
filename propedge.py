"""
PropEdge NBA — Automated Player Prop Analyzer
==============================================
Data sources:
  - The Odds API  → live sportsbook player prop lines (free tier: 500 req/mo)
  - nba_api       → real NBA.com game logs (free, no key needed)

Usage:
  1. pip install -r requirements.txt
  2. Open this file, paste your Odds API key on line 27
  3. python propedge.py
  4. Open the generated HTML file in your browser

That's it. Everything else is automatic.
"""

import os, sys, json, time, statistics
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from collections import defaultdict

# ============================================================================
#  PASTE YOUR API KEY HERE (get free at https://the-odds-api.com)
# ============================================================================
load_dotenv()
ODDS_API_KEY = os.getenv("API_KEY")
print(f"DEBUG KEY: [{ODDS_API_KEY}]")
# ============================================================================

import requests
import pandas as pd
import numpy as np

# nba_api imports (free — pulls from NBA.com, no key needed)
from nba_api.stats.static import players as nba_players  # type: ignore
from nba_api.stats.endpoints import playergamelog  # type: ignore

# ---------------------------------------------------------------------------
#  CONFIG
# ---------------------------------------------------------------------------
ODDS_BASE = "https://api.the-odds-api.com/v4"
SEASON = "2025-26"            # nba_api format
SEASON_YEAR = 2025            # first year of season
NBA_API_DELAY = 0.7           # seconds between nba_api calls (rate limit)
BOOKMAKER_PRIORITY = ["draftkings", "fanduel", "betmgm", "caesars"]

PROP_MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_steals",
    "player_blocks",
    "player_points_rebounds_assists",
    "player_points_rebounds",
    "player_points_assists",
    "player_rebounds_assists",
]

MARKET_LABELS = {
    "player_points": "Points",
    "player_rebounds": "Rebounds",
    "player_assists": "Assists",
    "player_steals": "Steals",
    "player_blocks": "Blocks",
    "player_points_rebounds_assists": "Pts+Reb+Ast",
    "player_points_rebounds": "Pts+Reb",
    "player_points_assists": "Pts+Ast",
    "player_rebounds_assists": "Reb+Ast",
}

# Map Odds API market keys → nba_api stat columns
MARKET_STAT_COLS = {
    "player_points": ["PTS"],
    "player_rebounds": ["REB"],
    "player_assists": ["AST"],
    "player_steals": ["STL"],
    "player_blocks": ["BLK"],
    "player_points_rebounds_assists": ["PTS", "REB", "AST"],
    "player_points_rebounds": ["PTS", "REB"],
    "player_points_assists": ["PTS", "AST"],
    "player_rebounds_assists": ["REB", "AST"],
}


# ---------------------------------------------------------------------------
#  STEP 1 — Fetch today's NBA games from The Odds API
# ---------------------------------------------------------------------------
def fetch_todays_games():
    """Get NBA events for today."""
    print("\n📡 Fetching today's NBA games...")
    url = f"{ODDS_BASE}/sports/basketball_nba/events"
    params = {"apiKey": ODDS_API_KEY}
    r = requests.get(url, params=params)
    r.raise_for_status()
    games = r.json()

    # Filter to today (API returns upcoming so may include tomorrow)
    today_str = date.today().isoformat()
    todays = [g for g in games if g["commence_time"][:10] == today_str]

    # If nothing today, take all upcoming (user may be running day-before)
    if not todays:
        todays = games[:12]  # cap at 12 games

    for g in todays:
        t = datetime.fromisoformat(g["commence_time"].replace("Z", "+00:00"))
        print(f"   {g['away_team']} @ {g['home_team']}  —  {t.strftime('%I:%M %p ET')}")
    print(f"   ✅ {len(todays)} games found")
    return todays


# ---------------------------------------------------------------------------
#  STEP 2 — Fetch player props for each game
# ---------------------------------------------------------------------------
def fetch_all_props(games):
    """For each game, pull player props from The Odds API."""
    print("\n📡 Fetching player prop lines...")
    all_props = []  # list of dicts

    for i, game in enumerate(games):
        matchup = f"{game['away_team']} @ {game['home_team']}"
        print(f"   [{i+1}/{len(games)}] {matchup}...", end=" ", flush=True)

        url = f"{ODDS_BASE}/sports/basketball_nba/events/{game['id']}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "oddsFormat": "american",
            "markets": ",".join(PROP_MARKETS),
        }

        try:
            r = requests.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"⚠ {e}")
            continue

        bookmakers = data.get("bookmakers", [])
        # Pick best bookmaker
        book = None
        for pref in BOOKMAKER_PRIORITY:
            book = next((b for b in bookmakers if b["key"] == pref), None)
            if book:
                break
        if not book and bookmakers:
            book = bookmakers[0]
        if not book:
            print("no lines")
            continue

        count = 0
        for mkt in book.get("markets", []):
            market_key = mkt["key"]
            if market_key not in MARKET_STAT_COLS:
                continue
            # Group Over outcomes by player
            for outcome in mkt["outcomes"]:
                if outcome["name"] != "Over":
                    continue
                player_name = outcome.get("description", "")
                if not player_name:
                    continue
                line = outcome.get("point")
                if line is None:
                    continue
                over_price = outcome.get("price", -110)

                all_props.append({
                    "player": player_name,
                    "market": market_key,
                    "market_label": MARKET_LABELS.get(market_key, market_key),
                    "line": float(line),
                    "over_odds": over_price,
                    "matchup": matchup,
                    "home_team": game["home_team"],
                    "away_team": game["away_team"],
                    "bookmaker": book["title"],
                })
                count += 1

        print(f"{count} props")
        time.sleep(0.3)

    print(f"   ✅ {len(all_props)} total prop lines collected")
    return all_props


# ---------------------------------------------------------------------------
#  STEP 3 — Pull real game logs from NBA.com via nba_api
# ---------------------------------------------------------------------------
_player_id_cache = {}

def _find_player_id(name):
    """Search nba_api for a player by name, return id or None."""
    if name in _player_id_cache:
        return _player_id_cache[name]

    all_p = nba_players.get_players()
    # Exact match first
    match = [p for p in all_p if p["full_name"].lower() == name.lower()]
    if not match:
        # Partial / fuzzy
        parts = name.lower().split()
        match = [p for p in all_p if all(pt in p["full_name"].lower() for pt in parts)]
    if not match:
        # Last name only
        ln = name.split()[-1].lower()
        match = [p for p in all_p if p["last_name"].lower() == ln]

    pid = match[0]["id"] if match else None
    _player_id_cache[name] = pid
    return pid


_gamelog_cache = {}

def get_game_logs(player_name, num_games=15):
    """Return last N game log rows for a player as list of dicts."""
    if player_name in _gamelog_cache:
        return _gamelog_cache[player_name][:num_games]

    pid = _find_player_id(player_name)
    if pid is None:
        _gamelog_cache[player_name] = []
        return []

    time.sleep(NBA_API_DELAY)
    try:
        gl = playergamelog.PlayerGameLog(
            player_id=pid,
            season=SEASON,
            season_type_all_star="Regular Season",
        )
        df = gl.get_data_frames()[0]
    except Exception as e:
        print(f"      ⚠ nba_api error for {player_name}: {e}")
        _gamelog_cache[player_name] = []
        return []

    # df columns: GAME_DATE, MATCHUP, WL, MIN, PTS, REB, AST, STL, BLK, ...
    logs = df.head(num_games).to_dict("records")
    _gamelog_cache[player_name] = logs
    return logs[:num_games]


# ---------------------------------------------------------------------------
#  STEP 4 — Analyze each prop
# ---------------------------------------------------------------------------
def analyze_prop(prop, near_threshold=1.5, num_games=10):
    """
    Given a prop dict and game logs, compute:
      hits, nears, avg_margin, std_dev, confidence_score, details[]
    """
    logs = get_game_logs(prop["player"], num_games=num_games + 5)
    if not logs:
        return None

    stat_cols = MARKET_STAT_COLS[prop["market"]]
    line = prop["line"]

    details = []
    for g in logs[:num_games]:
        val = sum(g.get(c, 0) or 0 for c in stat_cols)
        margin = val - line
        if margin > 0:
            result = "HIT"
        elif margin >= -near_threshold:
            result = "NEAR"
        else:
            result = "MISS"
        details.append({
            "date": g.get("GAME_DATE", ""),
            "matchup": g.get("MATCHUP", ""),
            "minutes": g.get("MIN", 0),
            "value": val,
            "margin": round(margin, 1),
            "result": result,
        })

    if not details:
        return None

    margins = [d["margin"] for d in details]
    hits = sum(1 for m in margins if m > 0)
    nears = sum(1 for m in margins if -near_threshold <= m <= 0)
    n = len(details)
    avg_margin = sum(margins) / n
    std_dev = (sum((m - avg_margin) ** 2 for m in margins) / n) ** 0.5

    # Confidence score (0-100)
    hit_rate = hits / n
    near_rate = nears / n
    consistency = max(0, 1 - std_dev / 10)
    avg_norm = min(1, max(0, (avg_margin + 10) / 20))
    score = hit_rate * 40 + near_rate * 15 + avg_norm * 25 + consistency * 20

    # Last-5 trend
    last5_margins = margins[:5]
    last5_avg = sum(last5_margins) / len(last5_margins) if last5_margins else 0

    return {
        "hits": hits,
        "nears": nears,
        "games": n,
        "avg_margin": round(avg_margin, 2),
        "std_dev": round(std_dev, 2),
        "score": round(score, 1),
        "hit_rate": round(hit_rate * 100, 1),
        "last5_avg": round(last5_avg, 2),
        "details": details,
    }


# ---------------------------------------------------------------------------
#  STEP 5 — Run full pipeline
# ---------------------------------------------------------------------------
def run_analysis():
    """Main pipeline: games → props → stats → analysis → HTML."""
    print("=" * 60)
    print("⚡ PropEdge NBA — Player Prop Analyzer")
    print(f"   Date: {date.today().strftime('%A, %B %d, %Y')}")
    print(f"   Season: {SEASON}")
    print("=" * 60)

    if ODDS_API_KEY == "YOUR_ODDS_API_KEY_HERE":
        print("\n❌ ERROR: You need to set your Odds API key!")
        print("   Open propedge.py and paste your key on line 27.")
        print("   Get a free key at: https://the-odds-api.com")
        sys.exit(1)

    # 1. Games
    games = fetch_todays_games()
    if not games:
        print("\n❌ No games found. Run this on a game day.")
        sys.exit(1)

    # 2. Props
    props = fetch_all_props(games)
    if not props:
        print("\n❌ No props found. Lines may not be posted yet.")
        sys.exit(1)

    # 3. Analyze each prop
    print(f"\n🔬 Analyzing {len(props)} props (pulling NBA.com game logs)...")
    results = []
    unique_players = list({p["player"] for p in props})
    print(f"   {len(unique_players)} unique players to look up\n")

    for i, prop in enumerate(props):
        pname = prop["player"]
        mkt = prop["market_label"]
        print(f"   [{i+1}/{len(props)}] {pname} — {mkt}...", end=" ", flush=True)

        analysis = analyze_prop(prop)
        if analysis is None:
            print("⚠ no data")
            continue

        results.append({**prop, **analysis})
        tag = "✅" if analysis["score"] >= 60 else "🟡" if analysis["score"] >= 45 else "🔴"
        print(f"{tag} score={analysis['score']}  hit={analysis['hits']}/{analysis['games']}  avg={analysis['avg_margin']:+.1f}")

    # 4. Sort by score
    results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n✅ Analysis complete — {len(results)} props scored")
    print(f"   Top picks: {len([r for r in results if r['score'] >= 60])}")

    # 5. Generate HTML
    filename = generate_html(results)
    print(f"\n🎉 DONE! Open this file in your browser:")
    print(f"   {os.path.abspath(filename)}")
    return results


# ---------------------------------------------------------------------------
#  STEP 6 — Generate interactive HTML report
# ---------------------------------------------------------------------------
def generate_html(results):
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"propedge_{now}.html"

    top_picks = [r for r in results if r["score"] >= 60]
    mid_picks = [r for r in results if 45 <= r["score"] < 60]

    def result_color(res):
        if res == "HIT": return "#34d399"
        if res == "NEAR": return "#fbbf24"
        return "#f87171"

    def result_bg(res):
        if res == "HIT": return "#0d3320"
        if res == "NEAR": return "#332800"
        return "#330d0d"

    def score_color(s):
        if s >= 65: return "#34d399"
        if s >= 45: return "#fbbf24"
        return "#f87171"

    def score_bg(s):
        if s >= 65: return "#0d3320"
        if s >= 45: return "#332800"
        return "#1a0a0a"

    def score_border(s):
        if s >= 65: return "#166534"
        if s >= 45: return "#854d0e"
        return "#7f1d1d"

    def odds_str(o):
        return f"+{o}" if o > 0 else str(o)

    rows_html = ""
    for i, r in enumerate(results):
        rank = i + 1
        is_top = rank <= 3

        # Detail rows for expanded view
        detail_rows = ""
        for d in r["details"]:
            mc = result_color(d["result"])
            mb = result_bg(d["result"])
            margin_color = "#34d399" if d["margin"] > 0 else ("#fbbf24" if d["result"] == "NEAR" else "#f87171")
            margin_str = f"+{d['margin']}" if d["margin"] > 0 else str(d["margin"])
            detail_rows += f"""
            <tr style="border-bottom:1px solid #12122a">
              <td style="padding:7px 10px;color:#8888aa;font-family:'Courier New',monospace;font-size:12px">{d['date']}</td>
              <td style="padding:7px 10px;color:#c0c0d8;font-size:13px">{d['matchup']}</td>
              <td style="padding:7px 10px;text-align:center;color:#8888aa;font-family:'Courier New',monospace">{d['minutes']}</td>
              <td style="padding:7px 10px;text-align:center;color:#e2e2f0;font-weight:700;font-family:'Courier New',monospace;font-size:14px">{d['value']}</td>
              <td style="padding:7px 10px;text-align:center;color:{margin_color};font-weight:600;font-family:'Courier New',monospace">{margin_str}</td>
              <td style="padding:7px 10px;text-align:center">
                <span style="padding:2px 10px;border-radius:4px;font-size:11px;font-weight:700;background:{mb};color:{mc};border:1px solid {mc}30">{d['result']}</span>
              </td>
            </tr>"""

        # Trend bars
        trend_bars = ""
        for d in reversed(r["details"]):
            h = min(abs(d["margin"]) * 2.5, 36)
            h = max(h, 3)
            tc = "#34d399" if d["margin"] > 0 else ("#fbbf24" if d["result"] == "NEAR" else "#f87171")
            trend_bars += f'<div style="width:20px;height:{h}px;border-radius:3px;background:{tc};opacity:0.85" title="{d["date"]}: {d["margin"]:+.1f}"></div>'

        sc = score_color(r["score"])
        sb = score_bg(r["score"])
        sbd = score_border(r["score"])
        hc = "#34d399" if r["hits"] >= 7 else ("#fbbf24" if r["hits"] >= 5 else "#f87171")
        star = "★ " if is_top else ""
        name_color = "#e2e2f0" if is_top else "#a0a0c0"
        rank_color = "#818cf8" if is_top else "#444"

        avg_color = "#34d399" if r["avg_margin"] > 0 else "#f87171"
        avg_str = f"+{r['avg_margin']}" if r["avg_margin"] > 0 else str(r["avg_margin"])
        std_color = "#34d399" if r["std_dev"] < 4 else ("#fbbf24" if r["std_dev"] < 7 else "#f87171")
        odds_color = "#34d399" if r["over_odds"] > 0 else "#f87171"

        rows_html += f"""
        <tr class="prop-row" onclick="toggleDetail('d{rank}')" style="cursor:pointer;border-bottom:1px solid #0f0f20">
          <td style="padding:12px 8px;text-align:center;font-size:13px;font-weight:800;color:{rank_color};font-family:'Courier New',monospace">{rank}</td>
          <td style="padding:12px 8px;font-weight:700;font-size:14px;color:{name_color}">{star}{r['player']}</td>
          <td style="padding:12px 8px;text-align:center;font-size:12px;color:#6b6b8a">{r['matchup'].split(' @ ')[0][:3].upper()} @ {r['matchup'].split(' @ ')[1][:3].upper()}</td>
          <td style="padding:12px 8px;text-align:center;font-size:12px;color:#a0a0c0;font-weight:600">{r['market_label']}</td>
          <td style="padding:12px 8px;text-align:center;font-family:'Courier New',monospace;font-size:14px;font-weight:700;color:#c0c0d8">{r['line']}</td>
          <td style="padding:12px 8px;text-align:center;font-family:'Courier New',monospace;font-size:12px;font-weight:600;color:{odds_color}">{odds_str(r['over_odds'])}</td>
          <td style="padding:12px 8px;text-align:center"><span style="font-family:'Courier New',monospace;font-size:14px;font-weight:700;color:{hc}">{r['hits']}</span><span style="color:#444;font-size:12px">/{r['games']}</span></td>
          <td style="padding:12px 8px;text-align:center"><span style="font-family:'Courier New',monospace;font-size:14px;font-weight:700;color:#fbbf24">{r['nears']}</span><span style="color:#444;font-size:12px">/{r['games']}</span></td>
          <td style="padding:12px 8px;text-align:center;font-family:'Courier New',monospace;font-size:13px;font-weight:600;color:{avg_color}">{avg_str}</td>
          <td style="padding:12px 8px;text-align:center;font-family:'Courier New',monospace;font-size:13px;font-weight:600;color:{std_color}">{r['std_dev']}</td>
          <td style="padding:12px 8px;text-align:center">
            <div style="display:inline-flex;padding:4px 14px;border-radius:6px;font-family:'Courier New',monospace;font-size:15px;font-weight:800;background:{sb};color:{sc};border:1px solid {sbd}">{r['score']}</div>
          </td>
        </tr>
        <tr id="d{rank}" style="display:none">
          <td colspan="11" style="padding:0;background:#0a0a14">
            <div style="margin:0 16px 12px;padding:16px 20px;border-radius:8px;background:linear-gradient(135deg,#0f0f1e,#12122a);border:1px solid #1e1e3a">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
                <h3 style="margin:0;font-size:15px;font-weight:700;color:#e2e2f0">Last {r['games']} Games — {r['player']}</h3>
                <span style="font-size:12px;color:#a0a0c0;font-family:'Courier New',monospace">{r['market_label']} O {r['line']} ({r['bookmaker']})</span>
              </div>
              <table style="width:100%;border-collapse:collapse;font-size:13px">
                <thead><tr style="border-bottom:1px solid #1e1e3a">
                  <th style="padding:6px 10px;text-align:left;color:#6b6b8a;font-weight:600;font-size:11px;letter-spacing:0.8px">DATE</th>
                  <th style="padding:6px 10px;text-align:left;color:#6b6b8a;font-weight:600;font-size:11px;letter-spacing:0.8px">MATCHUP</th>
                  <th style="padding:6px 10px;text-align:center;color:#6b6b8a;font-weight:600;font-size:11px;letter-spacing:0.8px">MIN</th>
                  <th style="padding:6px 10px;text-align:center;color:#6b6b8a;font-weight:600;font-size:11px;letter-spacing:0.8px">VALUE</th>
                  <th style="padding:6px 10px;text-align:center;color:#6b6b8a;font-weight:600;font-size:11px;letter-spacing:0.8px">MARGIN</th>
                  <th style="padding:6px 10px;text-align:center;color:#6b6b8a;font-weight:600;font-size:11px;letter-spacing:0.8px">RESULT</th>
                </tr></thead>
                <tbody>{detail_rows}</tbody>
              </table>
              <div style="margin-top:14px;display:flex;gap:4px;align-items:flex-end;height:40px">
                <span style="font-size:10px;color:#555;margin-right:6px;align-self:center">TREND</span>
                {trend_bars}
              </div>
              <div style="margin-top:12px;display:flex;gap:16px;font-size:12px;color:#6b6b8a">
                <span>Last 5 avg margin: <strong style="color:{'#34d399' if r['last5_avg'] > 0 else '#f87171'}">{r['last5_avg']:+.1f}</strong></span>
                <span>Hit rate: <strong style="color:{hc}">{r['hit_rate']}%</strong></span>
              </div>
            </div>
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PropEdge NBA — {date.today().strftime('%b %d, %Y')}</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#06060e;color:#e2e2f0;font-family:'Outfit',system-ui,sans-serif;min-height:100vh}}
.prop-row:hover td{{background:rgba(129,140,248,0.04)!important}}
::-webkit-scrollbar{{width:6px}}::-webkit-scrollbar-track{{background:#0a0a14}}::-webkit-scrollbar-thumb{{background:#2a2a4a;border-radius:3px}}
</style>
<script>
function toggleDetail(id){{
  var el=document.getElementById(id);
  el.style.display=el.style.display==='none'?'table-row':'none';
}}
</script>
</head><body>
<header style="padding:20px 28px;border-bottom:1px solid #14142a;background:linear-gradient(180deg,#0c0c1a,#06060e)">
  <div style="max-width:1300px;margin:0 auto;display:flex;justify-content:space-between;align-items:center">
    <div style="display:flex;align-items:center;gap:12px">
      <div style="width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#6366f1,#818cf8);font-size:18px">⚡</div>
      <div>
        <h1 style="font-size:20px;font-weight:800;letter-spacing:-0.5px">PropEdge <span style="color:#818cf8;font-weight:400;font-size:14px">NBA</span></h1>
        <p style="font-size:10px;color:#555;letter-spacing:1px;margin-top:1px">PLAYER PROP ANALYZER</p>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:12px">
      <span style="padding:5px 12px;border-radius:20px;background:#0d3320;border:1px solid #166534;font-size:11px;color:#34d399;font-weight:700;font-family:'JetBrains Mono',monospace">OVER</span>
      <span style="padding:6px 12px;border-radius:6px;background:#0f0f1e;border:1px solid #1e1e3a;font-size:13px;color:#8888aa;font-family:'JetBrains Mono',monospace">{date.today().strftime('%Y-%m-%d')}</span>
    </div>
  </div>
</header>

<div style="max-width:1300px;margin:0 auto;padding:14px 28px">
  <div style="display:flex;gap:16px;flex-wrap:wrap">
    <div style="padding:10px 18px;border-radius:8px;background:#0c0c1a;border:1px solid #1e1e3a">
      <span style="font-size:11px;color:#6b6b8a;font-weight:600">TOTAL PROPS</span>
      <span style="margin-left:8px;font-size:16px;font-weight:800;color:#e2e2f0">{len(results)}</span>
    </div>
    <div style="padding:10px 18px;border-radius:8px;background:#0d3320;border:1px solid #166534">
      <span style="font-size:11px;color:#34d399;font-weight:600">TOP PICKS (60+)</span>
      <span style="margin-left:8px;font-size:16px;font-weight:800;color:#34d399">{len(top_picks)}</span>
    </div>
    <div style="padding:10px 18px;border-radius:8px;background:#332800;border:1px solid #854d0e">
      <span style="font-size:11px;color:#fbbf24;font-weight:600">MODERATE (45-59)</span>
      <span style="margin-left:8px;font-size:16px;font-weight:800;color:#fbbf24">{len(mid_picks)}</span>
    </div>
  </div>
</div>

<div style="max-width:1300px;margin:0 auto;padding:0 28px 60px;overflow-x:auto">
<table style="width:100%;border-collapse:collapse;margin-top:8px;min-width:900px">
<thead><tr>
  <th style="padding:12px 8px;text-align:center;color:#444;font-size:10px;letter-spacing:1px;font-weight:700;width:36px">#</th>
  <th style="padding:12px 8px;text-align:left;color:#6b6b8a;font-size:10px;letter-spacing:1.2px;font-weight:700">PLAYER</th>
  <th style="padding:12px 8px;text-align:center;color:#6b6b8a;font-size:10px;letter-spacing:1.2px;font-weight:700">GAME</th>
  <th style="padding:12px 8px;text-align:center;color:#6b6b8a;font-size:10px;letter-spacing:1.2px;font-weight:700">MARKET</th>
  <th style="padding:12px 8px;text-align:center;color:#6b6b8a;font-size:10px;letter-spacing:1.2px;font-weight:700">LINE</th>
  <th style="padding:12px 8px;text-align:center;color:#6b6b8a;font-size:10px;letter-spacing:1.2px;font-weight:700">ODDS</th>
  <th style="padding:12px 8px;text-align:center;color:#6b6b8a;font-size:10px;letter-spacing:1.2px;font-weight:700">HIT RATE</th>
  <th style="padding:12px 8px;text-align:center;color:#6b6b8a;font-size:10px;letter-spacing:1.2px;font-weight:700">NEAR</th>
  <th style="padding:12px 8px;text-align:center;color:#6b6b8a;font-size:10px;letter-spacing:1.2px;font-weight:700">AVG MARGIN</th>
  <th style="padding:12px 8px;text-align:center;color:#6b6b8a;font-size:10px;letter-spacing:1.2px;font-weight:700">STD DEV</th>
  <th style="padding:12px 8px;text-align:center;color:#6b6b8a;font-size:10px;letter-spacing:1.2px;font-weight:700">SCORE</th>
</tr></thead>
<tbody>
{rows_html}
</tbody></table>
</div>

<footer style="padding:14px 28px;border-top:1px solid #0f0f20;text-align:center;color:#2a2a4a;font-size:11px;letter-spacing:0.5px">
  PropEdge NBA — Data: NBA.com + The Odds API • Click any row to expand last 10 games • For informational purposes only
</footer>
</body></html>"""

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    return filename


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_analysis()
