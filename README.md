# ⚡ PropEdge NBA

Automated NBA player prop analyzer. Pulls **real sportsbook lines** and **real NBA.com game logs**, then ranks every prop by confidence score.

---

## Setup (2 minutes)

### Step 1: Get your free API key
Go to **https://the-odds-api.com** → Sign up → Copy your API key.
Free tier = 500 requests/month (plenty for daily use).

### Step 2: Install dependencies
```
pip install -r requirements.txt
```
That installs: `requests`, `pandas`, `numpy`, `nba_api`

### Step 3: Paste your API key
Open `propedge.py` in VS Code. Find **line 27**:
```python
ODDS_API_KEY = "YOUR_ODDS_API_KEY_HERE"
```
Replace with your actual key:
```python
ODDS_API_KEY = "abc123your_real_key"
```

### Step 4: Run it
```
python propedge.py
```

### Step 5: View results
It generates an HTML file like `propedge_20260206_143022.html`.
Open it in your browser. Click any row to expand the last 10 games.

---

## What it does

1. Fetches today's NBA games from The Odds API
2. Pulls player prop lines (Points, Rebounds, Assists, Steals, Blocks, PRA, PR, PA, RA)
3. For each player, grabs their last 10-15 game logs from NBA.com (via nba_api — free, no key)
4. Computes: hit rate, near-miss rate, avg margin vs line, consistency, confidence score
5. Ranks all props and generates an interactive HTML report

---

## Output columns

| Column     | Meaning                                           |
|------------|---------------------------------------------------|
| Hit Rate   | How many of last 10 games cleared the line (7/10) |
| Near       | Within 1.5 of the line but missed (2/10)          |
| Avg Margin | Average stat value minus the line (+2.3)          |
| Std Dev    | Consistency — lower = more predictable            |
| Score      | Confidence 0-100 (higher = better bet)            |

---

## Files

```
propedge-nba/
├── propedge.py          ← the whole app (one file)
├── requirements.txt     ← dependencies
└── README.md            ← you're reading it
```

---

## Troubleshooting

**"No games found"** → Run on a day with NBA games. Lines are usually posted by morning.

**"nba_api error"** → NBA.com rate limits. The script already adds 0.7s delay between calls. If it still fails, run again in a minute.

**"Odds API 401"** → Your API key is wrong. Double-check it at https://the-odds-api.com/account

**Yellow lines in VS Code on nba_api imports** → Normal. Pylance can't resolve nba_api's dynamic imports. It still works fine. Add `# type: ignore` (already included) to silence them.
