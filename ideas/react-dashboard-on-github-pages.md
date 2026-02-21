# React Dashboard on GitHub Pages

## Overview

Create a React-based dashboard hosted on GitHub Pages that visualizes engineering metrics currently stored in a private Google Sheet. The sheet is populated by existing Google Apps Scripts that pull data from Jira and GitHub.

Two viable approaches for getting data from the private sheet into the dashboard:

1. **Bake data into the repo** via a scheduled GitHub Action
2. **Expose data via Google Apps Script** `doGet()` endpoint

Both can be combined — use Option 1 as the primary approach and Option 3 as a supplement for lighter, real-time data needs.

---

## Approach 1: GitHub Action Pulls Data into the Repo (Recommended)

### How It Works

A GitHub Action runs on a schedule, authenticates with Google Sheets using a service account, reads the data, and commits it as a static JSON file in the repo. The React app reads that JSON at load time — no runtime auth, no API keys in the browser.

```
Google Sheet (private)
       |
       | GitHub Action (scheduled, e.g. every hour)
       | uses Google service account credentials
       v
  data/metrics.json  (committed to repo)
       |
       | React app reads at page load
       v
  GitHub Pages dashboard
```

### Step-by-Step Setup

#### 1. Create a Google Cloud Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use an existing one), e.g. `metrics-dashboard`
3. Enable the **Google Sheets API** under APIs & Services > Library
4. Go to **APIs & Services > Credentials**
5. Click **Create Credentials > Service Account**
   - Name: `metrics-dashboard-reader`
   - Role: none needed (it only accesses sheets shared with it)
6. Go to the service account > **Keys** tab > **Add Key > Create New Key > JSON**
7. Download the JSON key file — you'll need it for the GitHub secret

#### 2. Share the Sheet with the Service Account

1. Open the JSON key file, find the `client_email` field (looks like `metrics-dashboard-reader@your-project.iam.gserviceaccount.com`)
2. In Google Sheets, click **Share** and add that email as a **Viewer**
3. The service account can now read the sheet without any user login

#### 3. Store Credentials in GitHub Secrets

In your repo: **Settings > Secrets and variables > Actions**

Add these secrets:
- `GOOGLE_SERVICE_ACCOUNT_KEY` — the entire contents of the JSON key file
- `GOOGLE_SHEET_ID` — the ID from the sheet URL (`https://docs.google.com/spreadsheets/d/{THIS_PART}/edit`)

#### 4. Create the Data Fetching Script

Create `scripts/fetch_sheet_data.py`:

```python
"""Fetch metrics data from Google Sheets and write to JSON."""

import json
import os
import sys

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def fetch_sheet_data():
    """Read all configured tabs from the Google Sheet and write to JSON."""

    # Authenticate with service account
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not creds_json:
        print("Error: GOOGLE_SERVICE_ACCOUNT_KEY not set", file=sys.stderr)
        sys.exit(1)

    creds_info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds)

    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        print("Error: GOOGLE_SHEET_ID not set", file=sys.stderr)
        sys.exit(1)

    # Define which tabs/ranges to pull
    # Adjust these to match your actual sheet tab names and ranges
    ranges = {
        "cycle_time": "Cycle Time!A1:Z1000",
        "developer_activity": "Developer Activity!A1:Z1000",
        "engineering_excellence": "Engineering Excellence!A1:Z1000",
        "releases": "Releases!A1:Z1000",
        "bug_stats": "Bug Stats!A1:Z1000",
    }

    data = {}
    sheets_api = service.spreadsheets().values()

    for key, range_str in ranges.items():
        try:
            result = sheets_api.get(
                spreadsheetId=sheet_id, range=range_str
            ).execute()
            rows = result.get("values", [])

            if not rows:
                data[key] = []
                continue

            # First row is headers, rest is data
            headers = rows[0]
            data[key] = [
                dict(zip(headers, row + [""] * (len(headers) - len(row))))
                for row in rows[1:]
            ]
        except Exception as e:
            print(f"Warning: Could not fetch '{key}': {e}", file=sys.stderr)
            data[key] = []

    # Write to the dashboard's public data directory
    output_path = os.path.join("dashboard", "public", "data", "metrics.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Wrote {len(data)} datasets to {output_path}")


if __name__ == "__main__":
    fetch_sheet_data()
```

#### 5. Create the GitHub Action

Create `.github/workflows/update-dashboard-data.yml`:

```yaml
name: Update Dashboard Data

on:
  schedule:
    # Run every hour during business hours (UTC)
    - cron: "0 7-18 * * 1-5"
  workflow_dispatch: # Allow manual trigger

permissions:
  contents: write

jobs:
  fetch-data:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          pip install google-auth google-api-python-client

      - name: Fetch sheet data
        env:
          GOOGLE_SERVICE_ACCOUNT_KEY: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_KEY }}
          GOOGLE_SHEET_ID: ${{ secrets.GOOGLE_SHEET_ID }}
        run: python scripts/fetch_sheet_data.py

      - name: Commit and push if changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add dashboard/public/data/metrics.json
          git diff --staged --quiet || git commit -m "Update dashboard metrics data"
          git push
```

### Data Freshness

- The cron runs every hour on weekdays during business hours
- You can also trigger it manually via the Actions tab or the GitHub API
- The `git diff --staged --quiet ||` check means it only commits when data actually changed, keeping the git history clean

---

## Approach 2: Google Apps Script `doGet()` Endpoint

### How It Works

Your existing Google Apps Script (or a new one) exposes a web endpoint that returns JSON. The React app fetches from that URL. The sheet stays private — only the Apps Script endpoint is accessible.

```
Google Sheet (private)
       |
       | Apps Script reads sheet, returns JSON
       v
  https://script.google.com/macros/s/{id}/exec
       |
       | React app fetches at page load
       v
  GitHub Pages dashboard
```

### Step-by-Step Setup

#### 1. Create (or Add to) the Apps Script

In your Google Sheet: **Extensions > Apps Script**

```javascript
/**
 * Serves sheet data as JSON when the script URL is accessed via GET.
 *
 * Deploy as: Web App
 *   - Execute as: Me
 *   - Who has access: Anyone (within your org, if using Workspace)
 */
function doGet(e) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet();
  const requestedTab = e.parameter.tab;
  const data = {};

  // If a specific tab is requested, return just that one
  // Otherwise return all configured tabs
  const tabNames = requestedTab
    ? [requestedTab]
    : [
        "Cycle Time",
        "Developer Activity",
        "Engineering Excellence",
        "Releases",
        "Bug Stats",
      ];

  tabNames.forEach(function (tabName) {
    const tab = sheet.getSheetByName(tabName);
    if (!tab) return;

    const values = tab.getDataRange().getValues();
    if (values.length === 0) return;

    const headers = values[0];
    const rows = values.slice(1).map(function (row) {
      const obj = {};
      headers.forEach(function (header, i) {
        obj[header] = row[i];
      });
      return obj;
    });

    // Convert tab name to a clean key
    const key = tabName.toLowerCase().replace(/\s+/g, "_");
    data[key] = rows;
  });

  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(
    ContentService.MimeType.JSON
  );
}
```

#### 2. Deploy as a Web App

1. In Apps Script editor: **Deploy > New Deployment**
2. Select type: **Web App**
3. Settings:
   - **Execute as**: Me (your account — this gives the script access to the private sheet)
   - **Who has access**: Anyone within your Google Workspace organization
4. Click **Deploy**
5. Copy the deployment URL (looks like `https://script.google.com/macros/s/AKfy.../exec`)

#### 3. Access Control

When deployed with "Anyone within [org]":
- Only people logged into your company's Google Workspace can hit the endpoint
- No authentication tokens needed in the React app — the browser's Google session handles it

**Important caveat**: If deployed as "Anyone" (not restricted to org), the URL is effectively public. Anyone who discovers it can read the data. For most internal metrics this is low risk, but be aware.

If your Google Workspace enforces organization-only access on Apps Script web apps, this is a clean solution with no extra infrastructure.

#### 4. Calling It from React

```javascript
const APPS_SCRIPT_URL = "https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec";

async function fetchMetrics(tab) {
  const url = tab ? `${APPS_SCRIPT_URL}?tab=${encodeURIComponent(tab)}` : APPS_SCRIPT_URL;
  const response = await fetch(url);
  return response.json();
}
```

### Limitations

- **Cold starts**: Apps Script web apps can take 2-5 seconds on first request
- **Quotas**: Google Apps Script has a daily quota of ~20,000 URL fetch triggers for consumer accounts, more for Workspace. Plenty for a dashboard
- **CORS**: Apps Script web apps return redirects that can cause CORS issues in some setups. A common workaround is fetching in `no-cors` mode or using the `google.script.run` client, but the simplest fix is to just handle the redirect. In practice, `fetch(url, { redirect: "follow" })` usually works
- **No real-time**: Data is as fresh as the sheet. If Apps Scripts update the sheet every 15 minutes, the dashboard is 0-15 minutes behind

---

## The React Dashboard

This part is the same regardless of which data approach you use.

### Tech Stack

| Tool | Purpose |
|------|---------|
| **Vite** | Build tool — fast, simple config |
| **React** | UI framework |
| **Recharts** | Charting library (built on D3, React-native) |
| **TanStack Query** | Data fetching with caching and refetch |
| **Tailwind CSS** | Styling (optional, but fast for dashboards) |

### Project Structure

```
dashboard/
  ├── public/
  │   └── data/
  │       └── metrics.json        # Option 1: static data file
  ├── src/
  │   ├── main.jsx
  │   ├── App.jsx
  │   ├── hooks/
  │   │   └── useMetrics.js       # Data fetching hook
  │   ├── components/
  │   │   ├── Layout.jsx
  │   │   ├── MetricCard.jsx      # Summary stat card
  │   │   └── charts/
  │   │       ├── CycleTimeChart.jsx
  │   │       ├── ReleaseFrequencyChart.jsx
  │   │       ├── EngineeringExcellenceChart.jsx
  │   │       ├── BugStatsChart.jsx
  │   │       └── DeveloperActivityChart.jsx
  │   └── utils/
  │       └── dataTransforms.js   # Clean/reshape data for charts
  ├── index.html
  ├── package.json
  ├── vite.config.js
  └── tailwind.config.js
```

### Data Fetching Hook

```javascript
// src/hooks/useMetrics.js
import { useQuery } from "@tanstack/react-query";

// Option 1: Static JSON from repo
const fetchFromStatic = () =>
  fetch("/data/metrics.json").then((res) => res.json());

// Option 2: Apps Script endpoint
const APPS_SCRIPT_URL = import.meta.env.VITE_APPS_SCRIPT_URL;
const fetchFromAppsScript = () =>
  fetch(APPS_SCRIPT_URL).then((res) => res.json());

// Use whichever source is configured
const fetchMetrics = APPS_SCRIPT_URL ? fetchFromAppsScript : fetchFromStatic;

export function useMetrics() {
  return useQuery({
    queryKey: ["metrics"],
    queryFn: fetchMetrics,
    staleTime: 5 * 60 * 1000,    // Consider data fresh for 5 minutes
    refetchInterval: 10 * 60 * 1000, // Refetch every 10 minutes
  });
}
```

### Deployment to GitHub Pages

Create `.github/workflows/deploy-dashboard.yml`:

```yaml
name: Deploy Dashboard

on:
  push:
    branches: [main]
    paths:
      - "dashboard/**"
      - "dashboard/public/data/**"

permissions:
  pages: write
  id-token: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install and build
        working-directory: dashboard
        run: |
          npm ci
          npm run build

      - uses: actions/upload-pages-artifact@v3
        with:
          path: dashboard/dist

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

### Vite Config for GitHub Pages

```javascript
// dashboard/vite.config.js
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Set base to repo name for GitHub Pages
  base: "/metrics-and-insights/",
});
```

---

## GitHub Pages Visibility (Private Repos)

Since this is a private company repo, dashboard visibility depends on your GitHub plan:

- **GitHub Enterprise Cloud**: Supports private GitHub Pages — only org members can access. This is the ideal case. Check under **Organization Settings > Pages** or ask your GitHub admin.
- **GitHub Team or lower**: Pages on private repos are served publicly. The URL is not advertised but anyone who has it can view.

If private Pages aren't available, alternatives:
- Deploy to **Cloudflare Pages** or **Vercel** behind your company SSO
- Use a simple internal hosting platform if available

---

## Visual Design: "Quest Intelligence" Dark Theme

The dashboard should match the polished dark aesthetic of the
[Quest Portfolio Dashboard](https://kjellkod.github.io/quest/) — a dark blue
base with subtle ambient glows, semi-transparent glass-like cards, and clean
typography. Here is the complete design system extracted from that reference.

### Color Palette

#### Backgrounds

| Token | Value | Usage |
|-------|-------|-------|
| `--bg-primary` | `#05070f` | Page background |
| `--bg-secondary` | `#0a0f1d` | Slightly lighter layer |
| `--bg-tertiary` | `#0f172a` | Gradient endpoint |

#### Surfaces (Cards & Panels)

Cards use **semi-transparent** backgrounds with a subtle border, creating a
frosted-glass depth effect against the ambient glows behind them.

| Token | Value | Usage |
|-------|-------|-------|
| `--surface-0` | `rgba(17, 24, 39, 0.78)` | Default card fill |
| `--surface-1` | `rgba(15, 23, 42, 0.84)` | Darker panels |
| `--surface-2` | `rgba(30, 41, 59, 0.75)` | Elevated elements |
| `--border` | `rgba(148, 163, 184, 0.22)` | Subtle card borders |

#### Text

| Token | Value | Usage |
|-------|-------|-------|
| `--text-primary` | `#f8fafc` | Headings, key numbers |
| `--text-secondary` | `#cbd5e1` | Body text, descriptions |
| `--text-tertiary` | `#94a3b8` | Labels, metadata |

#### Status / Accent Colors

| Status | Color | Hex |
|--------|-------|-----|
| Finished / Success | Emerald green | `#34d399` |
| In Progress | Sky blue | `#60a5fa` |
| Blocked / Warning | Amber | `#f59e0b` |
| Abandoned / Error | Red | `#f87171` |
| Unknown / Neutral | Purple | `#a78bfa` |

These same accents should be used for chart series — cycle time trends in blue,
bug counts in red, release success in green, etc.

### Ambient Glow Effect

The signature "shiny" look comes from two large radial gradients positioned
behind all content, creating soft light pools that bleed through the
semi-transparent cards:

```css
/* Apply to body or a full-screen wrapper */
.dashboard-bg {
  background-color: #05070f;
  position: relative;
}

.dashboard-bg::before,
.dashboard-bg::after {
  content: "";
  position: fixed;
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
}

/* Cyan glow — top left */
.dashboard-bg::before {
  width: 1200px;
  height: 1200px;
  top: -5%;
  left: 8%;
  background: radial-gradient(
    circle,
    rgba(56, 189, 248, 0.18) 0%,
    transparent 70%
  );
  filter: blur(95px);
}

/* Teal glow — bottom right */
.dashboard-bg::after {
  width: 1000px;
  height: 1000px;
  bottom: -10%;
  right: 5%;
  background: radial-gradient(
    circle,
    rgba(20, 184, 166, 0.12) 0%,
    transparent 70%
  );
  filter: blur(95px);
}
```

All page content sits at `z-index: 1` or higher so the glows shine through the
semi-transparent card backgrounds.

### Card Styling

```css
.card {
  background: rgba(17, 24, 39, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 25px 60px rgba(2, 6, 23, 0.45);
  transition: border-color 0.2s ease;
}

.card:hover {
  border-color: rgba(148, 163, 184, 0.35);
}
```

### KPI Summary Cards (Top Row)

The top row shows 4-6 key numbers in a grid. Each card has:
- An uppercase label in `--text-tertiary` (small, tracked)
- A large number in `--text-primary` (36-48px, bold)
- Colored accent matching the metric meaning (green for positive, red for issues)

```css
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 16px;
}

.kpi-card {
  text-align: center;
  padding: 20px 16px;
}

.kpi-label {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #94a3b8;
}

.kpi-value {
  font-size: 42px;
  font-weight: 700;
  margin-top: 8px;
  color: #f8fafc;
}
```

### Typography

```css
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, sans-serif;
  line-height: 1.6;
  color: #cbd5e1;
}

h1 {
  color: #f8fafc;
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
}

h2 {
  color: #f8fafc;
  font-size: 20px;
  font-weight: 600;
}

/* Section eyebrow label (e.g. "ENGINEERING METRICS") */
.eyebrow {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #34d399; /* accent green */
}
```

### Layout Grid

```css
.dashboard-layout {
  max-width: 1200px;
  margin: 0 auto;
  padding: 40px 24px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  position: relative;
  z-index: 1;
}

/* Two-column chart row */
.chart-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

@media (max-width: 780px) {
  .chart-row {
    grid-template-columns: 1fr;
  }
}
```

### Chart Styling with Recharts

Configure Recharts to match the dark theme:

```jsx
// Consistent chart theme props
const chartTheme = {
  axisStroke: "#94a3b8",
  gridStroke: "rgba(148, 163, 184, 0.12)",
  tooltipBg: "rgba(15, 23, 42, 0.95)",
  tooltipBorder: "rgba(148, 163, 184, 0.3)",
  colors: ["#60a5fa", "#34d399", "#f59e0b", "#f87171", "#a78bfa"],
};

// Example usage in a Recharts component
<ResponsiveContainer width="100%" height={300}>
  <LineChart data={data}>
    <CartesianGrid stroke={chartTheme.gridStroke} strokeDasharray="3 3" />
    <XAxis
      dataKey="month"
      stroke={chartTheme.axisStroke}
      tick={{ fill: "#94a3b8", fontSize: 12 }}
    />
    <YAxis
      stroke={chartTheme.axisStroke}
      tick={{ fill: "#94a3b8", fontSize: 12 }}
    />
    <Tooltip
      contentStyle={{
        background: chartTheme.tooltipBg,
        border: `1px solid ${chartTheme.tooltipBorder}`,
        borderRadius: "8px",
        color: "#f8fafc",
      }}
    />
    <Line
      type="monotone"
      dataKey="cycleTime"
      stroke="#60a5fa"
      strokeWidth={2}
      dot={{ fill: "#60a5fa", r: 4 }}
    />
  </LineChart>
</ResponsiveContainer>
```

### Responsive Breakpoints

| Breakpoint | Behavior |
|------------|----------|
| > 1120px | Full layout, 5-column KPI grid, 2-column charts |
| 780-1120px | KPI grid wraps to 3 columns, charts stack partially |
| 460-780px | Single column layout, charts full width |
| < 460px | Compact mobile layout, smaller font sizes |

### Tailwind CSS Shortcut

If using Tailwind, most of this maps directly to the `slate` color scale:

```javascript
// tailwind.config.js
export default {
  content: ["./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          0: "rgba(17, 24, 39, 0.78)",
          1: "rgba(15, 23, 42, 0.84)",
          2: "rgba(30, 41, 59, 0.75)",
        },
        accent: {
          green: "#34d399",
          blue: "#60a5fa",
          amber: "#f59e0b",
          red: "#f87171",
          purple: "#a78bfa",
        },
      },
    },
  },
};
```

Then cards become: `bg-surface-0 border border-slate-700/20 rounded-2xl p-6 shadow-2xl`

---

## Chart Catalog: From Google Sheets to Recharts

Every chart currently in the spreadsheet maps directly to a Recharts component.
Below is the full catalog with the Recharts component type, design upgrades over
the spreadsheet version, and example JSX.

### Dashboard Layout

The charts are organized into themed sections, each inside a dark card panel.

```
┌─────────────────────────────────────────────────────────────┐
│  ENGINEERING METRICS DASHBOARD              Data: Feb 2026  │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ Releases │ Rollbacks│ Tickets  │ Points   │ SLA % Met       │
│    14    │    0     │   135    │   300    │   92%           │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│                                                             │
│  ┌─────────────────────────┐ ┌─────────────────────────┐   │
│  │ Completed Work & SLAs   │ │ Vulnerability Look-Ahead│   │
│  │ (stacked area)          │ │ (stacked area)          │   │
│  └─────────────────────────┘ └─────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────┐ ┌─────────────────────────┐   │
│  │ R&D Work Focus          │ │ Releases & Rollbacks    │   │
│  │ (stacked bar 100%)      │ │ (combo bar + line)      │   │
│  └─────────────────────────┘ └─────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────┐ ┌─────────────────────────┐   │
│  │ Released Tickets YoY    │ │ Released Points YoY     │   │
│  │ (multi-line)            │ │ (multi-line)            │   │
│  └─────────────────────────┘ └─────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────┐ ┌─────────────────────────┐   │
│  │ Cycle Time: Median YoY  │ │ Cycle Time: Average YoY │   │
│  │ (multi-line, purple)    │ │ (multi-line, amber)     │   │
│  └─────────────────────────┘ └─────────────────────────┘   │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Web Releases YoY (multi-line, full width)             │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### Chart 1: Completed Work and All SLAs

**Type**: `<AreaChart>` — stacked area with transparency

**What it shows**: Estimated work (SLA), completed work, and remaining work
over time. The overlap between estimated and completed tells the story at a
glance.

**Dark theme upgrades**:
- Semi-transparent fills with `fillOpacity={0.3}` so layers blend beautifully
  against the dark background
- Glowing stroke on the "Completed" line (`filter: drop-shadow(0 0 4px #34d399)`)
- Subtle dashed grid lines instead of the heavy gray Google Sheets grid

```jsx
<ResponsiveContainer width="100%" height={320}>
  <AreaChart data={slaData}>
    <defs>
      <linearGradient id="gradEstimated" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#60a5fa" stopOpacity={0.4} />
        <stop offset="100%" stopColor="#60a5fa" stopOpacity={0.05} />
      </linearGradient>
      <linearGradient id="gradCompleted" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#f87171" stopOpacity={0.4} />
        <stop offset="100%" stopColor="#f87171" stopOpacity={0.05} />
      </linearGradient>
      <linearGradient id="gradRemaining" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.4} />
        <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.05} />
      </linearGradient>
    </defs>
    <CartesianGrid stroke="rgba(148,163,184,0.08)" strokeDasharray="3 3" />
    <XAxis dataKey="month" tick={{ fill: "#94a3b8", fontSize: 12 }} />
    <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} />
    <Tooltip contentStyle={tooltipStyle} />
    <Area
      type="monotone"
      dataKey="estimated"
      stroke="#60a5fa"
      strokeWidth={2}
      fill="url(#gradEstimated)"
      name="Estimated Work (SLA)"
    />
    <Area
      type="monotone"
      dataKey="completed"
      stroke="#f87171"
      strokeWidth={2}
      fill="url(#gradCompleted)"
      name="Completed"
    />
    <Area
      type="monotone"
      dataKey="remaining"
      stroke="#f59e0b"
      strokeWidth={2}
      fill="url(#gradRemaining)"
      name="Remaining"
    />
  </AreaChart>
</ResponsiveContainer>
```

---

### Chart 2: Vulnerability Look-Ahead (by Team)

**Type**: `<AreaChart>` — stacked area, one series per team

**What it shows**: Remaining vulnerability SLA work per team over time.
Helps leadership see which teams carry the load.

**Dark theme upgrades**:
- Each team gets a distinct accent color from the palette
- Stacked fills create a layered mountain effect that looks stunning on dark
- Team legend with colored dots instead of the flat Google Sheets boxes

```jsx
const teamColors = {
  panda: "#60a5fa",   // blue
  spork: "#f87171",   // red
  mint: "#f59e0b",    // amber
  other: "#34d399",   // green
};

<ResponsiveContainer width="100%" height={320}>
  <AreaChart data={vulnData}>
    <CartesianGrid stroke="rgba(148,163,184,0.08)" strokeDasharray="3 3" />
    <XAxis dataKey="month" tick={{ fill: "#94a3b8", fontSize: 12 }} />
    <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} />
    <Tooltip contentStyle={tooltipStyle} />
    <Legend />
    {Object.entries(teamColors).map(([team, color]) => (
      <Area
        key={team}
        type="monotone"
        dataKey={team}
        stackId="teams"
        stroke={color}
        fill={color}
        fillOpacity={0.25}
        name={`${team.charAt(0).toUpperCase() + team.slice(1)} SLAs`}
      />
    ))}
  </AreaChart>
</ResponsiveContainer>
```

---

### Chart 3: R&D Work Focus (Stacked Percentage Bar)

**Type**: `<BarChart>` — stacked bars, normalized to 100%

**What it shows**: Monthly breakdown of where engineering effort goes:
Product vs Critical vs Debt Reduction vs Operational.

**Dark theme upgrades**:
- Vibrant stacked segments pop against the dark card
- Rounded bar corners (`radius={[4, 4, 0, 0]}` on top segment)
- Percentage labels inside bars for months with data
- Hover reveals exact breakdown in a styled tooltip

```jsx
const focusColors = {
  product: "#60a5fa",        // blue — the main investment
  critical: "#f87171",       // red — fires
  debtReduction: "#f59e0b",  // amber — paying it down
  operational: "#34d399",    // green — keeping the lights on
};

<ResponsiveContainer width="100%" height={320}>
  <BarChart data={focusData}>
    <CartesianGrid stroke="rgba(148,163,184,0.08)" strokeDasharray="3 3" />
    <XAxis dataKey="month" tick={{ fill: "#94a3b8", fontSize: 12 }} />
    <YAxis
      tick={{ fill: "#94a3b8", fontSize: 12 }}
      tickFormatter={(v) => `${v}%`}
      domain={[0, 100]}
    />
    <Tooltip
      contentStyle={tooltipStyle}
      formatter={(value) => `${value.toFixed(1)}%`}
    />
    <Legend />
    <Bar dataKey="product" stackId="focus" fill="#60a5fa" name="Product %" />
    <Bar dataKey="critical" stackId="focus" fill="#f87171" name="Critical %" />
    <Bar dataKey="debtReduction" stackId="focus" fill="#f59e0b" name="Debt Reduction %" />
    <Bar
      dataKey="operational"
      stackId="focus"
      fill="#34d399"
      name="Operational %"
      radius={[4, 4, 0, 0]}
    />
  </BarChart>
</ResponsiveContainer>
```

---

### Chart 4: Releases and Rollbacks (Combo Chart)

**Type**: `<ComposedChart>` — bars for releases + line for rollbacks

**What it shows**: Monthly release count with rollback trend overlaid.
The combination makes it easy to spot months where rollbacks spike relative
to releases.

**Dark theme upgrades**:
- Releases as solid blue bars with subtle glow
- Rollback line in red with animated dots at data points
- Zero-rollback months feel celebratory against the dark background
- Bar hover with a cyan highlight border

```jsx
<ResponsiveContainer width="100%" height={320}>
  <ComposedChart data={releaseData}>
    <CartesianGrid stroke="rgba(148,163,184,0.08)" strokeDasharray="3 3" />
    <XAxis dataKey="month" tick={{ fill: "#94a3b8", fontSize: 12 }} />
    <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} />
    <Tooltip contentStyle={tooltipStyle} />
    <Legend />
    <Bar
      dataKey="releases"
      fill="#60a5fa"
      name="Releases"
      radius={[6, 6, 0, 0]}
      barSize={40}
    />
    <Line
      type="monotone"
      dataKey="reverted"
      stroke="#f87171"
      strokeWidth={3}
      name="Reverted"
      dot={{ fill: "#f87171", r: 5, strokeWidth: 2, stroke: "#0a0f1d" }}
    />
  </ComposedChart>
</ResponsiveContainer>
```

---

### Chart 5: Year-over-Year Comparison Lines (Tickets, Points, Releases)

**Type**: `<LineChart>` — multiple lines, one per year

**What it shows**: The same metric (tickets released, points released, or
web releases) plotted by month, with one line per year (2023-2026). Makes
trends and growth immediately visible.

**Dark theme upgrades**:
- Each year gets a distinct color with decreasing opacity for older years
- Current year (2026) is bold and bright, older years fade into the background
- Animated line drawing on load (Recharts `isAnimationActive`)
- Glowing dot on the current month to show "you are here"

```jsx
const yearColors = {
  2023: { stroke: "#94a3b8", opacity: 0.5 },  // gray, faded
  2024: { stroke: "#a78bfa", opacity: 0.7 },  // purple, medium
  2025: { stroke: "#34d399", opacity: 0.85 },  // green, prominent
  2026: { stroke: "#60a5fa", opacity: 1.0 },   // blue, bold current year
};

<ResponsiveContainer width="100%" height={320}>
  <LineChart data={monthlyData}>
    <CartesianGrid stroke="rgba(148,163,184,0.08)" strokeDasharray="3 3" />
    <XAxis dataKey="month" tick={{ fill: "#94a3b8", fontSize: 12 }} />
    <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} />
    <Tooltip contentStyle={tooltipStyle} />
    <Legend />
    {Object.entries(yearColors).map(([year, style]) => (
      <Line
        key={year}
        type="monotone"
        dataKey={`y${year}`}
        stroke={style.stroke}
        strokeWidth={year === "2026" ? 3 : 1.5}
        strokeOpacity={style.opacity}
        dot={year === "2026" ? { fill: style.stroke, r: 5 } : false}
        name={`${year}`}
        connectNulls
      />
    ))}
  </LineChart>
</ResponsiveContainer>
```

This pattern is reused for three chart instances:
1. **Engineering #Released Tickets (2023-2026)**
2. **Engineering #Released Points (2023-2026)**
3. **[Web] Releases (2023-2026)**

Each uses the same `<YearOverYearChart>` component, just with different data
keys and titles. Build it once, use it three times.

---

### Chart 6: Cycle Time — Median (Year-over-Year)

**Type**: `<LineChart>` — multi-year comparison

**What it shows**: Median cycle time (days from code review to release) per
month, with one line per year. Median is the better stat here — it's not
skewed by outlier tickets that sit for weeks. A downward trend year-over-year
means the team is shipping faster.

**Dark theme upgrades**:
- Progressive year styling: older years thin and faded, recent years bold
- Current year gets a subtle area fill underneath to emphasize the trend
- A horizontal reference line at your SLA target (e.g., 7 days) adds context
- Tooltip shows "days" unit with year-over-year delta

```jsx
const cycleTimeYearColors = {
  2023: { stroke: "#94a3b8", width: 1.5, opacity: 0.45 },  // gray, faded
  2024: { stroke: "#a78bfa", width: 2.5, opacity: 0.75 },  // purple, medium
  2025: { stroke: "#c084fc", width: 3,   opacity: 1.0 },   // bright purple, bold
};

<ResponsiveContainer width="100%" height={320}>
  <LineChart data={medianCycleData}>
    <defs>
      {/* Subtle fill under the most recent year */}
      <linearGradient id="gradCycleCurrent" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#c084fc" stopOpacity={0.2} />
        <stop offset="100%" stopColor="#c084fc" stopOpacity={0} />
      </linearGradient>
    </defs>
    <CartesianGrid stroke="rgba(148,163,184,0.08)" strokeDasharray="3 3" />
    <XAxis dataKey="month" tick={{ fill: "#94a3b8", fontSize: 12 }} />
    <YAxis
      tick={{ fill: "#94a3b8", fontSize: 12 }}
      label={{
        value: "Days (Median)",
        angle: -90,
        position: "insideLeft",
        fill: "#94a3b8",
        fontSize: 12,
      }}
    />
    {/* Optional SLA target reference line */}
    <ReferenceLine
      y={7}
      stroke="#34d399"
      strokeDasharray="6 4"
      strokeOpacity={0.5}
      label={{ value: "SLA Target", fill: "#34d399", fontSize: 11 }}
    />
    <Tooltip
      contentStyle={tooltipStyle}
      formatter={(value) => [`${value} days`, null]}
    />
    <Legend />
    {Object.entries(cycleTimeYearColors).map(([year, style]) => (
      <Line
        key={year}
        type="monotone"
        dataKey={`median_${year}`}
        stroke={style.stroke}
        strokeWidth={style.width}
        strokeOpacity={style.opacity}
        dot={year === "2025" ? { fill: style.stroke, r: 4 } : false}
        name={`${year} Median`}
        connectNulls
      />
    ))}
  </LineChart>
</ResponsiveContainer>
```

---

### Chart 7: Cycle Time — Average (Year-over-Year)

**Type**: `<LineChart>` — multi-year comparison (same pattern as median)

**What it shows**: Average cycle time per month, year-over-year. Average is
more sensitive to spikes — a single ticket stuck for 30 days pulls the
average up, which is useful for spotting systemic slowdowns. Show it alongside
the median chart so viewers can compare the two.

**Dark theme upgrades**:
- Same progressive year styling as the median chart
- Different color family (gold/amber) to visually distinguish from the
  median chart (purple) at a glance
- Area fill under the current year line
- Tooltip shows the average alongside a "vs median" delta if both datasets
  are available

```jsx
const avgYearColors = {
  2023: { stroke: "#94a3b8", width: 1.5, opacity: 0.45 },  // gray, faded
  2024: { stroke: "#a78bfa", width: 2.5, opacity: 0.75 },  // purple, medium
  2025: { stroke: "#f59e0b", width: 3,   opacity: 1.0 },   // amber, bold current
};

<ResponsiveContainer width="100%" height={320}>
  <LineChart data={avgCycleData}>
    <defs>
      <linearGradient id="gradCycleAvg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.2} />
        <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
      </linearGradient>
    </defs>
    <CartesianGrid stroke="rgba(148,163,184,0.08)" strokeDasharray="3 3" />
    <XAxis dataKey="month" tick={{ fill: "#94a3b8", fontSize: 12 }} />
    <YAxis
      tick={{ fill: "#94a3b8", fontSize: 12 }}
      label={{
        value: "Days (Average)",
        angle: -90,
        position: "insideLeft",
        fill: "#94a3b8",
        fontSize: 12,
      }}
    />
    <ReferenceLine
      y={7}
      stroke="#34d399"
      strokeDasharray="6 4"
      strokeOpacity={0.5}
      label={{ value: "SLA Target", fill: "#34d399", fontSize: 11 }}
    />
    <Tooltip
      contentStyle={tooltipStyle}
      formatter={(value) => [`${value} days`, null]}
    />
    <Legend />
    {Object.entries(avgYearColors).map(([year, style]) => (
      <Line
        key={year}
        type="monotone"
        dataKey={`avg_${year}`}
        stroke={style.stroke}
        strokeWidth={style.width}
        strokeOpacity={style.opacity}
        dot={year === "2025" ? { fill: style.stroke, r: 5 } : false}
        name={`${year} Average`}
        connectNulls
      />
    ))}
  </LineChart>
</ResponsiveContainer>
```

**Layout note**: These two cycle time charts should sit side-by-side in a
`chart-row` under a "CYCLE TIME" section eyebrow. Median on the left, average
on the right. The pairing lets viewers immediately see if a spike in average
is driven by a few outliers (median stays flat) or a systemic slowdown
(both spike).

```
┌─────────────────────────────┐ ┌─────────────────────────────┐
│ Cycle Time: Median (YoY)    │ │ Cycle Time: Average (YoY)   │
│ Purple tones, lower values  │ │ Amber tones, higher values  │
│ Shows the "typical" ticket  │ │ Shows impact of outliers    │
└─────────────────────────────┘ └─────────────────────────────┘
```

---

### Shared Utilities

#### Tooltip Style (reused across all charts)

```javascript
const tooltipStyle = {
  background: "rgba(15, 23, 42, 0.95)",
  border: "1px solid rgba(148, 163, 184, 0.3)",
  borderRadius: "10px",
  color: "#f8fafc",
  fontSize: "13px",
  boxShadow: "0 8px 32px rgba(0, 0, 0, 0.4)",
};
```

#### Gradient Definitions (reused for area fills)

Create a shared `<ChartGradients>` component with all gradient `<defs>` so
they're consistent across charts:

```jsx
function ChartGradients() {
  const gradients = [
    { id: "blue", color: "#60a5fa" },
    { id: "green", color: "#34d399" },
    { id: "amber", color: "#f59e0b" },
    { id: "red", color: "#f87171" },
    { id: "purple", color: "#a78bfa" },
  ];

  return (
    <defs>
      {gradients.map(({ id, color }) => (
        <linearGradient key={id} id={`grad-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.4} />
          <stop offset="100%" stopColor={color} stopOpacity={0.05} />
        </linearGradient>
      ))}
    </defs>
  );
}
```

---

### Before & After: What Changes

| Aspect | Google Sheets | React Dashboard |
|--------|--------------|-----------------|
| Background | White/gray | Deep dark blue `#05070f` |
| Grid lines | Heavy black borders | Faint `rgba(148,163,184,0.08)` dashes |
| Colors | Default Google palette | Curated accent palette with glow |
| Tooltips | Yellow sticky note | Glass-effect dark panel |
| Legend | Flat colored boxes | Rounded pills with subtle borders |
| Typography | Default sans-serif | System stack, tracked uppercase labels |
| Area fills | Solid opaque | Gradient fade from 40% to 5% opacity |
| Bars | Flat solid fill | Rounded corners, hover highlight |
| Lines | 2px solid | 2-3px with optional drop-shadow glow |
| Layout | One chart per sheet tab | All charts in a scrollable dashboard |
| Responsiveness | None (spreadsheet) | Fully responsive 4-tier breakpoints |
| Load time | Google Sheets lag | Static JSON, instant render |

---

## Raw Data Tabs: Designing for Dashboard Consumption

Currently the scripts output CSV and the data lands in Google Sheets with
chart-oriented tabs (one tab per visual). For the dashboard, it's better to
have **raw data tabs** that the dashboard can parse predictably — and let the
React app handle all the chart logic, grouping, and formatting.

### Design Principles

1. **One tab per domain** — not per chart. A single "Cycle Time" raw tab feeds
   both the median and average charts.
2. **Row-per-observation** — the most granular level your scripts produce.
   Aggregation (monthly averages, YoY grouping) happens in the React app.
3. **Consistent date column** — always `YYYY-MM` in a column called `month`.
   The dashboard can parse this reliably.
4. **Year column** — explicit `year` column for easy YoY filtering without
   date parsing.
5. **No formulas, no merged cells** — pure flat data. Sheets formulas break
   API reads.
6. **Headers in row 1** — snake_case, no spaces. Makes JSON key mapping trivial.
7. **Append-friendly** — new months get appended as rows. No need to restructure.

### Recommended Raw Data Tabs

#### Tab: `raw_released_work`

Feeds: Released Tickets YoY, Released Points YoY, KPI cards

| Column | Type | Example | Source Script |
|--------|------|---------|---------------|
| `month` | text | `2026-02` | `released_tickets.py` |
| `year` | int | `2026` | derived |
| `ticket_count` | int | `135` | `released_tickets.py` |
| `total_points` | int | `300` | `released_tickets.py` |

```
month     | year | ticket_count | total_points
2023-01   | 2023 | 78           | 120
2023-02   | 2023 | 52           | 95
...
2026-01   | 2026 | 135          | 300
2026-02   | 2026 | 142          | 310
```

#### Tab: `raw_cycle_time`

Feeds: Cycle Time Median chart, Cycle Time Average chart

| Column | Type | Example | Source Script |
|--------|------|---------|---------------|
| `month` | text | `2026-02` | `cycle_time.py` |
| `year` | int | `2026` | derived |
| `team` | text | `Panda` | `cycle_time.py` |
| `assignee` | text | `jane.doe` | `cycle_time.py` |
| `cycle_time_hours` | float | `48.5` | `cycle_time.py` |
| `cycle_time_days` | float | `6.1` | `cycle_time.py` |

Keep it at the **individual ticket level** (or assignee/month level, whatever
`cycle_time.py` currently produces). The dashboard computes median and average
from this raw data — much more flexible than pre-aggregating.

```
month     | year | team  | assignee  | cycle_time_hours | cycle_time_days
2025-01   | 2025 | Panda | jane.doe  | 48.5             | 6.1
2025-01   | 2025 | Spork | bob.smith | 72.0             | 9.0
...
```

#### Tab: `raw_releases`

Feeds: Releases & Rollbacks chart, Web Releases YoY, KPI cards

| Column | Type | Example | Source Script |
|--------|------|---------|---------------|
| `month` | text | `2026-01` | `releases.py` |
| `year` | int | `2026` | derived |
| `repository` | text | `web-app` | `releases.py` |
| `release_count` | int | `14` | `releases.py` |
| `reverted_count` | int | `3` | `release_failure.py` |

```
month     | year | repository | release_count | reverted_count
2023-01   | 2023 | web-app    | 4             | 0
2023-01   | 2023 | api        | 3             | 1
...
2026-01   | 2026 | web-app    | 15            | 0
2026-01   | 2026 | api        | 14            | 3
```

The dashboard sums across repos for the total chart or filters to `web-app`
for the Web Releases chart.

#### Tab: `raw_work_focus`

Feeds: R&D Work Focus stacked bar chart

| Column | Type | Example | Source Script |
|--------|------|---------|---------------|
| `month` | text | `2026-01` | `engineering_excellence.py` |
| `year` | int | `2026` | derived |
| `team` | text | `All` | `engineering_excellence.py` |
| `product_pct` | float | `70.5` | `engineering_excellence.py` |
| `critical_pct` | float | `15.2` | derived (from work type) |
| `debt_reduction_pct` | float | `10.1` | derived |
| `operational_pct` | float | `4.2` | derived |

```
month     | year | team  | product_pct | critical_pct | debt_reduction_pct | operational_pct
2026-01   | 2026 | All   | 70.5        | 15.2         | 10.1               | 4.2
2026-01   | 2026 | Panda | 65.0        | 20.0         | 10.0               | 5.0
...
```

#### Tab: `raw_sla_compliance`

Feeds: Completed Work & SLAs chart, Vulnerability Look-Ahead chart, KPI cards

| Column | Type | Example | Source Script |
|--------|------|---------|---------------|
| `month` | text | `2026-03` | Apps Script / manual |
| `year` | int | `2026` | derived |
| `team` | text | `Panda` | Apps Script |
| `category` | text | `vulnerability` | Apps Script |
| `estimated_sla` | int | `170` | SLA target |
| `completed` | int | `145` | actual |
| `remaining` | int | `25` | estimated - completed |

```
month     | year | team  | category      | estimated_sla | completed | remaining
2026-01   | 2026 | All   | all_sla       | 5             | 2         | 3
2026-02   | 2026 | All   | all_sla       | 50            | 30        | 20
2026-03   | 2026 | All   | all_sla       | 170           | 145       | 25
2026-01   | 2026 | Panda | vulnerability | 3             | 1         | 2
...
```

#### Tab: `raw_bug_stats`

Feeds: potential bug trend chart (not in current catalog but useful to have)

| Column | Type | Example | Source Script |
|--------|------|---------|---------------|
| `month` | text | `2026-01` | `bug_stats.py` |
| `year` | int | `2026` | derived |
| `project` | text | `WEB` | `bug_stats.py` |
| `bugs_created` | int | `12` | `bug_stats.py` |
| `bugs_closed` | int | `15` | `bug_stats.py` |
| `bugs_open` | int | `8` | `bug_stats.py` |

```
month     | year | project | bugs_created | bugs_closed | bugs_open
2026-01   | 2026 | WEB     | 12           | 15          | 8
2026-01   | 2026 | API     | 5            | 7           | 3
...
```

---

### What About the Existing Chart Tabs?

Keep them. They're useful for people who open the spreadsheet directly. The
raw data tabs are an **addition**, not a replacement. The chart tabs can even
reference the raw tabs with formulas if you want to consolidate.

### How the Fetcher Uses These Tabs

The GitHub Action (or Apps Script `doGet()`) reads only the `raw_*` tabs:

```python
# In fetch_sheet_data.py
ranges = {
    "released_work":   "raw_released_work!A1:Z5000",
    "cycle_time":      "raw_cycle_time!A1:Z50000",
    "releases":        "raw_releases!A1:Z5000",
    "work_focus":      "raw_work_focus!A1:Z5000",
    "sla_compliance":  "raw_sla_compliance!A1:Z5000",
    "bug_stats":       "raw_bug_stats!A1:Z5000",
}
```

The resulting `metrics.json` mirrors this structure:

```json
{
  "released_work": [
    { "month": "2023-01", "year": 2023, "ticket_count": 78, "total_points": 120 },
    ...
  ],
  "cycle_time": [
    { "month": "2025-01", "year": 2025, "team": "Panda", "cycle_time_days": 6.1 },
    ...
  ],
  ...
}
```

The React app then does all the grouping, filtering, and math:

```javascript
// Example: compute median cycle time per month for a given year
function medianByMonth(cycleData, year) {
  const byMonth = groupBy(
    cycleData.filter((r) => r.year === year),
    "month"
  );
  return Object.entries(byMonth).map(([month, rows]) => ({
    month,
    median: median(rows.map((r) => r.cycle_time_days)),
  }));
}
```

### Future-Proofing

This design handles new years automatically — 2027 data just gets appended
as new rows with `year: 2027`. No tab restructuring, no new columns. The
YoY charts pick it up automatically because they group by the `year` column.

Adding a new metric (e.g., "code review turnaround time") means:
1. Add a `raw_code_review` tab with the same conventions
2. Add one entry to the fetcher's `ranges` dict
3. Build a new chart component

Nothing else changes.

---

## Recommended Implementation Order

1. **Set up the `dashboard/` directory** with Vite + React + Recharts
2. **Create a sample `metrics.json`** with realistic data to develop against
3. **Build the `YearOverYearChart` component** first — it covers 3 charts at once
4. **Build the stacked area, stacked bar, and combo chart** — one each
5. **Add the KPI summary cards** at the top
6. **Set up the GitHub Action** for deploying to Pages
7. **Add the data-fetching Action** (Approach 1) or Apps Script endpoint (Approach 2)
8. **Configure GitHub Pages** in repo settings (Settings > Pages > Source: GitHub Actions)
9. **Iterate** on the dashboard design with real data

---

## Cost

- **Google Cloud**: Free tier covers the Sheets API usage easily
- **GitHub Actions**: Free tier includes 2,000 minutes/month for private repos — hourly data fetch uses ~30 min/month
- **GitHub Pages**: Included in all plans
- **Total**: $0
