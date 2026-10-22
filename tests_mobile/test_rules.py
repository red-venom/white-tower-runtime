import json
import unittest
from copy import deepcopy

from mobile_game import rules


class DisposableRulesTests(unittest.TestCase):
    def plan(self, prepared=False):
        state = rules.resolve(rules.initial_state(), "accept_task")["state"]
        if prepared:
            state = rules.resolve(state, "prepare_grip")["state"]
        return state

    def test_independent_fixture_and_manual_starting_ratings(self):
        a, b = rules.initial_state(), rules.initial_state()
        a["resources"]["inventory"].append("test")
        self.assertNotEqual(a, b)
        self.assertEqual(sorted(b["attributes"].values()), [0, 1, 1, 2, 2])
        self.assertEqual(sorted(b["skills"].values()), [0]*6 + [1]*4 + [2]*2)
        self.assertEqual(b["resources"]["max_vitality"], 6 + 2*b["attributes"]["body"])
        self.assertTrue(b["disposable"])

    def test_all_100_unprepared_rolls_match_manual_bands(self):
        state = self.plan()
        counts = {"clean": 0, "costly": 0, "setback": 0}
        for first in range(1, 11):
            for second in range(1, 11):
                result = rules.resolve(state, "cross_courtyard", [first, second])
                total = first + second + 4
                expected = "clean" if total >= 14 else "costly" if total >= 11 else "setback"
                self.assertEqual(result["roll"]["outcome"], expected)
                self.assertEqual(result["roll"]["total"], total)
                counts[expected] += 1
                self.assertEqual(result["state"]["resources"], state["resources"])
        self.assertEqual(counts, {"clean": 64, "costly": 21, "setback": 15})

    def test_exact_boundaries_and_preparation_is_single_bonus(self):
        state = self.plan()
        for dice, outcome, elapsed in (([5, 5], "clean", 300), ([3, 4], "costly", 600), ([3, 3], "setback", 300)):
            result = rules.resolve(state, "cross_courtyard", dice)
            self.assertEqual(result["roll"]["outcome"], outcome)
            self.assertEqual(result["elapsed_seconds"], elapsed)
        prepared = rules.resolve(state, "prepare_grip")["state"]
        result = rules.resolve(prepared, "cross_courtyard", [4, 4])
        self.assertEqual(result["roll"]["modifier"], 2)
        self.assertEqual(result["roll"]["total"], 14)
        with self.assertRaises(ValueError):
            rules.resolve(prepared, "prepare_grip")
        stakes = next(c for c in rules.view(prepared)["choices"] if c["id"] == "cross_courtyard")["stakes"]
        for text in ("Grace 2", "Athletics 2", "preparation 2", "difficulty 14", "11–13", "10 or less"):
            self.assertIn(text, stakes)

    def test_safe_route_finishes_without_dice_and_no_chapter_award(self):
        state = self.plan()
        result = rules.resolve(state, "covered_route")
        self.assertIsNone(result["roll"])
        self.assertEqual(result["elapsed_seconds"], 900)
        self.assertTrue(rules.view(result["state"])["completed"])
        self.assertEqual(result["state"]["progression"], state["progression"])
        self.assertEqual(result["state"]["level"], 1)

    def test_setback_changes_route_and_cannot_repeat_unchanged_roll(self):
        setback = rules.resolve(self.plan(), "cross_courtyard", [1, 1])["state"]
        choices = {c["id"] for c in rules.view(setback)["choices"]}
        self.assertNotIn("cross_courtyard", choices)
        with self.assertRaises(ValueError):
            rules.resolve(setback, "cross_courtyard", [10, 10])
        for choice in choices:
            result = rules.resolve(setback, choice)
            self.assertIsNone(result["roll"])
            self.assertTrue(rules.view(result["state"])["completed"])
            self.assertEqual(result["state"]["world"]["episode"]["check_count"], 1)

    def test_refusal_and_alternative_end_without_penalty(self):
        for choice in ("decline_task", "move_inside"):
            state = rules.initial_state()
            result = rules.resolve(state, choice)
            self.assertTrue(rules.view(result["state"])["completed"])
            self.assertEqual(result["state"]["resources"], state["resources"])
            self.assertEqual(result["state"]["progression"], state["progression"])
            with self.assertRaises(ValueError):
                rules.resolve(result["state"], "accept_task")

    def test_unknown_state_is_preserved_but_not_in_public_view(self):
        state = self.plan()
        state["future_extension"] = {"secret": [1, {"private": "HIDDEN-CANARY"}]}
        state["world"]["private_gm_plan"] = "HIDDEN-CANARY"
        state["resources"]["future_item"] = {"arbitrary": "preserve"}
        original = deepcopy(state)
        result = rules.resolve(state, "cross_courtyard", [5, 5])
        self.assertEqual(state, original)
        for key in ("future_extension",):
            self.assertEqual(result["state"][key], original[key])
        self.assertEqual(result["state"]["world"]["private_gm_plan"], "HIDDEN-CANARY")
        self.assertEqual(result["state"]["resources"]["future_item"], {"arbitrary": "preserve"})
        self.assertNotIn("HIDDEN-CANARY", json.dumps(rules.view(result["state"])))

    def test_bad_dice_and_unavailable_choice_do_not_mutate(self):
        state = self.plan()
        original = deepcopy(state)
        for dice in (None, [], [1], [0, 5], [5, 11], [True, 5], [1.5, 4], [1, 2, 3], "5,5"):
            with self.assertRaises(ValueError):
                rules.resolve(state, "cross_courtyard", dice)
            self.assertEqual(state, original)
        with self.assertRaises(ValueError):
            rules.resolve(state, "covered_route", [10, 10])
        with self.assertRaises(ValueError):
            rules.resolve(state, "invented_action")
        self.assertEqual(state, original)

    def test_quiet_and_recovery_keep_objective_finished(self):
        state = rules.resolve(rules.initial_state(), "move_inside")["state"]
        state["resources"].update(vitality=7, strain=1, wounds=1)
        quiet = rules.resolve(state, "quiet_interval")
        self.assertEqual(quiet["state"]["resources"], state["resources"])
        rested = rules.resolve(quiet["state"], "rest_break")["state"]
        self.assertEqual(rested["resources"]["vitality"], 8)
        self.assertEqual(rested["resources"]["strain"], 0)
        self.assertEqual(rested["resources"]["wounds"], 1)
        self.assertTrue(rules.view(rested)["completed"])
        self.assertNotIn("rest_break", {c["id"] for c in rules.view(rested)["choices"]})
        for _ in range(5):
            rested = rules.resolve(rested, "quiet_interval")["state"]
        self.assertIn("rest_break", {c["id"] for c in rules.view(rested)["choices"]})
        second = rules.resolve(rested, "rest_break")["state"]
        self.assertEqual(second["clock"]["last_break_end"] - quiet["state"]["clock"]["fictional_seconds"] - 600, 3600)

    def test_resolve_and_view_reject_non_sample_campaign(self):
        state = rules.initial_state()
        state["disposable"] = False
        for operation in (lambda: rules.view(state), lambda: rules.resolve(state, "accept_task")):
            with self.assertRaises(ValueError):
                operation()


if __name__ == "__main__":
    unittest.main()
