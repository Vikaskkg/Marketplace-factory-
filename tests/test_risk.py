"""Rubric tests. Run: .venv\\Scripts\\python.exe -m pytest tests  (or python tests/test_risk.py)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import risk  # noqa: E402

DEFAULT = {"name": "Microsoft.DefaultV2", "filters": risk.TEMPLATES["Low"]}
HIGH = {"name": "hub-high-v1", "filters": risk.TEMPLATES["High"]}


def run(facts, text="", mcp=(), chosen=None, rails=(DEFAULT,)):
    return risk.assess(facts, text, list(mcp), chosen, list(rails))


def test_internal_read_only_faq_is_low():
    r = run({"audience": "staff", "data": "internal", "actions": "read_only", "domain": "general", "human_review": "yes"})
    assert r["tier"] == "Low" and r["score"] == 1
    assert "Microsoft.DefaultV2" in r["guardrail"]["satisfying"]


def test_customer_facing_with_writes_and_personal_data_is_high():
    r = run({"audience": "customers", "data": "personal", "actions": "writes", "domain": "general", "human_review": "no"})
    assert r["tier"] in ("High", "Critical") and r["guardrail"]["suggestNew"] == f"hub-{r['tier'].lower()}-v1"


def test_one_answer_moves_the_tier():
    base = {"audience": "staff", "data": "internal", "actions": "read_only", "domain": "general", "human_review": "yes"}
    assert run(base)["tier"] == "Low"
    assert run({**base, "audience": "public"})["tier"] == "Medium"                      # 3 + 1 = 4
    assert run({**base, "audience": "public", "data": "personal"})["tier"] == "High"    # 3 + 3 = 6
    assert run({**base, "audience": "public", "data": "personal", "actions": "writes"})["tier"] in ("High", "Critical")


def test_safety_floor_regulated_data_is_at_least_high():
    r = run({"audience": "staff", "data": "regulated", "actions": "read_only", "domain": "general", "human_review": "yes"})
    assert r["tier"] == "High" and r["floorNote"]


def test_unknown_facts_are_assumed_and_flagged():
    r = run({})
    assumed = {f["key"] for f in r["factors"] if f["assumed"]}
    assert {"audience", "data", "domain", "human_review", "actions"} <= assumed


def test_tools_attached_assume_write_access():
    assert run({}, mcp=["https://x.example/mcp"])["facts"]["actions"] == "writes"
    assert run({})["facts"]["actions"] == "read_only"


def test_weak_guardrail_is_flagged_and_strict_one_is_accepted():
    facts = {"audience": "public", "data": "personal", "actions": "writes", "domain": "general", "human_review": "no"}
    assert run(facts, chosen="Microsoft.DefaultV2")["guardrail"]["selectedOk"] is False
    assert run(facts, chosen="hub-high-v1", rails=(DEFAULT, HIGH))["guardrail"]["selectedOk"] is True


def test_critical_is_blocked():
    r = run({"audience": "public", "data": "regulated", "actions": "writes", "domain": "medical", "human_review": "no"},
            text="web search the internet")
    assert r["tier"] == "Critical" and r["blocked"]


def test_keyword_facts_from_description():
    f = risk.facts_from_text("A bot for customers that reads patient records and can send email")
    assert f["audience"] == "customers" and f["data"] == "regulated" and f["actions"] == "writes"


def test_satisfies_strictness():
    loose = [dict(f, severityThreshold="High") if "severityThreshold" in f else f for f in risk.TEMPLATES["Low"]]
    assert not risk.satisfies(loose, risk.TEMPLATES["Medium"])
    assert risk.satisfies(risk.TEMPLATES["High"], risk.TEMPLATES["Medium"])
    assert not risk.satisfies(risk.TEMPLATES["Low"], risk.TEMPLATES["High"])   # lacks jailbreak etc.


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
