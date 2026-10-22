"""Only synthetic manual-v2 fixtures; never load a player campaign in tests."""
from copy import deepcopy
import json
import unittest

from mobile_game import migration as m

HEAD_REF = "https://app.notion.com/p/11111111111141118111111111111111"
PREV_REF = "https://app.notion.com/p/22222222222242228222222222222222"
GM_REF = "https://app.notion.com/p/33333333333343338333333333333333"


def fixtures():
    state = {
        "identity": {"name": "Synthetic migration fixture", "dice_method": "player-supplied",
                     "outside_obligation": {"unresolved": "PRIVATE-CANARY"}},
        "attributes": dict(zip(m.ATTRIBUTES, (0, 1, 2, 2, 1))),
        "skills": {key: (2 if key in ("Notice", "Scholarship") else 0) for key in m.SKILLS},
        "rank": "novice", "level": 3,
        "resources": {"vitality": 6, "max_vitality": 6, "wounds": 0, "strain": 0,
                      "supply": 4, "silver": 6, "inventory": [{"name": "synthetic item", "future": [1, None, False]}]},
        "channeling": {"potential": 10, "potential_roll": {"die": "d3", "value": 3, "base": 7, "provenance": "synthetic fixture"},
                       "capacity": 4, "control": 2, "flows": {key: 1 for key in m.FLOWS},
                       "source_embraced": False, "known_weaves": ["W01", "W02"], "held": [], "tied": [],
                       "pending_cast": None, "circle": None, "angreal": None},
        "clock": {"fictional_seconds": 600, "day_activity_seconds": 180,
                  "last_break_end": None, "last_full_rest_end": 0, "unknown_clock_credit": 17},
        "progression": {"chapter": {"number": 3, "status": "active", "future_field": "retain"},
                        "proofs": [{"id": "proof-test", "evidence": "synthetic"}], "general_points": 4,
                        "channel_points": 2, "learning_opportunities": 2, "courses": {"N01": {"partial_seconds": 30}},
                        "capacity_proofs": [], "service_records": [], "readiness": None,
                        "formal_test": None, "rank_choices": None, "completed_chapters": [1, 2]},
        "world": {"location": "Synthetic room", "scene": {"id": "synthetic", "status": "completed", "description": "Fixture only"},
                  "scene_plan": {"private_development": "PRIVATE-CANARY"}, "known_facts": [], "allies": [],
                  "npcs": [{"id": "synthetic-npc", "private": "PRIVATE-CANARY"}], "projects": [],
                  "commitments": [], "due_events": [{"id": "old-event", "status": "resolved"}],
                  "threat_clocks": [], "conflict": None},
        "unresolved_decisions": [{"id": "choice-test", "topic": "synthetic decision"}],
        "unrecognised_future_extension": {"decimal_metadata": 1.25, "nested": ["retain", {"x": None}]},
    }
    before = deepcopy(state)
    before["clock"]["fictional_seconds"] = 420
    checkpoint = {"campaign_id": "synthetic-only", "rules_edition": m.EDITION,
                  "head": HEAD_REF, "revision": 7, "pending": None, "state": state,
                  "future_checkpoint_extension": {"keep": True}}
    head = {"schema": "notion-turn-v1", "campaign_id": "synthetic-only", "action_id": "synthetic-action-7",
            "sequence": 7, "predecessor_page": PREV_REF, "predecessor_revision": 6,
            "rules_edition": m.EDITION, "status": "COMMITTED", "intent": {"text": "synthetic routine"},
            "rules_citations": ["synthetic source"], "stakes": {"routine": True}, "acceptance": {"accepted": True},
            "dice": {"method": "none", "values": [], "source": "routine fixture"},
            "pre_state": before, "post_state": deepcopy(state), "resolution": {"elapsed_seconds": 180},
            "narration": "Synthetic outcome.", "checks": {"fixture": True}, "future_turn_extension": [1, 2, 3]}
    gm = {"id": "33333333-3333-4333-8333-333333333333", "url": GM_REF,
          "title": "PRIVATE-CANARY", "text": "PRIVATE-CANARY: synthetic private planning only.",
          "metadata": {"unknown": 1.5}, "page_last_edited_at": "2026-01-01T00:00:00Z"}
    return checkpoint, head, gm


class MigrationCapsuleTests(unittest.TestCase):
    def build(self, *values):
        return m.create_capsule(*(values or fixtures()), committed_head_reference=HEAD_REF)

    def test_lossless_deterministic_and_no_input_mutation(self):
        sources = fixtures()
        originals = deepcopy(sources)
        capsule = self.build(*sources)
        self.assertEqual(sources, originals)
        self.assertEqual(capsule, self.build(*sources))
        self.assertEqual(m.canonical(capsule["source_archive"]["checkpoint"]), m.canonical(sources[0]))
        self.assertEqual(m.canonical(capsule["source_archive"]["committed_head"]), m.canonical(sources[1]))
        self.assertEqual(m.canonical(capsule["private_reference"]["gm_record"]), m.canonical(sources[2]))
        self.assertFalse(capsule["playable"])
        self.assertTrue(m.validate_capsule(capsule))
        capsule["source_archive"]["checkpoint"]["state"]["resources"]["silver"] = 999
        self.assertEqual(sources, originals)

    def test_roundtrip_keeps_full_sources_and_no_story_in_receipt(self):
        capsule = self.build()
        loaded = m.load_json_bytes(m.canonical(capsule))
        self.assertTrue(m.validate_capsule(loaded))
        report = m.redacted_report(loaded)
        text = json.dumps(report)
        for private in ("PRIVATE-CANARY", "Synthetic migration fixture", "synthetic-only", HEAD_REF, GM_REF):
            self.assertNotIn(private, text)
        self.assertFalse(report["playable"])
        self.assertFalse(report["checks"]["freshness_or_authenticity_verified"])

    def test_pending_save_must_be_reconciled(self):
        for pending in ({}, {"action_id": "pending-test"}, False, "pending"):
            cp, head, gm = fixtures()
            cp["pending"] = pending
            with self.assertRaises(m.MigrationError):
                self.build(cp, head, gm)

    def test_unknown_schema_and_wrong_edition_rejected(self):
        for target, key, value in ((0, "schema", "unknown-checkpoint"), (1, "schema", "unknown-turn"),
                                   (2, "schema", "unknown-page"), (0, "rules_edition", "legacy")):
            sources = list(fixtures())
            sources[target][key] = value
            with self.assertRaises(m.MigrationError):
                self.build(*sources)

    def test_sample_shape_cannot_masquerade_as_manual_campaign(self):
        from mobile_game.rules import initial_state
        cp, head, gm = fixtures()
        cp["state"] = head["post_state"] = initial_state()
        with self.assertRaises(m.MigrationError):
            self.build(cp, head, gm)

    def test_revision_campaign_and_commit_must_agree(self):
        for key, value in (("campaign_id", "another-fixture"), ("sequence", 8),
                           ("predecessor_revision", 7), ("status", "PREPARED")):
            cp, head, gm = fixtures()
            head[key] = value
            with self.assertRaises(m.MigrationError):
                self.build(cp, head, gm)

    def test_fetched_head_identity_is_required_and_normalises_uuid(self):
        cp, head, gm = fixtures()
        with self.assertRaises(m.MigrationError):
            m.create_capsule(cp, head, gm, committed_head_reference=PREV_REF)
        valid = m.create_capsule(cp, head, gm, committed_head_reference="11111111-1111-4111-8111-111111111111")
        self.assertTrue(m.validate_capsule(valid))
        head["predecessor_page"] = HEAD_REF
        with self.assertRaises(m.MigrationError):
            self.build(cp, head, gm)

    def test_full_post_state_equality_includes_unknown_extensions(self):
        cp, head, gm = fixtures()
        head["post_state"]["unrecognised_future_extension"]["nested"].append("diverged")
        with self.assertRaises(m.MigrationError):
            self.build(cp, head, gm)

    def test_clock_delta_safe_integer_and_resource_invariants(self):
        for mutation in ("elapsed", "clock", "body_formula", "strain"):
            cp, head, gm = fixtures()
            if mutation == "elapsed":
                head["resolution"]["elapsed_seconds"] = 179
            elif mutation == "clock":
                cp["state"]["clock"]["fictional_seconds"] = m.MAX_INT + 1
                head["post_state"] = deepcopy(cp["state"])
            elif mutation == "body_formula":
                cp["state"]["resources"]["max_vitality"] = 8
                head["post_state"] = deepcopy(cp["state"])
            else:
                cp["state"]["resources"]["strain"] = 9
                head["post_state"] = deepcopy(cp["state"])
            with self.assertRaises(m.MigrationError):
                self.build(cp, head, gm)

    def test_private_gm_identity_and_completeness(self):
        for key, value in (("id", "44444444-4444-4444-8444-444444444444"), ("text", ""), ("truncated", True)):
            cp, head, gm = fixtures()
            gm[key] = value
            with self.assertRaises(m.MigrationError):
                self.build(cp, head, gm)

    def test_changed_capsule_cannot_be_made_playable_by_rehashing(self):
        capsule = self.build()
        capsule["playable"] = True
        capsule["checksum_sha256"] = m.checksum({k: v for k, v in capsule.items() if k != "checksum_sha256"})
        with self.assertRaises(m.MigrationError):
            m.validate_capsule(capsule)

    def test_strict_json_rejects_duplicates_nonfinite_and_non_json(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'\xff', b'{'):
            with self.assertRaises(m.MigrationError):
                m.load_json_bytes(raw)
        for value in ({1: "key"}, {"x": (1, 2)}, {"x": float("nan")}):
            with self.assertRaises(m.MigrationError):
                m.canonical(value)


if __name__ == "__main__":
    unittest.main()
