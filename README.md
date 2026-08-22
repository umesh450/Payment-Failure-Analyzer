# Smart Payment Failure Analyzer

Built for the Razorpay AI Buildathon.

Payment failures cost merchants real money, and the reasons behind them are
often buried in raw transaction logs. This tool takes a transaction CSV and
turns it into a clear diagnostic: **which banks, payment methods, and error
codes are driving failures**, when they cluster, and what to actually do
about each one — with an optional AI-generated plain-English summary on top.

## What it does

1. **Upload a CSV** of transactions (or use the bundled sample dataset).
2. The backend computes failure rates broken down by bank, payment method,
   error code, device type, and hour of day.
3. A rule-based insight engine turns those numbers into specific,
   actionable findings (e.g. "BANK_TIMEOUT dominates failures — add retry
   with backoff and route through an alternate gateway during peak hours").
4. If an Anthropic API key is configured, Claude generates a short natural-
   language executive summary on top of those same insights — the AI layer
   never invents numbers, it only narrates what the rule-based engine found.
5. Everything is shown on a single dashboard.

## Why this approach

The core insight logic is deterministic and auditable — every number a
merchant sees traces back to their actual data, not an LLM hallucination.
The AI layer is additive: it makes the findings easier to skim, but the app
is fully functional (and honest) without an API key at all.

## Tech stack

- **Backend:** Python, FastAPI, pandas
- **AI layer:** Anthropic Claude (`anthropic` Python SDK) — optional
- **Frontend:** Plain HTML/CSS/JS (no build step)

## Project structure

```
payment-failure-analyzer/
├── app/
│   ├── main.py          # FastAPI app + routes
│   ├── analyzer.py       # CSV parsing + rule-based insight engine
│   ├── llm.py             # Optional Claude narrative summary layer
│   └── static/
│       └── index.html    # Dashboard frontend
├── data/
│   └── sample_transactions.csv   # Demo dataset
├── requirements.txt
├── .env.example
└── README.md
```

## Running it locally

```bash
# 1. Clone and enter the repo
git clone https://github.com/umesh450/payment-failure-analyzer.git
cd payment-failure-analyzer

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) enable AI summaries
cp .env.example .env
# then edit .env and add your ANTHROPIC_API_KEY

# 5. Run the server
uvicorn app.main:app --reload

# 6. Open the dashboard
# http://127.0.0.1:8000
```

Click **"Try sample data"** on the dashboard for an instant demo — no CSV
upload needed.

## CSV format

Your CSV needs these columns:

| Column | Description |
|---|---|
| `transaction_id` | Unique ID |
| `timestamp` | e.g. `2026-08-15 09:12:03` |
| `amount` | Transaction amount |
| `payment_method` | `UPI`, `card`, `netbanking`, etc. |
| `bank` | Issuing/receiving bank |
| `status` | `success` or `failed` |
| `error_code` | e.g. `BANK_TIMEOUT`, `INSUFFICIENT_FUNDS`, `OTP_MISMATCH` (blank if success) |
| `device_type` | `mobile` or `desktop` |
| `is_new_device` | `true`/`false` |
| `retry_count` | Number of retries attempted |

See `data/sample_transactions.csv` for a working example.

## API

- `POST /api/analyze` — upload a CSV file, get back summary + insights
- `GET /api/sample` — analyze the bundled sample dataset
- `GET /api/health` — health check

## Roadmap / what I'd add next

- Persist uploaded datasets and compare failure trends over time
- Per-merchant benchmarking against anonymized aggregate failure rates
- Slack/email alerting when a bank's failure rate spikes above baseline
- Support for JSON/webhook ingestion in addition to CSV upload

## Why this fits Razorpay

Payment failure analysis sits at the center of what a payments platform
needs to get right for merchants — every percentage point of avoidable
failure is recovered revenue. This project is scoped to be a believable
first version of an internal tool, not just a toy demo.

## What broke during validation

The most dangerous bug in this project was not a hard crash — it was a
silent failure in CSV validation.

During testing, we intentionally uploaded a broken CSV where one row had a
blank `status` value. The app accepted the file, returned HTTP 200, and
rendered a neat-looking summary with misleading numbers instead of flagging
bad input. The underlying cause was in `load_csv()`: it checked whether the
required columns existed, but it did not validate each row's `status` and
`timestamp` before analysis began. As a result, invalid rows were silently
dropped from the `failed` and `success` filters, and the dashboard showed
plausible but wrong metrics.

The fix: added explicit validation in `load_csv()` that checks every row's
`status` and `timestamp` before analysis runs, and raises a clear error
listing exactly which transaction IDs are problematic — instead of silently
dropping bad rows and returning misleading numbers.
