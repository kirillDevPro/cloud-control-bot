"""Repository for balance history."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

from .base import BaseRepository

if TYPE_CHECKING:
    from typing import Self

logger = logging.getLogger(__name__)


@dataclass
class BurnRateResult:
    """Result of a burn-rate calculation via linear regression."""

    burn_rate: float | None  # $/day (None if not enough data)
    trend: str  # "decreasing" | "increasing" | "stable" | "unknown"
    days_left: float | None  # days until depletion
    data_points: int  # number of records used in the calculation
    period_hours: float  # period span in hours


def _linear_regression(x: list[float], y: list[float]) -> tuple[float, float]:
    """
    Compute a linear regression using the least-squares method.

    Args:
        x: List of X values (time in days)
        y: List of Y values (effective_balance)

    Returns:
        tuple[float, float]: (slope, intercept)
    """
    n = len(x)
    if n < 2:
        return 0.0, 0.0

    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi * xi for xi in x)

    # Formula: slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x^2)
    denominator = n * sum_x2 - sum_x * sum_x

    if abs(denominator) < 1e-10:
        # All X points are identical - no slope
        return 0.0, sum_y / n if n > 0 else 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n

    return slope, intercept


class BaseBalanceRecord(BaseModel, ABC):
    """
    Base class for a balance record.

    Defines the common interface for prepaid and postpaid billing models.
    All subclasses must implement the abstract properties.
    """

    timestamp: datetime = Field(default_factory=datetime.now, description="Balance check timestamp")
    provider_type: str = Field(..., description="Provider type (vultr, hetzner, aws, etc.)")
    provider_alias: str = Field(
        default="",
        description="Provider instance alias (e.g. 'hetzner_prod')",
    )

    @property
    @abstractmethod
    def display_value(self) -> float:
        """
        Primary value to display in the UI.

        For prepaid: effective_balance (available balance)
        For postpaid: monthly_costs (month-to-date spending)
        """
        pass

    @property
    @abstractmethod
    def billing_model(self) -> str:
        """
        Billing model of the provider.

        Returns:
            str: 'prepaid' or 'postpaid'
        """
        pass

    @abstractmethod
    def should_check_threshold(self) -> bool:
        """
        Determine whether the balance threshold should be checked for notifications.

        Returns:
            bool: True if the threshold should be checked
        """
        pass

    @abstractmethod
    def format_summary(self) -> str:
        """
        Format a short summary for the UI.

        Returns:
            str: Short summary (e.g. "$50.00" or "$30.00 MTD")
        """
        pass


class PrepaidBalanceRecord(BaseBalanceRecord):
    """
    Balance record for prepaid providers (Vultr, Hetzner).

    Prepaid model:
    - balance = funds remaining on the account (positive number)
    - pending_charges = upcoming charges (accrued over the month)
    - effective_balance = balance - pending_charges (actual available balance)

    IMPORTANT: The Vultr API returns balance with a negative sign!
    In this model balance is already converted (multiplied by -1).
    """

    balance: float = Field(
        ...,
        ge=0,
        description="Current balance in USD for prepaid providers (positive value)",
    )
    pending_charges: float = Field(
        default=0.0,
        ge=0,
        description="Upcoming charges in USD",
    )
    last_payment_date: datetime | None = Field(default=None, description="Date of the last payment")
    last_payment_amount: float | None = Field(
        default=None, ge=0, description="Amount of the last payment in USD"
    )

    @property
    def effective_balance(self) -> float:
        """
        Effective balance = balance - pending_charges.

        For Vultr: balance is updated once a month when charges are deducted,
        while pending_charges accrues over the month.
        The actual available balance = balance - pending_charges.

        Returns:
            float: Effective available balance
        """
        return self.balance - self.pending_charges

    @property
    def display_value(self) -> float:
        """For prepaid records, display effective_balance."""
        return self.effective_balance

    @property
    def billing_model(self) -> str:
        """Prepaid billing model."""
        return "prepaid"

    def should_check_threshold(self) -> bool:
        """Prepaid providers require threshold checking."""
        return True

    def format_summary(self) -> str:
        """Format the balance for a short display."""
        return f"${self.effective_balance:.2f}"

    @model_validator(mode="after")
    def validate_semantic(self) -> "Self":
        """Validate the semantic correctness of the record."""
        # pending_charges cannot exceed twice the balance
        # (guard against data-entry errors)
        if self.balance > 0 and self.pending_charges > self.balance * 2:
            raise ValueError(
                f"pending_charges ({self.pending_charges}) too high "
                f"relative to balance ({self.balance})"
            )
        return self


class PostpaidBalanceRecord(BaseBalanceRecord):
    """
    Spending record for postpaid providers (AWS).

    Postpaid model:
    - monthly_costs = spending for the current month (MTD - Month To Date)
    - There is no notion of "balance" - billed at month end based on actual usage
    - Checking a threshold for notifications makes no sense
    """

    monthly_costs: float = Field(
        ...,
        ge=0,
        description="Spending for the current month (MTD) in USD",
    )

    @property
    def display_value(self) -> float:
        """For postpaid records, display monthly_costs."""
        return self.monthly_costs

    @property
    def billing_model(self) -> str:
        """Postpaid billing model."""
        return "postpaid"

    def should_check_threshold(self) -> bool:
        """Postpaid providers do NOT require balance threshold checking."""
        return False

    def format_summary(self) -> str:
        """Format the spending for a short display."""
        return f"${self.monthly_costs:.2f} MTD"


# Type alias for use throughout the code
BalanceRecord = PrepaidBalanceRecord | PostpaidBalanceRecord


class BalanceRepository(BaseRepository[BalanceRecord]):
    """
    Repository for working with balance history.

    Stores the history of balance checks for trend analysis and forecasting.
    Supports both record types: PrepaidBalanceRecord and PostpaidBalanceRecord.
    """

    # Maximum number of records kept in history
    MAX_HISTORY_RECORDS = 10000

    def __init__(self, file_path: Path):
        """
        Initialize the balance repository.

        Args:
            file_path: Path to balance_history.json
        """
        super().__init__(file_path)

    def _get_empty_data(self) -> list:
        """Return an empty list for initialization."""
        return []

    def _deserialize_record(self, data: dict) -> BalanceRecord:
        """
        Deserialize a record from a dict into the correct type.

        Determines the type by the presence of the monthly_costs field.

        Args:
            data: Dict with the record data

        Returns:
            PrepaidBalanceRecord or PostpaidBalanceRecord
        """
        # If monthly_costs is present and not None - it is postpaid
        if data.get("monthly_costs") is not None:
            return PostpaidBalanceRecord(**data)
        # Otherwise - prepaid
        return PrepaidBalanceRecord(**data)

    def add_record(self, record: BalanceRecord) -> None:
        """
        Add a new balance record.

        Args:
            record: Balance record (PrepaidBalanceRecord or PostpaidBalanceRecord)
        """
        data = self._read_json()
        data.append(record.model_dump())

        # Cap the number of records
        if len(data) > self.MAX_HISTORY_RECORDS:
            data = data[-self.MAX_HISTORY_RECORDS :]

        self._write_json(data)

    def get_all_records(self) -> list[BalanceRecord]:
        """
        Get all balance history records.

        Returns:
            list[BalanceRecord]: List of records (oldest to newest)
        """
        data = self._read_json()
        records = [self._deserialize_record(item) for item in data]

        # Sort by time
        records.sort(key=lambda r: r.timestamp)

        return records

    def get_latest_record(
        self, provider: str | None = None, provider_alias: str | None = None
    ) -> BalanceRecord | None:
        """
        Get the latest balance record.

        Args:
            provider: Filter by provider type (vultr, hetzner, etc.)
            provider_alias: Filter by provider alias (hetzner_prod, etc.)

        Returns:
            BalanceRecord | None: The latest record or None
        """
        records = self.get_all_records()

        if provider_alias:
            records = [r for r in records if r.provider_alias == provider_alias]
        elif provider:
            records = [r for r in records if r.provider_type == provider]

        return records[-1] if records else None

    def get_records_for_period(
        self, start_date: datetime, end_date: datetime | None = None
    ) -> list[BalanceRecord]:
        """
        Get records within a period.

        Args:
            start_date: Start of the period
            end_date: End of the period (if None, up to the current moment)

        Returns:
            list[BalanceRecord]: Records within the period
        """
        if end_date is None:
            end_date = datetime.now()

        all_records = self.get_all_records()

        return [record for record in all_records if start_date <= record.timestamp <= end_date]

    def get_recent_records(
        self,
        days: int = 30,
        provider: str | None = None,
        provider_alias: str | None = None,
    ) -> list[BalanceRecord]:
        """
        Get records from the last N days.

        Args:
            days: Number of days
            provider: Filter by provider type (vultr, hetzner, etc.)
            provider_alias: Filter by provider alias (hetzner_prod, etc.)

        Returns:
            list[BalanceRecord]: Records within the period
        """
        start_date = datetime.now() - timedelta(days=days)
        records = self.get_records_for_period(start_date)

        if provider_alias:
            records = [r for r in records if r.provider_alias == provider_alias]
        elif provider:
            records = [r for r in records if r.provider_type == provider]

        return records

    def get_last_deposit_date(
        self,
        provider: str | None = None,
        provider_alias: str | None = None,
    ) -> datetime | None:
        """
        Get the date of the last deposit.

        Args:
            provider: Filter by provider type (legacy)
            provider_alias: Filter by provider alias (new)

        Returns:
            datetime | None: Date of the last deposit or None
        """
        latest = self.get_latest_record(
            provider=provider,
            provider_alias=provider_alias,
        )

        if not latest or not isinstance(latest, PrepaidBalanceRecord):
            return None

        return latest.last_payment_date

    # Epsilon for float comparisons (prevents division by ~0)
    _FLOAT_EPSILON = 1e-10

    def _calculate_spending_trend(
        self, records: list[PrepaidBalanceRecord]
    ) -> str:
        """
        Determine the SPENDING trend (not the balance trend).

        Compares the burn_rate of the first and second halves of the records.
        If spending is higher in the second half, the trend is "increasing".
        If lower, "decreasing".

        Args:
            records: Prepaid records sorted by time

        Returns:
            str: "increasing", "decreasing", "stable", "unknown"
        """
        if len(records) < 4:
            # Not enough data to compare two periods
            return "unknown"

        mid = len(records) // 2

        # First half
        first_half = records[:mid]
        first_start = first_half[0]
        first_end = first_half[-1]
        first_hours = (first_end.timestamp - first_start.timestamp).total_seconds() / 3600

        # Second half
        second_half = records[mid:]
        second_start = second_half[0]
        second_end = second_half[-1]
        second_hours = (second_end.timestamp - second_start.timestamp).total_seconds() / 3600

        # Need at least 1 hour in each half (guards against division by ~0)
        if first_hours < 1 or second_hours < 1:
            return "unknown"

        # Extra guard against dividing by very small values
        if abs(first_hours) < self._FLOAT_EPSILON or abs(second_hours) < self._FLOAT_EPSILON:
            return "unknown"

        # Spending = change in pending_charges over the period
        first_spending = first_end.pending_charges - first_start.pending_charges
        second_spending = second_end.pending_charges - second_start.pending_charges

        # Normalize per hour
        first_rate = first_spending / first_hours
        second_rate = second_spending / second_hours

        # Compare (1% change threshold)
        # Use epsilon for safe float comparison
        if abs(first_rate) < self._FLOAT_EPSILON:
            if second_rate > self._FLOAT_EPSILON:
                return "increasing"
            return "stable"

        change_percent = (second_rate - first_rate) / first_rate * 100

        if change_percent > 1:
            return "increasing"  # Spending is growing
        elif change_percent < -1:
            return "decreasing"  # Spending is falling
        else:
            return "stable"  # Spending is stable

    def calculate_burn_rate_regression(
        self,
        provider: str | None = None,
        provider_alias: str | None = None,
    ) -> BurnRateResult:
        """
        Compute the burn rate via linear regression over effective_balance.

        IMPORTANT: This only makes sense for prepaid providers!

        Algorithm:
        1. Determine the period: from the last deposit, but no earlier than 30 days ago
        2. Filter prepaid records within that period
        3. Detect a pending_charges reset (start of a new month) and keep
           only the records after it
        4. Check the minimum requirements: 2 records more than 12 hours apart
        5. Compute the linear regression over effective_balance
        6. burn_rate = -slope (a negative slope = spending)

        Args:
            provider: Filter by provider type (vultr, hetzner, etc.) - legacy
            provider_alias: Filter by provider alias (hetzner_prod, etc.) - new

        Returns:
            BurnRateResult: Calculation result with burn_rate, trend, days_left
        """
        # Determine the period
        now = datetime.now()
        max_period_start = now - timedelta(days=30)

        # Get the date of the last deposit
        deposit_date = self.get_last_deposit_date(
            provider=provider,
            provider_alias=provider_alias,
        )

        if deposit_date:
            # Normalize timezone
            deposit_date_naive = (
                deposit_date.replace(tzinfo=None) if deposit_date.tzinfo else deposit_date
            )
            start_date = max(deposit_date_naive, max_period_start)
        else:
            start_date = max_period_start

        # Get prepaid records within the period
        all_records = self.get_all_records()

        def matches_filter(r: BalanceRecord) -> bool:
            """Check whether the record matches the filter."""
            if provider_alias:
                return r.provider_alias == provider_alias
            if provider:
                return r.provider_type == provider
            return True

        records = [
            r
            for r in all_records
            if isinstance(r, PrepaidBalanceRecord)
            and r.timestamp >= start_date
            and matches_filter(r)
        ]

        # Check the minimum requirements
        if len(records) < 2:
            return BurnRateResult(
                burn_rate=None,
                trend="unknown",
                days_left=None,
                data_points=len(records),
                period_hours=0.0,
            )

        # Sort by time
        records.sort(key=lambda r: r.timestamp)

        # Detect a pending_charges reset (start of a new month)
        # Reset = pending_charges dropped sharply (previous > $100 AND current < 50% of previous)
        last_reset_idx = 0
        for i in range(1, len(records)):
            prev_pending = records[i - 1].pending_charges
            curr_pending = records[i].pending_charges
            # Detect a reset: current pending is significantly lower than the previous one
            if prev_pending > 100 and curr_pending < prev_pending * 0.5:
                last_reset_idx = i

        # Keep only the records after the last reset
        if last_reset_idx > 0:
            records = records[last_reset_idx:]

        # Re-check the minimum requirements after filtering
        if len(records) < 2:
            return BurnRateResult(
                burn_rate=None,
                trend="unknown",
                days_left=None,
                data_points=len(records),
                period_hours=0.0,
            )

        first_timestamp = records[0].timestamp
        last_timestamp = records[-1].timestamp
        period_seconds = (last_timestamp - first_timestamp).total_seconds()
        period_hours = period_seconds / 3600

        # Check the time span (minimum 12 hours)
        if period_hours < 12:
            return BurnRateResult(
                burn_rate=None,
                trend="unknown",
                days_left=None,
                data_points=len(records),
                period_hours=period_hours,
            )

        # Prepare the data for regression
        x = [(r.timestamp - first_timestamp).total_seconds() / 86400 for r in records]
        y = [r.effective_balance for r in records]

        # Compute the linear regression
        slope, _ = _linear_regression(x, y)

        # burn_rate = -slope (negative slope = spending = positive burn_rate)
        burn_rate = -slope

        # Determine the SPENDING trend (not the balance trend!)
        # Compare the burn_rate of the first and second halves of the records
        trend = self._calculate_spending_trend(records)

        # Compute days_left
        days_left: float | None = None
        if burn_rate > 0:
            current_balance = records[-1].effective_balance
            if current_balance > 0:
                days_left = current_balance / burn_rate

        return BurnRateResult(
            burn_rate=burn_rate if burn_rate > 0 else None,
            trend=trend,
            days_left=days_left,
            data_points=len(records),
            period_hours=period_hours,
        )

    def estimate_days_until_empty(
        self,
        threshold: float = 0.0,
        provider: str | None = None,
        provider_alias: str | None = None,
    ) -> float | None:
        """
        Forecast the number of days until the balance is depleted.

        IMPORTANT: This only makes sense for prepaid providers!
        Uses linear regression for an accurate forecast.

        Args:
            threshold: Balance threshold value (default 0)
            provider: Filter by provider type (legacy)
            provider_alias: Filter by provider alias (new)

        Returns:
            float | None: Number of days, or None if it cannot be computed
        """
        result = self.calculate_burn_rate_regression(
            provider=provider,
            provider_alias=provider_alias,
        )

        if result.days_left is None:
            return None

        # Account for the threshold
        if threshold > 0 and result.burn_rate is not None and result.burn_rate > 0:
            latest = self.get_latest_record(
                provider=provider,
                provider_alias=provider_alias,
            )
            if latest and isinstance(latest, PrepaidBalanceRecord):
                available = latest.effective_balance - threshold
                if available <= 0:
                    return 0.0
                return available / result.burn_rate

        return result.days_left

    def cleanup_old_data(self, days: int = 90) -> int:
        """
        Delete data older than the specified number of days.

        Args:
            days: Number of days to retain

        Returns:
            int: Number of records deleted
        """
        cutoff_time = datetime.now() - timedelta(days=days)
        all_records = self.get_all_records()

        initial_count = len(all_records)

        # Keep only the recent records
        recent_records = [r for r in all_records if r.timestamp >= cutoff_time]

        if len(recent_records) < initial_count:
            data = [r.model_dump() for r in recent_records]
            self._write_json(data)
            return initial_count - len(recent_records)

        return 0
