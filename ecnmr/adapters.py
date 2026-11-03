"""Instrument boundaries. No vendor connection is attempted by this prototype.

The simulator in the controller supplies the working acquisition workflow. Real
control remains deliberately unavailable until the site's vendor integration is
implemented against its installed, supported API and validated on the instrument.
"""
from dataclasses import dataclass
import math
from pathlib import Path


class HardwareUnavailable(RuntimeError):
    """The requested action requires a validated vendor driver."""


@dataclass(frozen=True)
class HardwareSettings:
    endpoint: str = ""
    channel: int = 0
    protocol: str = ""
    min_voltage_V: float | None = None
    max_voltage_V: float | None = None
    max_abs_current_mA: float | None = None
    operator_authorized: bool = False

    def validate(self) -> None:
        if not self.operator_authorized:
            raise HardwareUnavailable("An operator must explicitly authorize hardware operation.")
        if not self.endpoint or self.channel < 0:
            raise ValueError("An explicit instrument endpoint and nonnegative channel are required.")
        if not self.protocol or not Path(self.protocol).is_file():
            raise ValueError("Select an existing operator-approved EC-Lab protocol.")
        values = (self.min_voltage_V, self.max_voltage_V, self.max_abs_current_mA)
        if any(v is None or not math.isfinite(v) for v in values):
            raise ValueError("Finite voltage and current limits are required.")
        if self.min_voltage_V >= self.max_voltage_V or self.max_abs_current_mA <= 0:
            raise ValueError("The voltage range and current limit must be valid.")


class BioLogicAdapter:
    """Fail-closed integration boundary; not an operational EC-Lab driver."""

    implemented = False
    hardware_validated = False

    def __init__(self, settings: HardwareSettings | None = None):
        self.settings = settings or HardwareSettings()

    def prepare(self) -> None:
        self.settings.validate()
        raise HardwareUnavailable(
            "Real SP-150e control is unavailable: install a vendor-supported driver, "
            "verify instrument/board/firmware compatibility and validate acquisition "
            "and numerical data retrieval. Offline and simulation remain available."
        )

    def start(self) -> None:
        raise HardwareUnavailable("Real instrument start is disabled in this prototype.")

    def stop(self) -> None:
        raise HardwareUnavailable(
            "No hardware connection exists; stop the instrument using EC-Lab and "
            "the laboratory's hardware safety procedure."
        )

    def read_measurements(self) -> list[dict]:
        raise HardwareUnavailable("No validated live numerical EC data source is configured.")


class TopSpinAdapter:
    """Acquisition API boundary, distinct from the usable offline data reader."""

    implemented = False
    hardware_validated = False

    def prepare(self) -> None:
        raise HardwareUnavailable("TopSpin acquisition control requires site API/version validation.")

    def start(self) -> None:
        raise HardwareUnavailable("Real NMR acquisition is disabled in this prototype.")

    def stop(self) -> None:
        raise HardwareUnavailable("No spectrometer connection exists; use TopSpin to stop acquisition.")
