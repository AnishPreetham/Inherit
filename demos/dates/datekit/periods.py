import datetime

from dateutil.relativedelta import relativedelta

from datekit import settings


def add_months(year, month, day, months):
    start = datetime.date(year, month, day)
    return (start + relativedelta(months=months)).isoformat()


def week_start(year, month, day):
    date = datetime.date(year, month, day)
    offset = date.weekday() if settings.WEEK_START == "monday" else (date.weekday() + 1) % 7
    return (date - datetime.timedelta(days=offset)).isoformat()


def months_between(start_iso, end_iso):
    start = datetime.date.fromisoformat(start_iso)
    end = datetime.date.fromisoformat(end_iso)
    delta = relativedelta(end, start)
    return delta.years * 12 + delta.months
