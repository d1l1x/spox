from datetime import time

def total_seconds(t: time):
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1_000_000