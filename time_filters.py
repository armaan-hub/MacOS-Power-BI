from datetime import date, timedelta
from calendar import monthrange
from typing import Iterable

def _year_to_date_start(value: date, year_end: tuple[int, int] = (12, 31)) -> date:
    end_month, end_day = year_end
    if (value.month, value.day) <= (end_month, end_day):
        start_year = value.year - 1
    else:
        start_year = value.year
    start_month = (end_month % 12) + 1
    # Day is 1 for next month, or adjust if end_day is mid-month but standard year ends are month ends
    # This logic matches PREVIOUSYEAR. I'll just copy it or we can import from measures if we need it.
    pass

