from datetime import datetime
from typing import Protocol

from .contracts import MeasurementInput, PairContext


class InputUnavailableError(Exception):
    """No authoritative planner/evidence integration is currently available."""


class MeasurementSource(Protocol):
    def load(self, pair: PairContext, known_at: datetime) -> MeasurementInput: ...


class UnavailableMeasurementSource:
    def load(self, pair: PairContext, known_at: datetime) -> MeasurementInput:
        raise InputUnavailableError("Data 2/Vision measurement adapter is not configured")


class FixtureMeasurementSource:
    """Explicitly injected local/test data; never selected implicitly in production."""
    def __init__(self, inputs: dict[int, MeasurementInput]) -> None:
        self.inputs = inputs

    def load(self, pair: PairContext, known_at: datetime) -> MeasurementInput:
        if pair.pair_id not in self.inputs:
            raise InputUnavailableError("Fixture has no measurement facts for this pair")
        result = self.inputs[pair.pair_id].model_copy(deep=True)
        if result.pair != pair:
            raise ValueError("Input pair generation/membership does not match authoritative pair")
        return result


def get_measurement_source() -> MeasurementSource:
    return UnavailableMeasurementSource()
