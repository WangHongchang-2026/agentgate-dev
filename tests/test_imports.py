from pathlib import Path


def test_removed_monolithic_modules_are_not_referenced():
    root = Path(__file__).parents[1] / "src" / "agentgate"
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*.py")
    )
    assert "agentgate.contracts" not in sources
    assert "from agentgate.case " not in sources
    assert "from agentgate.case." not in sources
    assert "import agentgate.case" not in sources
    assert "agentgate.evaluator.core" not in sources
