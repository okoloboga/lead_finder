import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.program import Program
from bot.models.user import User

PAID_PERIODS_MONTHS = {
    "1m": 1,
    "3m": 3,
    "6m": 6,
    "12m": 12,
}

STARS_PRICES = {
    "1m": 500,
    "3m": 1300,
    "6m": 2400,
    "12m": 4200,
}


def _utc_now() -> datetime.datetime:
    return datetime.datetime.utcnow()


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


async def check_program_limit(
    session: AsyncSession, user: User
) -> tuple[bool, str | None]:
    if is_paid_user(user):
        return True, None

    program_count = (
        await session.execute(
            select(func.count(Program.id)).where(Program.user_id == user.telegram_id)
        )
    ).scalar_one()
    if program_count >= 1:
        return (
            False,
            "На бесплатном тарифе доступна только 1 программа. "
            "Оформи подписку, чтобы снять лимит.",
        )
    return True, None


def check_weekly_analysis_limit(user: User) -> tuple[bool, int]:
    if is_paid_user(user):
        return True, 0

    if not user.last_analysis_at:
        return True, 0

    delta = _utc_now() - user.last_analysis_at
    if delta >= datetime.timedelta(days=7):
        return True, 0

    days_left = 7 - delta.days
    if days_left <= 0:
        days_left = 1
    return False, days_left


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
