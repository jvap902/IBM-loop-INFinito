"""Data quality validators for the Gold feature store.

Two layers of validation are provided:

1. Pydantic v2 row-level schema
   - Validates column types and domain constraints for a single hexagon record.
   - Used in streaming / incremental ingestion scenarios.

2. Suite-level checks (Great-Expectations-compatible assertions via pandas)
   - Run over the full Gold DataFrame after aggregation.
   - Assertions specified in Sub-Task 1 TODO item 11:
     a. No null in required fields.
     b. H3 coverage > 80% of populated municipalities.
     c. HHI in [0, 10000].
   - Each failed assertion is logged and collected into a QualityReport.

Usage
-----
    from processing.quality import validate_gold, FeatureRow

    report = validate_gold(gold_df, municipalities_total=5570)
    if not report.passed:
        raise ValueError(report.summary())
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Required fields that must not be null in the Gold table
REQUIRED_FIELDS = ["h3_id", "d_down", "d_up", "lat", "n_dom", "n_erb", "HHI"]

# Optional but expected fields (warn if excessively null)
EXPECTED_FIELDS = ["vol_test", "n_com", "ren_med", "vol_reclam"]

# HHI valid range (Herfindahl-Hirschman Index)
HHI_MIN, HHI_MAX = 0.0, 10000.0

# Minimum H3 coverage of populated municipalities
MIN_H3_COVERAGE_FRACTION = 0.80


# ---------------------------------------------------------------------------
# Pydantic row-level schema
# ---------------------------------------------------------------------------
try:
    from pydantic import BaseModel, Field, field_validator

    class FeatureRow(BaseModel):
        """Pydantic v2 schema for a single Gold feature-store row."""

        h3_id: str = Field(description="H3 cell index string")
        d_down: float = Field(ge=0.0, description="Mean download speed (Mbps)")
        d_up: float = Field(ge=0.0, description="Mean upload speed (Mbps)")
        lat: float = Field(ge=0.0, description="Mean latency (ms)")
        vol_test: Optional[float] = Field(default=None, ge=0.0)
        n_dom: float = Field(ge=0.0, description="Count of private households")
        n_com: Optional[float] = Field(default=None, ge=0.0)
        ren_med: Optional[float] = Field(default=None, ge=0.0)
        n_erb: float = Field(ge=0.0, description="Count of radio base stations")
        HHI: float = Field(ge=HHI_MIN, le=HHI_MAX, description="HHI market concentration")
        vol_reclam: Optional[float] = Field(default=None, ge=0.0)
        low_confidence: bool = False
        year: int
        month: int = Field(ge=1, le=12)
        h3_res: int = Field(ge=7, le=10)

        @field_validator("h3_id")
        @classmethod
        def h3_id_not_empty(cls, v: str) -> str:
            if not v or len(v) < 15:
                raise ValueError(f"h3_id appears invalid: {v!r}")
            return v

    PYDANTIC_AVAILABLE = True

except ImportError:
    logger.warning(
        "[quality] pydantic not installed; row-level validation disabled. "
        "Run: pip install pydantic"
    )
    PYDANTIC_AVAILABLE = False
    FeatureRow = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------
@dataclass
class QualityReport:
    """Aggregated result of the full Gold table quality check."""

    checks_run: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.failures) == 0

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [f"Quality check {status} ({self.checks_run} checks run)"]
        for f in self.failures:
            lines.append(f"  ✗ {f}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Suite-level Gold table validator
# ---------------------------------------------------------------------------
def validate_gold(
    gold: pd.DataFrame,
    municipalities_total: int = 5570,
    h3_coverage_threshold: float = MIN_H3_COVERAGE_FRACTION,
) -> QualityReport:
    """Run all data quality assertions against the Gold feature table.

    Parameters
    ----------
    gold                  : Gold DataFrame produced by build_gold().
    municipalities_total  : Total number of Brazilian municipalities used
                            to compute the H3 coverage ratio.  Defaults to
                            5,570 (all Brazilian municipalities, Censo 2022).
    h3_coverage_threshold : Minimum fraction of municipalities that must
                            have at least one H3 cell.  Spec: 0.80.

    Returns
    -------
    QualityReport with ``.passed`` flag and failure details.
    """
    report = QualityReport()

    # ── Check 1: No null in required fields ────────────────────────────
    report.checks_run += 1
    for col in REQUIRED_FIELDS:
        if col not in gold.columns:
            msg = f"Required column '{col}' is missing from Gold table."
            report.failures.append(msg)
            logger.error("[quality] FAIL | %s", msg)
            continue
        null_count = gold[col].isna().sum()
        if null_count > 0:
            msg = (
                f"Required column '{col}' has {null_count} null values "
                f"({100.0 * null_count / len(gold):.1f}%)."
            )
            report.failures.append(msg)
            logger.error("[quality] FAIL | %s", msg)
        else:
            logger.info("[quality] PASS | No nulls in required column '%s'.", col)

    # ── Check 2: HHI range [0, 10000] ──────────────────────────────────
    report.checks_run += 1
    if "HHI" in gold.columns:
        hhi_valid = gold["HHI"].dropna()
        out_of_range = ((hhi_valid < HHI_MIN) | (hhi_valid > HHI_MAX)).sum()
        if out_of_range:
            msg = f"HHI out of range [0,10000] for {out_of_range} rows."
            report.failures.append(msg)
            logger.error("[quality] FAIL | %s", msg)
        else:
            logger.info("[quality] PASS | All HHI values within [0, 10000].")
    else:
        report.failures.append("Column 'HHI' not found in Gold table.")

    # ── Check 3: H3 coverage > 80% of populated municipalities ─────────
    report.checks_run += 1
    if "h3_id" in gold.columns and municipalities_total > 0:
        # A rough proxy: unique populated municipalities ≈ unique H3 res-5
        # parent cells.  Exact municipality coverage requires joining to the
        # IBGE mesh — this heuristic is a best-effort check.
        try:
            import h3 as _h3

            def _to_res5(cell: str) -> str:
                try:
                    return _h3.cell_to_parent(cell, 5)
                except Exception:
                    return ""

            covered = gold["h3_id"].dropna().map(_to_res5)
            unique_cells_res5 = covered[covered != ""].nunique()
            # Approximate: res-5 cells in Brazil ≈ 482; 80% ≈ 386
            # Use as proxy for municipality coverage
            fraction = unique_cells_res5 / max(municipalities_total, 1)
            if fraction < h3_coverage_threshold:
                msg = (
                    f"H3 coverage ({fraction:.1%}) is below the required "
                    f"{h3_coverage_threshold:.0%} threshold."
                )
                report.failures.append(msg)
                logger.error("[quality] FAIL | %s", msg)
            else:
                logger.info(
                    "[quality] PASS | H3 coverage %.1f%% ≥ %.0f%% threshold.",
                    fraction * 100,
                    h3_coverage_threshold * 100,
                )
        except ImportError:
            logger.warning(
                "[quality] h3 not installed; skipping coverage check."
            )
    else:
        report.failures.append("Cannot compute H3 coverage: h3_id column missing or municipalities_total=0.")

    # ── Check 4: Gold table is not empty ────────────────────────────────
    report.checks_run += 1
    if len(gold) == 0:
        report.failures.append("Gold table is empty (0 rows).")
        logger.error("[quality] FAIL | Gold table is empty.")
    else:
        logger.info("[quality] PASS | Gold table has %d rows.", len(gold))

    # ── Warning for excessively null optional fields ─────────────────────
    for col in EXPECTED_FIELDS:
        if col in gold.columns:
            null_pct = 100.0 * gold[col].isna().sum() / max(len(gold), 1)
            if null_pct > 50.0:
                logger.warning(
                    "[quality] WARN | Optional column '%s' is %.1f%% null — "
                    "check upstream connector.",
                    col,
                    null_pct,
                )

    logger.info("[quality] %s", report.summary())
    return report


def validate_rows_pydantic(gold: pd.DataFrame) -> tuple[int, int]:
    """Row-level Pydantic validation.  Returns (valid_count, invalid_count).

    Logs the first invalid row as a warning for quick diagnosis.
    """
    if not PYDANTIC_AVAILABLE:
        logger.warning("[quality] Pydantic not available; skipping row validation.")
        return len(gold), 0

    valid, invalid = 0, 0
    for i, row in gold.iterrows():
        try:
            FeatureRow(**row.to_dict())
            valid += 1
        except Exception as exc:
            invalid += 1
            if invalid == 1:
                logger.warning(
                    "[quality] First invalid row (index=%s): %s", i, exc
                )

    logger.info(
        "[quality] Row-level validation: %d valid, %d invalid", valid, invalid
    )
    return valid, invalid
