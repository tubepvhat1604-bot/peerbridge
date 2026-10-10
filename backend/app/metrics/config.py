from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType

from .contracts import RiskFeature

# CONTEXT §9.1 explicitly calls for hand-set weights; these are disclosed pilot policies, not fitted probabilities.
RISK_WEIGHTS: Mapping[RiskFeature, float] = MappingProxyType({
    "absence": .25, "frequency_decline": .15, "pacing_deficit": .25,
    "partner_inactivity": .15, "reminder_nonresponse": .10, "theta_stagnation": .10,
})


@dataclass(frozen=True)
class MeasurementConfig:
    low_pacing_threshold: float = .7
    gap_threshold: float = .3
    absence_attention_days: int = 2
    absence_saturation_days: int = 7
    frequency_window_days: int = 7

    def __post_init__(self) -> None:
        if not isfinite(self.low_pacing_threshold) or not 0 <= self.low_pacing_threshold <= 1:
            raise ValueError("Low pacing threshold must be finite in [0,1]")
        if not isfinite(self.gap_threshold) or self.gap_threshold < 0:
            raise ValueError("Gap threshold must be finite and nonnegative")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in
               (self.absence_attention_days, self.absence_saturation_days, self.frequency_window_days)):
            raise ValueError("Risk/absence windows must be positive integer days")


DEFAULT_CONFIG = MeasurementConfig()
