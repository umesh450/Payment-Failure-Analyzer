"""
Core analysis engine for payment failure data.

Computes aggregate failure statistics, groups failures by dimension
(bank, payment method, error code, device, hour of day), and produces
a set of "insights" — human-readable explanations for why failures
are clustering the way they are. An optional LLM layer (see llm.py)
can turn these raw insights into a natural-language summary.
"""

from __future__ import annotations

import io
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = [
    "transaction_id",
    "timestamp",
    "amount",
    "payment_method",
    "bank",
    "status",
    "error_code",
    "device_type",
    "is_new_device",
    "retry_count",
]


VALID_STATUSES = {"success", "failed"}


def load_csv(file_bytes: bytes) -> pd.DataFrame:
    """Parse uploaded CSV bytes into a validated DataFrame.

    Raises ValueError with a specific, actionable message if:
      - required columns are missing
      - any row has a blank/invalid `status` value
      - any row has a blank/unparseable `timestamp`

    This exists because of a real bug found during testing: rows with a
    blank `status` were silently dropped from both the "failed" and
    "success" groups downstream (compute_summary uses `== "failed"` /
    `== "success"` filters), so the app returned HTTP 200 with a
    plausible-looking but wrong summary instead of flagging bad input.
    """
    df = pd.read_csv(io.BytesIO(file_bytes))

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    # Normalize status for comparison, but keep original for error messages.
    status_clean = df["status"].astype(str).str.strip().str.lower()
    invalid_status_mask = ~status_clean.isin(VALID_STATUSES)
    if invalid_status_mask.any():
        bad_rows = df.loc[invalid_status_mask, "transaction_id"].astype(str).tolist()
        raise ValueError(
            "Found rows with a blank or invalid 'status' value (must be "
            f"'success' or 'failed'). Affected transaction_id(s): {bad_rows[:10]}"
            + (" ...and more" if len(bad_rows) > 10 else "")
        )

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    if df["timestamp"].isna().any():
        bad_rows = df.loc[df["timestamp"].isna(), "transaction_id"].astype(str).tolist()
        raise ValueError(
            f"Found rows with a blank or unparseable 'timestamp'. "
            f"Affected transaction_id(s): {bad_rows[:10]}"
            + (" ...and more" if len(bad_rows) > 10 else "")
        )

    df["is_new_device"] = df["is_new_device"].astype(str).str.lower() == "true"
    return df


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(100 * numerator / denominator, 1)


def compute_summary(df: pd.DataFrame) -> dict[str, Any]:
    total = len(df)
    failed = df[df["status"] == "failed"]
    succeeded = df[df["status"] == "success"]
    fail_count = len(failed)

    overall_failure_rate = _rate(fail_count, total)

    by_bank = (
        failed.groupby("bank").size().sort_values(ascending=False).to_dict()
    )
    by_method = (
        failed.groupby("payment_method").size().sort_values(ascending=False).to_dict()
    )
    by_error = (
        failed.groupby("error_code").size().sort_values(ascending=False).to_dict()
    )

    failed = failed.copy()
    failed["hour"] = failed["timestamp"].dt.hour
    by_hour = failed.groupby("hour").size().sort_values(ascending=False).to_dict()

    new_device_failures = int(failed["is_new_device"].sum())
    high_retry_failures = int((failed["retry_count"] >= 2).sum())

    return {
        "total_transactions": total,
        "failed_transactions": fail_count,
        "successful_transactions": len(succeeded),
        "overall_failure_rate_pct": overall_failure_rate,
        "failures_by_bank": by_bank,
        "failures_by_payment_method": by_method,
        "failures_by_error_code": by_error,
        "failures_by_hour": by_hour,
        "new_device_failure_count": new_device_failures,
        "high_retry_failure_count": high_retry_failures,
    }


def generate_insights(summary: dict[str, Any]) -> list[dict[str, str]]:
    """
    Rule-based insight generation. This is the deterministic fallback/
    baseline that runs even without an LLM call, and also acts as the
    structured input handed to the LLM for narrative summarization.
    """
    insights: list[dict[str, str]] = []

    errors = summary["failures_by_error_code"]
    total_failed = summary["failed_transactions"] or 1

    if errors:
        top_error, top_error_count = next(iter(errors.items()))
        share = _rate(top_error_count, total_failed)
        if top_error == "BANK_TIMEOUT" and share >= 30:
            insights.append({
                "title": "Bank timeouts dominate failures",
                "detail": (
                    f"{top_error_count} of {total_failed} failures ({share}%) are "
                    "BANK_TIMEOUT errors. This usually points to issues on the "
                    "issuing bank's or PSP's end rather than the merchant "
                    "integration — often tied to specific banks or peak-hour load."
                ),
                "recommendation": (
                    "Add automatic retry with backoff for BANK_TIMEOUT, and route "
                    "repeat offenders through an alternate payment gateway/bank "
                    "during peak hours."
                ),
            })
        elif top_error == "INSUFFICIENT_FUNDS":
            insights.append({
                "title": "Insufficient funds is a leading failure cause",
                "detail": (
                    f"{top_error_count} of {total_failed} failures ({share}%) are "
                    "INSUFFICIENT_FUNDS. These are not recoverable via retry — "
                    "they reflect genuine account balance issues, often on "
                    "higher-value transactions."
                ),
                "recommendation": (
                    "Offer alternate payment methods (UPI/lower-limit card) or "
                    "EMI options at the failure point instead of a blind retry."
                ),
            })
        elif top_error == "OTP_MISMATCH":
            insights.append({
                "title": "OTP mismatches suggest UX friction",
                "detail": (
                    f"{top_error_count} of {total_failed} failures ({share}%) are "
                    "OTP_MISMATCH, frequently correlated with high retry counts — "
                    "a sign users are struggling with the OTP entry flow."
                ),
                "recommendation": (
                    "Test OTP auto-read/autofill on mobile, and add a clearer "
                    "'resend OTP' affordance with a visible countdown."
                ),
            })

    banks = summary["failures_by_bank"]
    if banks:
        top_bank, top_bank_count = next(iter(banks.items()))
        share = _rate(top_bank_count, total_failed)
        if share >= 25:
            insights.append({
                "title": f"{top_bank} accounts for a disproportionate share of failures",
                "detail": (
                    f"{top_bank_count} of {total_failed} failures ({share}%) involve "
                    f"{top_bank}. If this exceeds {top_bank}'s share of total "
                    "transaction volume, it points to a bank-specific issue."
                ),
                "recommendation": (
                    f"Flag {top_bank} to your PSP/acquiring bank contact and monitor "
                    "whether the failure rate for that bank improves over the next "
                    "billing cycle."
                ),
            })

    hours = summary["failures_by_hour"]
    if hours:
        peak_hour, peak_count = next(iter(hours.items()))
        insights.append({
            "title": f"Failures cluster around {peak_hour}:00",
            "detail": (
                f"{peak_count} failures occurred in the {peak_hour}:00 hour, the "
                "single busiest failure window in this dataset."
            ),
            "recommendation": (
                "Check gateway/bank capacity and queueing behavior during this "
                "window — it may correlate with traffic spikes."
            ),
        })

    if summary["new_device_failure_count"] > 0:
        insights.append({
            "title": "New-device transactions show elevated failures",
            "detail": (
                f"{summary['new_device_failure_count']} failed transactions came "
                "from a device not previously seen for that user, which can "
                "trigger stricter bank-side fraud checks and step-up "
                "authentication."
            ),
            "recommendation": (
                "Ensure step-up authentication flows (3DS/OTP) are well-tested "
                "on new devices, since this is a likely source of drop-off."
            ),
        })

    if not insights:
        insights.append({
            "title": "No dominant failure pattern detected",
            "detail": "Failures are fairly evenly distributed across banks, methods, and error codes.",
            "recommendation": "Continue monitoring; consider a larger data sample for stronger signal.",
        })

    return insights
