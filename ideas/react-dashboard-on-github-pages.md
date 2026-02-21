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

## Recommended Implementation Order

1. **Set up the `dashboard/` directory** with Vite + React + Recharts
2. **Create a sample `metrics.json`** with realistic data to develop against
3. **Build 2-3 chart components** to prove out the visualization approach
4. **Set up the GitHub Action** for deploying to Pages
5. **Add the data-fetching Action** (Approach 1) or Apps Script endpoint (Approach 2)
6. **Configure GitHub Pages** in repo settings (Settings > Pages > Source: GitHub Actions)
7. **Iterate** on the dashboard design with real data

---

## Cost

- **Google Cloud**: Free tier covers the Sheets API usage easily
- **GitHub Actions**: Free tier includes 2,000 minutes/month for private repos — hourly data fetch uses ~30 min/month
- **GitHub Pages**: Included in all plans
- **Total**: $0
