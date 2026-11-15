"""The sampling frame. Changing anything here changes which repos are in the dataset."""
from __future__ import annotations

import datetime as dt
import random

SNAPSHOT = dt.date(2026, 11, 15)
PUSHED_SINCE = dt.date(2025, 11, 15)
FIRST_DAY = dt.date(2008, 1, 1)
SEED = 20261115
SAMPLE_FRACTION = 0.05
CENSUS_MIN_STARS = 1000
SAMPLE_STARS = (100, 999)
FILTERS = f"is:public archived:false fork:false pushed:>={PUSHED_SINCE.isoformat()}"


def candidate_days() -> list[dt.date]:
    return [FIRST_DAY + dt.timedelta(d) for d in range((SNAPSHOT - FIRST_DAY).days)]


def sampled_days() -> list[dt.date]:
    days = candidate_days()
    return sorted(random.Random(SEED).sample(days, round(SAMPLE_FRACTION * len(days))))


def sample_weight() -> float:
    """Each stratum B repo stands for this many repos in the 100 to 999 star population."""
    return len(candidate_days()) / len(sampled_days())
