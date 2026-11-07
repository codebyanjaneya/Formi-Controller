"""Winner test: deterministic, Bonferroni-corrected, no winner on equal arms."""
import sys

sys.path.insert(0, ".")
from controller.experiments import winner_test, n_per_arm


def test_clear_winner():
    v = winner_test({"champ": (500, 1000), "c1": (600, 1000)}, "champ")
    assert v and v["winner"] == "c1" and v["effect"] > 0.09


def test_equal_arms_no_winner():
    assert winner_test({"champ": (500, 1000), "c1": (505, 1000), "c2": (498, 1000)},
                       "champ") is None


def test_worse_challenger_never_wins():
    assert winner_test({"champ": (600, 1000), "c1": (500, 1000)}, "champ") is None


def test_bonferroni_tightens_with_more_challengers():
    # a borderline challenger that wins alone must not win when k=4 splits alpha
    arms1 = {"champ": (500, 1000), "c1": (546, 1000)}
    assert winner_test(arms1, "champ") is not None
    arms4 = dict(arms1, c2=(500, 1000), c3=(500, 1000), c4=(500, 1000))
    assert winner_test(arms4, "champ") is None


def test_n_per_arm_monotonic():
    assert n_per_arm(0.5, 0.05, 0.05) > n_per_arm(0.5, 0.10, 0.05)
    assert n_per_arm(0.5, 0.05, 0.0125) > n_per_arm(0.5, 0.05, 0.05)
