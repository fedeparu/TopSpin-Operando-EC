import pytest
from ecnmr.adapters import BioLogicAdapter, HardwareSettings, HardwareUnavailable, TopSpinAdapter


def test_hardware_default_cannot_prepare_or_start():
    adapter = BioLogicAdapter()
    with pytest.raises(HardwareUnavailable, match="authorize"):
        adapter.prepare()
    with pytest.raises(HardwareUnavailable, match="disabled"):
        adapter.start()
    with pytest.raises(HardwareUnavailable, match="EC-Lab"):
        adapter.stop()
    with pytest.raises(HardwareUnavailable, match="numerical"):
        adapter.read_measurements()


def test_even_authorized_valid_settings_cannot_activate_hardware(tmp_path):
    protocol = tmp_path / "approved.mps"
    protocol.write_text("test")
    adapter = BioLogicAdapter(HardwareSettings(
        endpoint="192.0.2.1", channel=1, protocol=str(protocol),
        min_voltage_V=2.5, max_voltage_V=4.2, max_abs_current_mA=0.1,
        operator_authorized=True))
    with pytest.raises(HardwareUnavailable, match="unavailable"):
        adapter.prepare()
    with pytest.raises(HardwareUnavailable):
        adapter.start()


def test_invalid_limits_rejected_before_any_vendor_calls(tmp_path):
    protocol = tmp_path / "protocol.mps"
    protocol.write_text("test")
    settings = HardwareSettings(endpoint="instrument", protocol=str(protocol),
        min_voltage_V=4, max_voltage_V=3, max_abs_current_mA=1, operator_authorized=True)
    with pytest.raises(ValueError, match="range"):
        settings.validate()


def test_no_spectrometer_calls():
    for action in ("prepare", "start", "stop"):
        with pytest.raises(HardwareUnavailable):
            getattr(TopSpinAdapter(), action)()


def test_topspin_current_dataset_path_resolution():
    import runpy
    from pathlib import Path
    launcher = Path(__file__).parents[1] / "topspin" / "ecnmr_launcher.py"
    namespace = runpy.run_path(str(launcher), run_name="launcher_test")
    resolve = namespace["dataset_directory"]
    assert Path(resolve(["sample with spaces", "4", "1", "/data"])) == Path("/data") / "sample with spaces" / "4"
    with pytest.raises(ValueError):
        resolve(None)
