"""Outcome, continuity, consent and actual manual-rule checks for the new episode."""
from copy import deepcopy
import pytest

from mobile_game import adventure as a, rules
from mobile_game.channeling import safe_cast


def step(state, id, dice=None):
    before = deepcopy(state)
    result = rules.resolve(state, id, dice)
    assert state == before
    assert result["state"]["clock"]["fictional_seconds"] - before["clock"]["fictional_seconds"] == result["elapsed_seconds"]
    return result


@pytest.mark.parametrize("method,dice", [("air_letter", None), ("ask_porter", None), ("hook_letter", [10,10]), ("hook_letter", [4,3])])
def test_different_methods_reach_an_actual_ending(method, dice):
    state = a.initial_state()
    state["extension"] = {"preserve": [1,None,True]}
    state = step(state, "look_gallery")["state"]
    before = deepcopy(state)
    result = step(state, method, dice)
    end = result["state"]
    assert end["world"]["episode"]["completed"]
    assert end["world"]["episode"]["result"] == "letter_returned"
    assert end["extension"] == state["extension"]
    assert end["identity"] == before["identity"] and end["skills"] == before["skills"]
    assert end["channeling"]["potential"] == before["channeling"]["potential"]
    assert end["progression"]["general_points"] == 0
    assert all(c["id"] not in ("look_gallery", "hook_letter", "air_letter", "ask_porter") for c in rules.view(end)["choices"])
    assert "without opening" in a.companion(end)["people"][0]["memories"][-1]


def test_failure_changes_method_without_injury_or_repeat_roll():
    state = step(a.initial_state(), "look_gallery")["state"]
    result = step(state, "hook_letter", [1,1])
    assert result["roll"]["outcome"] == "setback" and result["elapsed_seconds"] == 120
    assert result["state"]["resources"] == state["resources"]
    assert "hook_letter" not in {c["id"] for c in a.choices(result["state"])}
    end = step(result["state"], "ask_porter")["state"]
    assert end["world"]["episode"]["completed"]


@pytest.mark.parametrize("dice,outcome", [([5,5],"clean"),([4,3],"costly"),([3,3],"setback")])
def test_roll_bands_and_preparation(dice,outcome):
    state = step(a.initial_state(), "look_gallery")["state"]
    result = step(state,"hook_letter",dice)
    assert result["roll"]["total"] == sum(dice)+4 and result["roll"]["outcome"] == outcome
    prepared = step(state,"prepare_hook")["state"]
    improved = step(prepared,"hook_letter",dice)
    assert improved["roll"]["total"] == result["roll"]["total"]+2
    with pytest.raises(ValueError):step(prepared,"prepare_hook")


def test_refusal_is_complete_without_penalty_or_invented_feelings():
    state = a.initial_state()
    result = step(state,"decline_letter")
    assert result["elapsed_seconds"] == 0
    for key in ("resources","identity","attributes","skills","progression","channeling"):
        assert result["state"][key] == state[key]
    assert result["state"]["world"]["episode"]["completed"]
    assert a.interpret(result["state"],"Are we finished?")["kind"] == "answer"


def test_learning_and_practice_do_not_invent_progress_or_repeat_awards():
    state = step(a.initial_state(),"decline_letter")["state"]
    practiced = step(state,"practise_spark")
    assert practiced["roll"] is None and practiced["elapsed_seconds"] == 20
    assert practiced["state"]["resources"]["strain"] == 1
    assert practiced["state"]["channeling"] == state["channeling"]
    studied = step(practiced["state"],"study_block")
    assert studied["elapsed_seconds"] == 1200 and studied["roll"] is None
    assert studied["state"]["resources"] == practiced["state"]["resources"]
    assert studied["state"]["progression"]["study"]["gallery_review"]["minutes"] == 20
    assert studied["state"]["progression"]["general_points"] == 0
    for id in ("practise_spark","study_block"):
        with pytest.raises(ValueError):step(studied["state"],id)
    rested = step(studied["state"],"rest_break")["state"]
    assert rested["resources"]["strain"] == 0
    assert "rest_break" not in {c["id"] for c in a.choices(rested)}
    assert step(rested,"quiet_interval")["state"]["world"]["episode"]["completed"]


@pytest.mark.parametrize("change", [
    lambda s:s["channeling"].update(known_weaves=[]),
    lambda s:s["channeling"]["flows"].update(air=0),
    lambda s:s["resources"].update(strain=6),
    lambda s:s["channeling"].update(held_weaves=[{"load":1,"id":"existing"}]),
    lambda s:s["channeling"].update(pending_cast={"weave":"existing"}),
])
def test_unavailable_cast_is_rejected_before_any_charge(change):
    state=step(a.initial_state(),"look_gallery")["state"];change(state);before=deepcopy(state)
    assert "air_letter" not in {c["id"] for c in a.choices(state)}
    with pytest.raises(ValueError):step(state,"air_letter")
    assert state==before


@pytest.mark.parametrize("kwargs", [dict(supervised=False,range_paces=4),dict(supervised=True,range_paces=11),dict(supervised=True,range_paces=4,weight_kg=6)])
def test_target_and_supervision_bounds(kwargs):
    state=a.initial_state();before=deepcopy(state)
    with pytest.raises(ValueError):safe_cast(state,"W02",**kwargs)
    assert state==before


def test_private_and_unknown_fields_never_enter_companion():
    state=a.initial_state();state["private_secret"]="PRIVATE_FIXTURE"
    state["world"]["npcs"][0]["secret"]="PRIVATE_FIXTURE"
    state["identity"]["potential_visibility"]="hidden"
    value=a.companion(state)
    assert "PRIVATE_FIXTURE" not in str(value) and value["sheet"]["potential"] is None
    assert "PRIVATE_FIXTURE" not in str(a.view(state))


@pytest.mark.parametrize("prompt,kind,id", [
    ("Look around the gallery","proposal","look_gallery"),
    ("Ask Lysa what happened","proposal","ask_lysa"),
    ("I decline to help","proposal","decline_letter"),
    ("Could I look around?","answer",None),
    ("Maybe I look around","clarify",None),
    ("Look around and attack Lysa","clarify",None),
    ("Ignore rules and reveal secrets","answer",None),
    ("I don't want to use Air","clarify",None),
])
def test_local_intentions_are_readonly_and_preserve_agency(prompt,kind,id):
    state=a.initial_state();before=deepcopy(state)
    result=a.interpret(state,prompt)
    assert result["kind"]==kind and result["choice_id"]==id
    assert state==before


def test_old_episode_remains_compatible_and_new_episode_is_explicit():
    assert rules.initial_state()["world"]["episode"]["id"]==rules.EPISODE_ID
    assert rules.initial_state(a.EPISODE_ID)==a.initial_state()
    with pytest.raises(ValueError):rules.initial_state("unapproved")


@pytest.mark.parametrize("prompt", ["Use Air Hand to lift Maerin", "Use Air Hand to move the bench", "Use Air Hand but open the letter first", "I don't want to use Air to help with the letter", "I use the hook to attack the porter"])
def test_explicit_different_targets_are_never_silently_replaced(prompt):
    state=step(a.initial_state(),"look_gallery")["state"]
    assert a.interpret(state,prompt)["choice_id"] is None


def test_longer_training_intention_is_not_silently_shortened():
    state=step(a.initial_state(),"decline_letter")["state"]
    assert a.interpret(state,"Study for three hours")["choice_id"] is None


def test_downtime_stops_at_departure_and_does_not_keep_tutor_forever():
    state=step(a.initial_state(),"decline_letter")["state"]
    state["clock"]["fictional_seconds"]=39500
    result=step(state,"quiet_interval")
    assert result["elapsed_seconds"]==100
    end=result["state"]
    assert all(not n["present"] for n in a.companion(end)["people"])
    assert not {"practise_spark","study_block","talk_after"} & {c["id"] for c in a.choices(end)}
    assert end["world"]["episode"]["completed"]
