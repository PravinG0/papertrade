"""Strict structured verdict boundary. Model output is not an order."""
import math


def validated_verdict(data):
    if not isinstance(data, dict):
        return "NO_TRADE", 1, 0., 0., 0., 0.
    verdict = str(data.get("verdict", "")).strip().upper()
    confidence = data.get("confidence")
    if type(confidence) is not int or not 1 <= confidence <= 10:
        return "NO_TRADE", 1, 0., 0., 0., 0.
    if verdict not in ("BUY CE", "BUY PE"):
        return "NO_TRADE", confidence, 0., 0., 0., 0.
    try:
        raw = [data[k] for k in ("recommended_strike", "entry_price", "stop_loss", "target")]
        if any(isinstance(x, bool) for x in raw):
            raise ValueError("Boolean is not a price")
        strike, entry, sl, target = map(float, raw)
        if not all(math.isfinite(x) for x in (strike, entry, sl, target)) or not (strike > 0 and 0 < sl < entry < target):
            raise ValueError("Invalid trade geometry")
    except (ValueError, TypeError, KeyError, OverflowError):
        return "NO_TRADE", confidence, 0., 0., 0., 0.
    return verdict, confidence, strike, entry, sl, target
