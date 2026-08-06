import datetime

from bot.models.user import User

PAID_PERIODS_MONTHS = {
    "1m": 1,
    "3m": 3,
    "6m": 6,
    "12m": 12,
}

STARS_PRICES = {
    "1m": 500,
    "3m": 1200,
    "6m": 2000,
    "12m": 3500,
}

# Free tier is a full-featured trial that starts at registration.
TRIAL_DAYS = 7

TRIAL_OVER_MESSAGE = (
    "Пробная неделя закончилась. Оформи подписку, чтобы продолжить."
)
TRIAL_OVER_MESSAGE_EN = (
    "Your free trial week is over. Subscribe to continue."
)


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def normalize_subscription(user: User) -> None:
    if (
        user.subscription_type == "paid"
        and user.subscription_expires_at
        and user.subscription_expires_at <= _utc_now()
    ):
        user.subscription_type = "free"
        user.subscription_expires_at = None


def is_paid_user(user: User) -> bool:
    normalize_subscription(user)
    return user.subscription_type == "paid"


def trial_expires_at(user: User) -> datetime.datetime:
    """Returns the moment the free trial week ends."""
    # created_at is filled on insert, so a not-yet-flushed user starts now.
    created_at = user.created_at or _utc_now()
    return created_at + datetime.timedelta(days=TRIAL_DAYS)


def is_trial_active(user: User) -> bool:
    """Whether the user is still inside the free trial week."""
    return _utc_now() < trial_expires_at(user)


def trial_days_left(user: User) -> int:
    """Days left in the trial rounded up, or 0 once it is over."""
    remaining = trial_expires_at(user) - _utc_now()
    if remaining <= datetime.timedelta(0):
        return 0
    return remaining.days + 1


def has_full_access(user: User) -> bool:
    """Trial week and paid subscription both unlock every feature."""
    return is_paid_user(user) or is_trial_active(user)


def mark_analysis_started(user: User) -> None:
    user.last_analysis_at = _utc_now()


def add_months(base: datetime.datetime, months: int) -> datetime.datetime:
    year = base.year + (base.month - 1 + months) // 12
    month = (base.month - 1 + months) % 12 + 1
    day = min(base.day, 28)
    return base.replace(year=year, month=month, day=day)


def activate_paid_subscription(user: User, period_key: str) -> datetime.datetime:
    months = PAID_PERIODS_MONTHS[period_key]
    normalize_subscription(user)
    start = _utc_now()
    if user.subscription_expires_at and user.subscription_expires_at > start:
        start = user.subscription_expires_at
    new_expiry = add_months(start, months)
    user.subscription_type = "paid"
    user.subscription_expires_at = new_expiry
    return new_expiry
