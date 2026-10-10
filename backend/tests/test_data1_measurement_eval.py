import importlib.util
from pathlib import Path


def test_synthetic_measurement_evaluation_cases_and_independent_expected_results():
    path = Path(__file__).resolve().parents[2] / "eval/measurement/run_phase2b.py"
    spec = importlib.util.spec_from_file_location("measurement_eval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.evaluate()
    assert result["cases"] == 20 and result["passed"] == 20
    assert "Synthetic" in result["authorship"]
