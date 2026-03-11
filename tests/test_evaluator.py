from agentdb.db.filesystem import VirtualFS
from agentdb.simulation.evaluator import ServiceEvaluator, ServiceResult

GOOD_SERVICE = '''
def handle_load(load: float, config: dict) -> dict:
    capacity = config.get("capacity", 1.0)
    if load > capacity:
        return {
            "status": "degraded",
            "capacity": capacity,
            "metrics": {"utilization": load / capacity},
        }
    return {
        "status": "ok",
        "capacity": capacity,
        "metrics": {"utilization": load / capacity},
    }
'''

BAD_SERVICE = '''
def handle_load(load: float, config: dict) -> dict:
    return 1 / 0  # ZeroDivisionError
'''

SYNTAX_ERROR_SERVICE = '''
def handle_load(load config):  # syntax error
    pass
'''


def test_evaluate_good_service(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", GOOD_SERVICE)
    fs.write_file("/city/services/power-grid/config.json", '{"capacity": 1.0}')
    evaluator = ServiceEvaluator(fs)
    result = evaluator.evaluate("power-grid", load=0.5)
    assert result.status == "ok"
    assert result.error is None


def test_evaluate_degraded_service(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", GOOD_SERVICE)
    fs.write_file("/city/services/power-grid/config.json", '{"capacity": 0.4}')
    evaluator = ServiceEvaluator(fs)
    result = evaluator.evaluate("power-grid", load=0.5)
    assert result.status == "degraded"


def test_evaluate_crashing_service(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", BAD_SERVICE)
    fs.write_file("/city/services/power-grid/config.json", '{}')
    evaluator = ServiceEvaluator(fs)
    result = evaluator.evaluate("power-grid", load=0.5)
    assert result.status == "failed"
    assert "ZeroDivisionError" in result.error


def test_evaluate_syntax_error(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", SYNTAX_ERROR_SERVICE)
    fs.write_file("/city/services/power-grid/config.json", '{}')
    evaluator = ServiceEvaluator(fs)
    result = evaluator.evaluate("power-grid", load=0.5)
    assert result.status == "failed"
    assert result.error is not None


def test_evaluate_missing_service(db):
    fs = VirtualFS(db)
    evaluator = ServiceEvaluator(fs)
    result = evaluator.evaluate("nonexistent", load=0.5)
    assert result.status == "failed"
    assert "not found" in result.error.lower()
