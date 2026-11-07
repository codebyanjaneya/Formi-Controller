"""Guardrail rule (D021): breach = (drop > policy max_drop AND significant) OR drop > 2x max_drop."""
import sys

sys.path.insert(0, ".")
from controller.experiments import guardrail_ok, ztest


def test_tiny_significant_drop_does_not_block():
    # 1pp drop, highly significant (huge n) — within the policy's 2pp allowance
    assert guardrail_ok(geff=-0.01, gp=0.0001, gdrop=0.02)


def test_breach_with_significance_blocks():
    assert not guardrail_ok(geff=-0.03, gp=0.01, gdrop=0.02)


def test_breach_without_significance_does_not_block():
    # noise-sized evidence of a >2pp drop: not enough to block (D019's false-block case)
    assert guardrail_ok(geff=-0.03, gp=0.4, gdrop=0.02)


def test_huge_point_drop_blocks_even_without_significance():
    assert not guardrail_ok(geff=-0.05, gp=0.4, gdrop=0.02)


def test_improvement_never_blocks():
    assert guardrail_ok(geff=0.04, gp=0.001, gdrop=0.02)


def test_with_real_ztest_numbers():
    # winner 46% vs residual 55% engagement on 500/300 calls: clear breach of a 2pp limit
    geff, gp = ztest(230, 500, 165, 300)
    assert geff < -0.02 and gp < 0.05
    assert not guardrail_ok(geff, gp, 0.02)
