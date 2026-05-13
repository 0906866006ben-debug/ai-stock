"""Short-term horizon wrapper."""

from __future__ import annotations

from ..classifiers.price_state import PriceStateClassifier
from ..contracts.enums import Horizon


def analyze_short_term(features, context, registry=None):
    classifier = PriceStateClassifier(rule_registry=registry, horizon=Horizon.SHORT_TERM)
    return classifier.classify(features, context)
