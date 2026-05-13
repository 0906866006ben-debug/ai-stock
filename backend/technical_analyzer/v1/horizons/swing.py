"""Swing horizon wrapper."""

from __future__ import annotations

from ..classifiers.price_state import PriceStateClassifier
from ..contracts.enums import Horizon


def analyze_swing(features, context, registry=None):
    classifier = PriceStateClassifier(rule_registry=registry, horizon=Horizon.SWING)
    return classifier.classify(features, context)
