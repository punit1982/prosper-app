"""
PROSPER v5.13.1 — tests for the deterministic resolver and everything that reads it
===================================================================================
The resolver decides the call, the ratio and the buy-below line the Options Desk trades against.
A wrong number here is a wrong order, so every rule the framework states with a number is pinned
here against the framework's own examples. Offline: no network, no model.

    python -m pytest tests/test_prosper_engine.py -q
"""

import json
import math
import os
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts", "_stub"))

from core import prosper_engine as pe          # noqa: E402
from core.framework_version import FRAMEWORK_VERSION, is_current   # noqa: E402


def _card(**over):
    d = {
        "ticker": "TEST", "company": "Test Co", "route": "CORE", "ai_class": "AI-N",
        "scores": {"d1": {"score": 8, "why": "a"}, "d2": {"score": 8, "why": "b"},
                   "d3": {"score": 6, "why": "c"}, "d4": {"score": 7, "why": "d"},
                   "d5": {"score": 6, "why": "e"}},
        "cases": {"bear": {"price": 180.0, "weight": 0.25, "why": "margins compress"},
                  "base": {"price": 260.0, "weight": 0.50, "why": "guidance met"},
                  "bull": {"price": 340.0, "weight": 0.25, "why": "share gains"}},
        "catalysts": [{"event": "Q3 results", "date": "30-Oct-2026", "impact": "proves margins"}],
        "prove_wrong": [{"fact": "gross margin < 40%", "effect": "bear case becomes base"}],
        "action_prices": {"buy_zone_low": 190.0, "buy_zone_high": 205.0, "add": "on Q3 beat",
                          "take_profit": [300.0, 320.0, 340.0], "walk_away": "below 170"},
        "integrity": {"type": "NONE"}, "regime": {"state": "Amber"},
        "conviction_target_pct": 3, "rating": "BUY", "do_this": "Buy now up to 205",
        "confidence": "Medium", "why": {"for": "x", "against": "y", "tips": "z"},
        "unverified": "nothing", "horizon_label": "Sep-2029",
    }
    d.update(over)
    return d


def _text(payload) -> str:
    return "═══════\nTEST CARD\n\n```json\n" + json.dumps(payload) + "\n```\n"


# ─────────────────────────────────────────────────────────────────────────────
# §B3 — score and bands
# ─────────────────────────────────────────────────────────────────────────────

def test_q_is_the_weighted_sum_times_ten():
    r = pe.resolve_card(_card(), 231.5)
    # 8×.25 + 8×.25 + 6×.20 + 7×.15 + 6×.15 = 7.15 → 71.5
    assert r["q"] == 71.5 and r["band_call"] == "BUY"


def test_band_edges_are_compared_unrounded():
    assert pe.band_for(64.5) == "HOLD"          # the framework's own example (AIY, 17-Sep)
    assert pe.band_for(64.99) == "HOLD"
    assert pe.band_for(65.0) == "BUY"
    assert pe.band_for(34.9) == "SELL"


def test_income_lens_uses_its_own_weights():
    d = _card(route="INCOME", scores={"d1": 5, "d2": 8, "d3": 7, "d4": 7, "d5": 6, "d6": 9, "d7": 6})
    r = pe.resolve_card(d, 231.5)
    expected = (5*.10 + 8*.30 + 7*.15 + 7*.15 + 6*.15 + 9*.10 + 6*.05) * 10
    assert abs(r["q"] - round(expected, 1)) < 1e-9 and r["weights_used"] == "INCOME"


# ─────────────────────────────────────────────────────────────────────────────
# P3 — the ratio, printed with numbers; D5 follows it
# ─────────────────────────────────────────────────────────────────────────────

def test_ratio_is_bull_minus_spot_over_spot_minus_bear():
    r = pe.resolve_card(_card(), 231.5)
    assert abs(r["ratio"] - (340 - 231.5) / (231.5 - 180)) < 1e-12
    assert pe.ratio_formula(r) == "(340.00 − 231.50) ÷ (231.50 − 180.00) = 108.50 ÷ 51.50 = 2.11×"


def test_base_is_never_the_reward_leg_and_spot_never_the_denominator():
    """Fujikura and VLN: the ratio was read two ways. Only one reading is allowed."""
    r = pe.resolve_card(_card(), 231.5)
    wrong_a = (260 - 231.5) / (231.5 - 180)      # base as the reward
    wrong_b = (340 - 231.5) / 231.5              # spot as the denominator
    assert r["ratio"] not in (wrong_a, wrong_b)


def test_d5_is_clamped_into_the_band_its_ratio_implies():
    r = pe.resolve_card(_card(scores={"d1": 8, "d2": 8, "d3": 6, "d4": 7, "d5": 9}), 231.5)
    assert r["scores"]["d5"] == 6                 # 2.11× scores 5–6; the model said 9
    assert any("asymmetry score" in a for a in r["adjustments"])


def test_no_downside_to_the_bear_is_infinite_not_an_error():
    r = pe.resolve_card(_card(), 175.0)           # spot below the bear
    assert math.isinf(r["ratio"]) and r["ratio_text"] == "no downside to the bear"


# ─────────────────────────────────────────────────────────────────────────────
# Hard caps — down only
# ─────────────────────────────────────────────────────────────────────────────

def test_buy_under_two_to_one_becomes_accumulate_with_the_release_price():
    r = pe.resolve_card(_card(), 240.0)           # (340-240)/(240-180) = 1.67×
    assert r["band_call"] == "BUY" and r["call"] == "ACCUMULATE ON DIPS"
    assert abs(r["reentry"] - (340 + 2 * 180) / 3) < 1e-9
    g = r["gates"][0]
    assert g["rule"] == "D5-BUY-GATE" and "233.33" in g["release"]


def test_d5_under_three_caps_at_hold():
    r = pe.resolve_card(_card(), 270.0)           # (340-270)/(270-180) = 0.78× → D5 ≤2
    assert r["call"] == "HOLD" and any(g["rule"] == "D5 <3" for g in r["gates"])


def test_strong_buy_needs_three_to_one():
    d = _card(scores={"d1": 10, "d2": 10, "d3": 9, "d4": 9, "d5": 6})
    r = pe.resolve_card(d, 231.5)                 # Q 88 but 2.11×
    assert r["band_call"] == "STRONG BUY" and r["call"] == "BUY"


def test_accounts_integrity_forces_sell_conduct_does_not():
    assert pe.resolve_card(_card(integrity={"type": "ACCOUNTS"}), 231.5)["call"] == "SELL"
    d = _card(integrity={"type": "CONDUCT"},
              cases={"break": {"price": 120, "weight": 0.05}, "bear": {"price": 180, "weight": 0.25},
                     "base": {"price": 260, "weight": 0.45}, "bull": {"price": 340, "weight": 0.25}})
    r = pe.resolve_card(d, 200.0)
    assert r["call"] == "HOLD" and r["stressed_bear"] == 120
    assert abs(r["weights"]["break"] - 0.10) < 1e-9          # P10: raised to ≥10%
    assert abs(sum(r["weights"].values()) - 1) < 1e-9


def test_conduct_with_break_ratio_under_one_is_sell():
    d = _card(integrity={"type": "CONDUCT"},
              cases={"break": {"price": 100, "weight": 0.10}, "bear": {"price": 180, "weight": 0.2},
                     "base": {"price": 230, "weight": 0.45}, "bull": {"price": 250, "weight": 0.25}})
    assert pe.resolve_card(d, 200.0)["call"] == "SELL"


def test_p11_conservative_restatement_is_a_flag_not_a_cap():
    d = _card(integrity={"type": "REPORTING_CONTROL", "restatement_direction": "CONSERVATIVE",
                         "direction_source": "FY2025 annual report, note 2", "material_weakness": True})
    r = pe.resolve_card(d, 231.5)
    assert r["scores"]["d4"] == 5 and r["call"] != "SELL"      # 7 − 2 (material weakness)


def test_p11_flattering_or_unsourced_restatement_is_accounts():
    for integ in ({"type": "REPORTING_CONTROL", "restatement_direction": "FLATTERING", "direction_source": "10-K/A"},
                  {"type": "REPORTING_CONTROL", "restatement_direction": "CONSERVATIVE"}):
        assert pe.resolve_card(_card(integrity=integ), 231.5)["call"] == "SELL"


def test_p4_chronic_dilution_caps_capital_score():
    r = pe.resolve_card(_card(dilution={"shares_3y_ago": 100e6, "shares_now": 135e6, "years": 3}), 231.5)
    assert r["scores"]["d4"] == 4 and r["dilution_cagr"] > 0.10


def test_ai_class_ceiling_and_hold_cap():
    r = pe.resolve_card(_card(ai_class="AI-V"), 231.5)
    assert r["scores"]["d2"] == 5
    r = pe.resolve_card(_card(ai_class="AI-X", scores={"d1": 8, "d2": 3, "d3": 6, "d4": 7, "d5": 6}), 150.0)
    assert r["call"] in ("HOLD", "TRIM", "SELL")


def test_blow_off_caps_at_hold():
    r = pe.resolve_card(_card(rr_gate={"status": "BLOW-OFF"}), 231.5)
    assert r["call"] == "HOLD"


def test_rr_confirmed_bonus_is_bounded():
    r = pe.resolve_card(_card(rr_gate={"status": "CONFIRMED", "bonus": 9}), 231.5)
    assert r["rr_bonus"] == 4.0 and r["q"] == 75.5


def test_quality_on_sale_needs_all_five():
    d = _card(route="QOS", week52_high=500.0, qos={"down_on_sentiment_not_fundamentals": True},
              cases={"bear": {"price": 180}, "base": {"price": 400}, "bull": {"price": 700}})
    r = pe.resolve_card(d, 200.0)                  # 60% off; (700-200)/(200-180) = 25×
    assert r["qos"] and r["call"] == "STRONG BUY"
    d["catalysts"] = [{"event": "execution", "date": "ongoing"}]
    r = pe.resolve_card(d, 200.0)
    assert not r["qos"]                            # P5: no dated catalyst, no QoS


def test_microcap_kill_switch_is_avoid():
    d = _card(route="MICROCAP", microcap={"kill_switch": "MOU-only traction",
                                          "pillars": {"p1": 7, "p2": 3, "p3": 2, "p4": 3, "p5": 2, "s6": 9}})
    assert pe.resolve_card(d, 231.5)["call"] == "AVOID"


def test_caps_only_ever_move_down():
    r = pe.resolve_card(_card(scores={"d1": 2, "d2": 2, "d3": 2, "d4": 2, "d5": 2}), 175.0)
    assert r["call"] == "SELL"                     # Q 20 — no cap may lift it


# ─────────────────────────────────────────────────────────────────────────────
# assemble_result — the one path every producer goes through
# ─────────────────────────────────────────────────────────────────────────────

def test_the_models_call_is_overridden_and_the_disagreement_recorded():
    text = _text(_card(rating="STRONG BUY"))
    data = pe._extract_json_block(text)
    res, err = pe.assemble_result("TEST", data, text, tier="standard",
                                  price_quote={"price": 240.0, "source": "t"})
    assert res, err
    assert res["entry_verdict"] == "ACCUMULATE ON DIPS" and res["model_call"] == "STRONG BUY"
    assert any("recomputed" in u for u in res["uncertainties"])
    assert res["do_this"].startswith("Wait for 233.33")


def test_ladder_fields_the_options_desk_reads():
    data = pe._extract_json_block(_text(_card()))
    res, _ = pe.assemble_result("TEST", data, "", price_quote={"price": 231.5})
    assert res["buy_below"] == 205.0                     # min(buy-zone top, 2× line 233.33)
    assert res["fair_high"] == 300.0                     # first take-profit
    assert abs(res["strong_buy_below"] - (340 + 3 * 180) / 4) < 0.01
    assert res["framework"] == FRAMEWORK_VERSION and res["score"] == res["q_score"] == 71.5
    assert res["no_adds"] == 0.0
    assert res["valid_until"] > res["analysis_date"]


def test_api_and_chat_window_paths_agree_exactly():
    data = pe._extract_json_block(_text(_card()))
    a, _ = pe.assemble_result("TEST", data, "", tier="cowork", price_quote={"price": 231.5})
    b, _ = pe.assemble_result("TEST", data, "", tier="standard", price_quote={"price": 231.5})
    for k in ("entry_verdict", "q_score", "reward_risk", "reentry_price", "buy_below", "fair_high",
              "prob_weighted_return"):
        assert a[k] == b[k], k


def test_rejections():
    data = pe._extract_json_block(_text(_card()))
    assert pe.assemble_result("TEST", data, "", price_quote=None)[0] is None          # no price
    bad = _card(cases={"bear": {"price": 1}})
    assert pe.assemble_result("TEST", bad, "", price_quote={"price": 10})[0] is None  # no cases
    res, err = pe.assemble_result("TEST", _card(no_rating_reason="no filings found"), "",
                                  price_quote={"price": 10})
    assert res is None and "Not rated" in err


def test_probability_weighted_return():
    data = _card(dividends_per_share_3y=0.0)
    res, _ = pe.assemble_result("TEST", data, "", price_quote={"price": 200.0})
    exp = 0.25 * (180 / 200 - 1) + 0.5 * (260 / 200 - 1) + 0.25 * (340 / 200 - 1)
    assert abs(res["prob_weighted_return"] - round(exp, 4)) < 1e-9


def test_a_grow_row_is_not_a_prior_run():
    """P9: a different framework's levels are not a prior run."""
    grow_row = {"framework": "GROW v5.1", "analysis_date": "2026-09-05", "buy_below": 230.07}
    assert pe._prior_slim(grow_row) is None
    res, _ = pe.assemble_result("TEST", _card(), "", price_quote={"price": 231.5}, prior=grow_row)
    assert any("context only" in u for u in res["uncertainties"])


def test_p9_flags_case_values_that_moved_without_a_fact():
    first, _ = pe.assemble_result("TEST", _card(), "", price_quote={"price": 231.5})
    prior = {"framework": FRAMEWORK_VERSION, "analysis_date": "2026-09-20",
             "full_response": first["full_response"]}
    moved = _card(cases={"bear": {"price": 150.0}, "base": {"price": 240.0}, "bull": {"price": 300.0}})
    res, _ = pe.assemble_result("TEST", moved, "", price_quote={"price": 200.0}, prior=prior)
    assert any(u.startswith("P9: case values moved") for u in res["uncertainties"])
    assert res["entry_line"]["old"] == round(first["reentry_price"], 2)


def test_card_text_carries_all_nine_sections_and_the_formula():
    res, _ = pe.assemble_result("TEST", _card(), "", price_quote={"price": 231.5})
    card = res["card_md"]
    for n, title in enumerate(["WHAT THEY DO", "RATING & RECOMMENDATION", "WHY", "BEAR · BASE · BULL",
                               "ASYMMETRY", "CATALYSTS", "ACTION PRICES", "WHAT WOULD PROVE US WRONG",
                               "WHAT WE COULDN'T VERIFY"], start=1):
        assert f"{n} {title}" in card, title
    assert "(340.00 − 231.50) ÷ (231.50 − 180.00)" in card
    fname, md = pe.cards_file([res], label="TEST")
    assert fname.startswith(f"{FRAMEWORK_VERSION} CARDS TEST ") and fname.endswith(".md")
    assert "| TEST | 71.5 |" in md


def test_prompt_carries_framework_and_contract():
    blocks = pe._system_blocks("standard")
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0]["text"].startswith("# PROSPER v5.13.1")
    assert "no_rating_reason" in blocks[1]["text"] and "portfolio" in blocks[1]["text"].lower()
    assert "about 12 searches" in blocks[1]["text"]
    assert "ALREADY ESTABLISHED" in pe._system_blocks("delta", regime_hint={"state": "Amber"})[1]["text"]


def test_version_filter():
    assert is_current(FRAMEWORK_VERSION)
    assert not is_current("GROW v5.1") and not is_current(None) and not is_current("")


# ─────────────────────────────────────────────────────────────────────────────
# Database round trip — in a throwaway HOME so no real data is touched
# ─────────────────────────────────────────────────────────────────────────────

_DB_SCRIPT = r"""
import json, sys
sys.path.insert(0, ROOT); sys.path.insert(0, ROOT + "/scripts/_stub")
from core import database as db
from core import prosper_engine as pe
db.init_db()
data = json.loads(PAYLOAD)
res, err = pe.assemble_result("TEST", data, "memo", price_quote={"price": 231.5})
assert res, err
db.save_prosper_analysis("TEST", res)
db.save_prosper_analysis("OLDG", {"framework": "GROW v5.1", "analysis_date": "2026-09-05",
                                  "rating": "HOLD", "score": 78, "durability": 78,
                                  "entry_verdict": "HOLD", "buy_below": 230.07})
try:
    import streamlit as st; st.session_state.clear()
except Exception:
    pass
row = db.get_prosper_analysis("TEST")
cur = db.get_current_analyses()
log = db.get_verdict_log("TEST")
print(json.dumps({
    "framework": row["framework"], "q": row["q_score"], "call": row["entry_verdict"],
    "rr": row["reward_risk"], "bb": row["buy_below"], "card": bool(row["card_md"]),
    "resolved": "resolved" in (row["full_response"] or {}),
    "current": sorted(cur["ticker"].tolist()),
    "log_q": float(log.iloc[0]["q_score"]), "log_rr": float(log.iloc[0]["reward_risk"]),
}))
"""


def test_database_round_trip_and_current_filter():
    with tempfile.TemporaryDirectory() as home:
        env = {**os.environ, "HOME": home}
        env.pop("TURSO_DATABASE_URL", None)
        code = _DB_SCRIPT.replace("ROOT", repr(_ROOT), 2).replace("PAYLOAD", repr(json.dumps(_card())))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env=env, cwd=home, timeout=120)
        assert out.returncode == 0, out.stderr[-2000:]
        got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["framework"] == FRAMEWORK_VERSION and got["q"] == 71.5 and got["call"] == "BUY"
    assert got["bb"] == 205.0 and got["card"] and got["resolved"]
    assert got["current"] == ["TEST"]                    # the GROW row is filtered out
    assert got["log_q"] == 71.5 and abs(got["log_rr"] - 2.107) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# Rendering — the card page runs end to end in Streamlit's test harness
# ─────────────────────────────────────────────────────────────────────────────

_RENDER_SCRIPT = """
import json, sys
sys.path.insert(0, {root!r}); sys.path.insert(0, {root!r} + "/scripts/_stub")
from core import prosper_engine as pe
from core.prosper_render import render_prosper_analysis
data = json.loads({payload!r})
res, err = pe.assemble_result("TEST", data, "# model card", price_quote={{"price": {price}}})
row = dict(res); row["full_response"] = json.loads(json.dumps(res["full_response"], default=str))
render_prosper_analysis(row, "TEST", "USD")
render_prosper_analysis({{"framework": "GROW v5.1", "analysis_date": "2026-09-05",
                          "thesis": "Durability 78", "ticker": "OLDG"}}, "OLDG", "USD")
"""


def test_card_renders_in_streamlit():
    from streamlit.testing.v1 import AppTest
    for price, payload in ((231.5, _card()), (240.0, _card()),
                           (200.0, _card(integrity={"type": "CONDUCT", "detail": "DOJ probe"},
                                         cases={"break": {"price": 120, "weight": .1},
                                                "bear": {"price": 180, "weight": .2},
                                                "base": {"price": 260, "weight": .45},
                                                "bull": {"price": 340, "weight": .25}}))):
        at = AppTest.from_string(_RENDER_SCRIPT.format(root=_ROOT, payload=json.dumps(payload), price=price))
        at.run(timeout=60)
        assert not at.exception, [e.value for e in at.exception]
        md = " ".join(m.value for m in at.markdown)
        assert "3 · Why" in md and "5 · Asymmetry" in md
        assert any("superseded" in w.value or "replaced" in w.value for w in at.warning)


# ─────────────────────────────────────────────────────────────────────────────
# run_prosper() end to end against a fake API client — the request plumbing
# ─────────────────────────────────────────────────────────────────────────────

class _FakeStream:
    def __init__(self, resp): self.resp = resp
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get_final_message(self): return self.resp


def _fake_client(reply_text, calls):
    from types import SimpleNamespace as NS

    class _Messages:
        def stream(self, **kw):
            calls.append(kw)
            usage = NS(input_tokens=1000, output_tokens=2000, cache_read_input_tokens=9000,
                       cache_creation_input_tokens=0, server_tool_use=NS(web_search_requests=4))
            return _FakeStream(NS(content=[NS(type="text", text=reply_text)], usage=usage,
                                  stop_reason="end_turn"))

    class _Client:
        def __init__(self, *a, **k): self.messages = _Messages()
    return _Client


def test_run_prosper_end_to_end(monkeypatch):
    import anthropic
    calls = []
    monkeypatch.setattr(anthropic, "Anthropic", _fake_client(_text(_card(rating="BUY")), calls))
    monkeypatch.setattr(pe, "get_api_key", lambda k: "sk-test")
    monkeypatch.setattr(pe, "_financials_snapshot", lambda t: "")
    import core.edgar_client as ec
    monkeypatch.setattr(ec, "filing_snapshot", lambda t: None)
    grow_row = {"framework": "GROW v5.1", "analysis_date": "2026-09-05"}

    # delta without a PROSPER prior falls back to a first (standard) run
    res, err = pe.run_prosper("TEST", tier="delta", info={"longName": "Test"},
                              price_quote={"price": 231.5, "source": "t"}, prior=grow_row)
    assert res, err
    assert res["model_used"] == "standard" and res["entry_verdict"] == "BUY"
    kw = calls[-1]
    assert kw["messages"][0]["content"].startswith("Prosper TEST")
    assert "different framework" in kw["messages"][0]["content"]          # P9 note, no prior JSON
    assert "PRIOR RUN" not in kw["messages"][0]["content"]
    assert {t["name"] for t in kw["tools"]} == {"web_search", "web_fetch"}
    assert kw["tools"][0]["max_uses"] == 12
    assert res["web_searches"] == 4 and res["cost_estimate"] > 0

    # a real PROSPER prior turns it into a delta: ≤6 searches, prior card attached
    prior = {"framework": FRAMEWORK_VERSION, "analysis_date": res["analysis_date"],
             "full_response": res["full_response"], "price_at_run": 231.5}
    res2, err = pe.run_prosper("TEST", tier="delta", info={}, price_quote={"price": 231.5},
                               prior=prior, regime_hint={"state": "Amber"})
    assert res2, err
    kw = calls[-1]
    assert res2["model_used"] == "delta" and kw["messages"][0]["content"].startswith("delta TEST")
    assert "PRIOR RUN (P9" in kw["messages"][0]["content"]
    assert kw["tools"][0]["max_uses"] == 6
    assert "ALREADY ESTABLISHED" in kw["system"][1]["text"]

    # screen: no tools, thinking off
    res3, _ = pe.run_prosper("TEST", tier="screen", info={}, price_quote={"price": 231.5})
    assert "tools" not in calls[-1] and calls[-1]["thinking"] == {"type": "disabled"}
    assert res3["confidence"] == "Low" and res3["screen_only"]
