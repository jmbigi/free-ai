"""Lightweight benchmark helpers for cache/context/router decisions."""
from __future__ import annotations
import time
from typing import Any

def timed(fn, *a, **k):
    t=time.perf_counter(); r=fn(*a,**k); return r, (time.perf_counter()-t)*1000

def percentile(values, p=95):
    if not values: return 0
    s=sorted(values); i=min(len(s)-1, int(round((p/100)*(len(s)-1))))
    return s[i]
