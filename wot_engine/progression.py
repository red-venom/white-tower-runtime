"""Exact, deterministic curriculum and advancement for new full-content games.

Training fixtures have no adventure effects. Their typed programs still spend
real time and Strain, except in the explicitly protected formal assessment mode.
No caller can supply an assertion that grants chapter or service evidence.
"""
from copy import deepcopy

from .catalogue import WEAVES, prerequisites
from .contracts import canonical, digest
from .rules import ATTRIBUTES, FLOWS, SKILLS, RuleError

RULES_VERSION = "rules-v2"
DAY = 28800
REQUIRED = tuple(f"W{i:02}" for i in (1,2,3,4,5,6,7,8,9,11,12,20))
ACCEPTED_WEAVES = ("W01","W02","W07","W08","W11","W12")
N_IDS = tuple(f"N{i:02}" for i in range(1,11))
G_IDS = tuple(f"G{i:02}" for i in range(1,11))
W_IDS = tuple(WEAVES)
COURSES = N_IDS + G_IDS + W_IDS + ("rehearsal",)
AJAH = ("blue","brown","gray","green","red","white","yellow")
CURRICULUM_SOURCE_SHA256 = '37808cf9c30ddda436002cbee7d7762099ba895cbc0288a5862bbf48afd50c45'
FORM_TEXT = {
    "F001": "Cast W02. Move the bead along a straight 30 cm line and stop on its end mark.",
    "F002": "Cast W02. Follow two 15 cm legs with one right-angle turn.",
    "F003": "Cast W02. Follow a square with four 10 cm sides and return to its start.",
    "F004": "Cast W02. Follow a triangle with three 15 cm sides without crossing its centre.",
    "F005": "Cast W02. Follow a circle 10 cm across and stop at its marked point.",
    "F006": "Cast W02. Lift the bead 10 cm, pause ten seconds and lower it onto its mark.",
    "F007": "Cast W02. Carry the bead around a fixed obstruction without touching it.",
    "F008": "Cast W02. Transfer the bead between two marked cups one metre apart.",
    "F009": "Cast W02 to carry the bead above a safe pad. Stop and release when the partner requests it.",
    "F010": "Cast W02 along the straight, right-angle and circle marks from F001, F002 and F005. Record the actions and Strain accurately.",
    "F011": "Cast W01 to ignite one dry wick. Extinguish it by the agreed ordinary method.",
    "F012": "Cast W01 on three wicks in order. Record three casts and 3 Strain.",
    "F013": "Cast W07 over a reading board without treating light as damaging heat.",
    "F014": "Cast W08 to warm one litre from 20°C to 30°C.",
    "F015": "Cast W08 to warm one litre from 20°C to 40°C with one cast.",
    "F016": "Cast W08 to warm one litre from 30°C to 45°C, below the entry's ceiling.",
    "F017": "Reject warming living tissue. Cast W08 on one litre of water, raising it from 20°C to 35°C as an allowed alternative.",
    "F018": "Cast W07 on a carried object. Move it two metres while preserving its permitted range.",
    "F019": "Select dry tinder from labelled dry and wet samples. Cast W01 to ignite only the dry sample.",
    "F020": "Cast W07, then W01 on prepared fuel while holding the light. Release W07 and record both costs.",
    "F021": "Cast W11 to transfer two litres into a marked vessel in 60 seconds.",
    "F022": "Cast W11 to transfer five litres in 150 seconds. Record the exact time without rounding to whole minutes.",
    "F023": "Cast W11 to transfer ten litres over 300 seconds without overflowing.",
    "F024": "Cast W11 to raise five litres from an open source one metre below the destination.",
    "F025": "Cast W11 to transfer water into a marked vessel. Stop at its line within 100 ml.",
    "F026": "Cast W12 to settle visible grit in one litre over ten minutes.",
    "F027": "Cast W12 on a muddy sample in a labelled vessel. Retain its sediment rather than deleting evidence.",
    "F028": "Cast W09 to cool ten litres from 30°C to 10°C with one cast.",
    "F029": "Cast W12 on two litres of visibly muddy water. Explain why its clear appearance does not prove safety.",
    "F030": "Cast W12 to settle a sample. Then cast W11 to transfer its clear upper water without disturbing sediment.",
    "F031": "Cast W12 to settle coarse grit in five litres. Preserve the sample label.",
    "F032": "Cast W12 to settle sand without claiming that dissolved material was removed.",
    "F033": "Cast W12 to settle visible fine silt, allowing the full ten-minute casting time.",
    "F034": "Cast W12 on mixed grit and silt. Retain the combined sediment.",
    "F035": "Cast W12 on labelled saline water containing sand. Reject a claim that the dissolved salt was removed.",
    "F036": "Cast W12 on an unidentified, safely contained sample with visible grit. Preserve it without assigning an unsupported identity.",
    "F037": "Record a muddy sample's starting volume and observable sediment. Cast W12, then record the remaining water and sediment.",
    "F038": "Cast W12 on two vessels separately. Record 2 Strain.",
    "F039": "Cast W12 on a muddy sample, then pour ordinarily. Do not invent a sorting effect.",
    "F040": "Reject an over-capacity cast in a written case. Then check actual free Load and cast W12 on an eligible sample.",
    "F041": "Cast W04 around a one-metre marked area.",
    "F042": "Cast W04 around a five-metre marked area.",
    "F043": "Cast W04 three metres away within its permitted range.",
    "F044": "Cast W04 around a marked area and report a partner's crossing. Do not claim the Ward supplied an identity.",
    "F045": "Cast W04, then pass a stone through its boundary ordinarily. Explain why the stone is not a creature trigger.",
    "F046": "Cast W04, observe a willing partner cross and record the warning.",
    "F047": "Cast W04 and observe two willing partners cross separately. Distinguish warning events from independently observed identities.",
    "F048": "Cast W03 as an agreed harmless Binding. Release immediately on request.",
    "F049": "Cast W04, then tie it with a second action and one extra Strain. Record its continuing Load.",
    "F050": "Cast W04 and tie it. Record its expiry, advance time safely and confirm it ended.",
    "F051": "Cast W02 and W07, hold both, then release in the declared order.",
    "F052": "Cast W04 and W07. Hold both while reading an ordinary notice.",
    "F053": "Cast W05 on a consenting partner and W07 on their carried marker. Hold both.",
    "F054": "Cast W04 and W03. Hold both with the partner's continuing consent.",
    "F055": "Cast W20 before an unresisting dummy drops one metre. Confirm that Catch ends after use.",
    "F056": "Cast W07, then W08 on a basin while holding the light. Record peak Load 2.",
    "F057": "Cast W04, then W01 on safe fuel while holding the Ward. Record peak Load 3.",
    "F058": "Cast W11 to draw water and release it. Then cast W09 to cool the collected water.",
    "F059": "Cast W05 and W02. Hold both, then choose one to release in a narrated concentration-loss case. Apply no actual harm.",
    "F060": "Cast W07 and W02. Release W02, then cast W04 after checking Load and Strain. Total Strain is 4.",
    "F061": "Cast the W06 practice pattern along a straight fixture path. Do not claim a bodily effect.",
    "F062": "Cast the W06 practice pattern along a right-angle fixture path. Identify recipient, consent and ordinary care in the accompanying case.",
    "F063": "Cast the W06 practice pattern along a triangular fixture path. Calculate that 3 of 8 Vitality becomes 7 after eligible Healing.",
    "F064": "Cast the W06 practice pattern along a square fixture path. Calculate that 7 of 8 Vitality becomes 8, without overflow.",
    "F065": "Cast the W06 practice pattern along a circular fixture path, or treat an eligible existing patient with W06. Record the chosen case.",
    "F066": "Cast the W06 practice pattern around a marked obstruction. Retain the case's existing Wound and explain its ordinary recovery.",
    "F067": "Reject self-Healing in the written case. Cast the W06 practice pattern along two adjoining fixture loops as the permitted demonstration.",
    "F068": "Check the written patient's last full rest. Cast the W06 practice pattern between two marked fixture endpoints without granting that patient another benefit.",
    "F069": "Cast the W06 practice pattern along a three-turn fixture path. Explain why restored Vitality leaves Strain and an undefined illness unchanged.",
    "F070": "Cast the W06 practice pattern along the labelled straight, curved and return sections. Give a handover with treatment limits and remaining uncertainty.",
    "F071": "Cast W03, W04 and W05 in that order. Record the display's three slots.",
    "F072": "Cast W04, W05 and W03. Explain the display while a partner asks one distracting ordinary question.",
    "F073": "Cast W05, W03 and W04. Pause conversation to check consent while preserving the safe display.",
    "F074": "Cast W03, W04 and W05. Release W03 first on request and retain only the other permitted effects.",
    "F075": "Cast W04, W03 and W05. Release W04 while preserving the consenting partner's W05.",
    "F076": "Cast W05, W04 and W03. Release W05 while retaining the harmless Ward and Binding.",
    "F077": "Cast W03, W05 and W04. Resolve a narrated concentration-loss case by choosing one to release. Apply no actual harm.",
    "F078": "Cast W04, W03 and W05. Explain when 1 Strain preserves concentration and when the limit prohibits it. Do not spend a hypothetical cost.",
    "F079": "Cast W05, W03 and W04. Respond to an ordinary unexpected noise by releasing W03, then the other two effects.",
    "F080": "Cast W03, W04 and W05. Release them in reverse order and reconcile Load, slots and Strain without a refund.",
    "F081": "Cast W03, W04, W05 and W02 to establish the four-weave display. Record the casting order.",
    "F082": "Cast W04, W05, W03 and W02. Name their individual Loads and total without counting anything twice.",
    "F083": "Cast W03, W04, W05 and W02. Move a marked object with W02 while preserving the other three effects.",
    "F084": "Cast W03, W04, W05 and W02. Explain why another Load 2 cannot fit at capacity 8 with committed Load 7.",
    "F085": "Cast W03, W04, W05 and W02. Release W02 and show that committed Load falls from 7 to 6.",
    "F086": "Cast W03, W04, W05 and W02. Release W04 and state that its warning is no longer available.",
    "F087": "Cast W03, W04, W05 and W02. End W03 on request. Apply contribution restoration in an accompanying inert conflict example.",
    "F088": "Cast W03, W04, W05 and W02. Release W02, then cast W07 after checking resources. Peak Load remains 7; total Strain becomes 8.",
    "F089": "Cast W03, W04, W05 and W02. Tie W04 and explain its continuing committed Load. Untie it before ending this form.",
    "F090": "Cast W03, W04, W05 and W02 for CP05's safe display. Reuse valid CP05 mastery evidence instead of demanding a second training proof.",
    "F091": "Cast W03, W04, W05 and W02, then W01 on prepared tinder. Peak Load and total Strain are 8.",
    "F092": "Cast W03, W04, W05 and W02. Release W02, check resources, then cast W20 before a dummy drop. Peak Load is 8; Strain is 9.",
    "F093": "Cast W03, W04, W05 and W02. Release W03, then cast W07. Identify the remaining effects and record total Strain 8.",
    "F094": "Cast W03, W04, W05 and W02. Release W05, then cast W20 before a dummy drop. Peak Load is 7; Strain is 9.",
    "F095": "Cast W03, W04, W05 and W02, then release all four. Cast F061's W06 fixture pattern or eligible live Healing. Total Strain is 10.",
    "F096": "Cast W12 on muddy water, then W11 to transfer the clear upper water. Explain why appearance cannot guarantee safe provision.",
    "F097": "Reject W08 on living tissue before spending casting time or Strain. Then cast W08 on one litre of water from 20°C to 30°C.",
    "F098": "Cast W03, W04, W05 and W02. Use the existing W02 to retrieve a partner's dropped marker while preserving consent and safe effects.",
    "F099": "Cast W04 around a one-metre area. Restate changed instructions, limits and consent; release it, then cast W04 around a two-metre area.",
    "F100": "Cast W04, W05, W03 and W02, then W01 on safe tinder. Release held effects in reverse order and record all effects, resources and evidence."
}
NOVICE_TEXT = {
    "N01": "State an effect, check its limits and release a harmless weave on request.",
    "N02": "Keep a practice record with one corrected mistake and its evidence.",
    "N03": "Obtain consent and stop when a practice partner withdraws.",
    "N04": "Separate a fact, inference and rumour in a report.",
    "N05": "Prepare first aid and identify when qualified help is needed.",
    "N06": "Plan a short trip with Supply, rest, route and return conditions.",
    "N07": "Explain two defensible responses to competing responsibilities. Choose one and accept its stated consequence.",
    "N08": "Demonstrate escape, preparation, negotiation or controlled defence. Winning a fight is unnecessary.",
    "N09": "Explain known facts and remaining uncertainty clearly.",
    "N10": "Complete a useful task, hand it over and identify an improvement."
}
VERBS = frozenset(("study","demonstrate","capacity_proof","review","start_bridge",
                   "finish_bridge","spend_points","reassign_channel","complete_chapter",
                   "begin_chapter","service","formal_start","formal_scene","rank_choice"))


def need(condition, message):
    if not condition:
        raise RuleError(message)


def integer(value, low=0, high=2**53-1):
    return type(value) is int and low <= value <= high


def closed(intent, required=(), optional=()):
    need(type(intent) is dict and set(required) <= set(intent) and
         set(intent) <= {"verb", *required, *optional}, "Invalid progression intent fields.")


def handles(intent):
    return type(intent) is dict and intent.get("verb") in VERBS


def before_action(state, intent):
    """A protected assessment resumes through its own next scene only."""
    for kind in ("accepted","shawl"):
        test=state["progression"][kind+"_test"]
        if test["started"] and not test["completed"]:
            need(intent.get("verb")=="formal_scene" and intent.get("kind")==kind,
                 "Complete the active protected assessment scenes before another activity.")


def _course():
    return {"seconds":0,"status":"not_started","source":None,"evidence":None,"proofs":{}}


def _entry(record, course):
    return record[course] if record[course] is not None else _course()


def _service():
    return {"seconds":0,"days":0,"partial_seconds":0,"status":"not_started",
            "settings":[],"outside_group":False,"benefits":0,"last_event":None,"task_credit":{}}


def initialize(state):
    need("progression" not in state, "Progression already exists; migrations are explicit.")
    p = state["pc"]
    p["general_points"] = 0
    p["channel_points"] = 0
    p["ajah"] = None
    p["oaths_source_event"] = "genesis"
    record = dict.fromkeys(COURSES)
    for key in p["known_weaves"]:
        record[key] = {"seconds":0,"status":"mastered","source":"creation",
                       "evidence":"genesis","proofs":{key:{"hash":digest({"creation":key}),"event":"genesis"}}}
    record.update(
        chapter={"number":1,"completed":0,"stage":"active","gp_awarded":0,
                 "cp_awarded":0,"learning_awarded":0,"last_award_event":None},
        capacity={"completed":0,"last_event":None,"last_proof":None},
        service_novice=_service(),service_accepted=_service(),service_independent=_service(),
        reviews={"accepted":None,"technical":None,"full":None},
        bridge={"target":None,"seconds":0,"status":"none","source":None,"evidence":None},
        accepted_test={"started":False,"completed":False,"scene":0,"evidence":[],
                       "deferred_work_seconds":0,"service_obligations":0},
        shawl_test={"started":False,"completed":False,"scene":0,"evidence":[],
                    "deferred_work_seconds":0,"service_obligations":0,"form_count":0,"form_hash":None},
        qualification={"accepted":False,"shawl":False,"rank_choice":"defer",
                       "oaths_choice":"defer","ajah_choice":"defer"},
        obligations={"service_days":0,"source_events":[]},
        channel_spent=0,general_spent=0,
    )
    state["progression"] = record


def _required_seconds(course):
    return (4 if course in N_IDS else 10 if course in G_IDS else 5) * DAY


def _group_requirements(number):
    flows = {1:{"air":2},2:{"air":1,"fire":1},3:{"water":2,"air":1,"earth":1,"fire":1},
             4:{"earth":2,"water":2},5:{"air":2,"spirit":2}}
    known = {1:("W02",),2:("W01","W07","W08"),3:("W09","W11","W12"),
             4:("W12",),5:("W03","W04"),6:REQUIRED,7:("W06",),
             8:("W03","W04","W05"),9:("W02","W03","W04","W05","W07"),10:REQUIRED}
    return {"control":2 if number <= 2 else 3 if number <= 8 else 4,
            "flows":flows.get(number,dict.fromkeys(FLOWS,2)),
            "capacity":{8:6,9:7,10:8}.get(number,3),"known":known[number]}


def _eligible(state, course):
    p = state["pc"]
    if course in W_IDS:
        prerequisites(p,course,require_known=False)
    elif course in G_IDS:
        need(p["rank"] in ("accepted","aes_sedai"), "Hundred-form study begins during Accepted training.")
        group = _group_requirements(int(course[1:]))
        need(p["control"] >= group["control"] and p["capacity"] >= group["capacity"] and
             all(p["flows"][flow] >= level for flow,level in group["flows"].items()) and
             set(group["known"]) <= set(p["known_weaves"]), "This form group's prerequisites are not met.")
    elif course == "rehearsal":
        need(readiness(state,"technical")["ready"], "Complete technical readiness before rehearsal.")


def _source(state, source):
    need(source in ("curriculum-library","appointed-tutor"), "Use the curriculum library or appointed substitute tutor.")
    if source == "curriculum-library":
        need(state["world"].get("library_available",False), "The library is unavailable; use the appointed tutor.")
    # The appointed substitute is an institutional entitlement. It is not
    # friendship with a unique NPC, and cannot grant adventure effects.
    need(state["world"].get("safe",False), "Guided instruction needs a safe setting.")


def _safe(state, *, no_work=True):
    p,w = state["pc"],state["world"]
    need(w.get("safe") and not w.get("active_conflict"), "Progression requires a safe interval.")
    need(not p["held"] and not p["tied"] and not p.get("magic",{}).get("pending"),
         "End committed effects before guided training.")
    need(not p.get("magic",{}).get("circle"),"End the active circle before individual training or progression.")
    need(not no_work or p["pending_work_seconds"] == 0, "Finish outstanding follow-up work first.")


def _activity(state, seconds, kind, advance):
    from .regional import advance_activity
    return advance_activity(state,seconds,kind,advance_clock=advance)


def _participant(state, program, identifier):
    needed = any(step[0]=="cast" and step[1] in ("W03","W05") for step in program) or identifier in (
        "N03","F009","F044","F046","F047")
    if not needed:
        return None
    occupied=set((state["pc"].get("magic",{}).get("circle") or {}).get("members",[]))
    people=sorted(key for key,value in state.items() if value.get("kind")=="person" and key not in occupied and
                  not value.get("magic",{}).get("circle_id") and
                  value.get("visible") is True and value.get("willing") is True and
                  value.get("consenting") is True and value.get("alive") is True and
                  value.get("location")==state["world"]["location"] and
                  value.get("distance_m",1000) <= 10)
    count=2 if identifier=="F047" else 1
    need(len(people)>=count,"This demonstration needs a present consenting assistant; use another teaching source or return with a willing partner.")
    return people[:count]


def _casts(*ids):
    return [("cast",wid) for wid in ids]


def _programs():
    programs = {}
    def put(number, steps):
        identifier=f"F{number:03}"
        programs[identifier] = tuple([("instructions",identifier)] + steps + [("release_all",)])
    for n in range(1,11):
        put(n,_casts("W02")+[("fixture",f"air-path-{n:02}")])
    put(6,_casts("W02")+[("fixture","lift-ten-centimetres"),("wait",10),("fixture","lower-to-mark")])
    for n,ids in {11:("W01",),12:("W01","W01","W01"),13:("W07",),
                  14:("W08",),15:("W08",),16:("W08",),17:("W08",),
                  18:("W07",),19:("W01",),20:("W07","W01")}.items():
        put(n,_casts(*ids)+[("fixture",f"heat-light-{n:03}")])
    for n,seconds in ((21,60),(22,150),(23,300),(24,150),(25,30)):
        put(n,[("cast","W11"),("wait",seconds-10),("fixture",f"open-water-{n:03}")])
    for n in (26,27,29,*range(31,38),39,40):
        put(n,_casts("W12")+[("fixture",f"sediment-{n:03}")])
    put(28,_casts("W09")+[("fixture","ten-litres-30-to-10")])
    put(30,_casts("W12","W11")+[("wait",20),("fixture","clear-upper-water")])
    put(38,_casts("W12","W12"))
    for n in range(41,48):
        put(n,_casts("W04")+[("fixture",f"ward-boundary-{n:03}")])
    put(48,_casts("W03")+[("release","W03"),("fixture","partner-withdraws-consent")])
    put(49,_casts("W04")+[("tie","W04"),("untie","W04")])
    put(50,_casts("W04")+[("tie","W04"),("wait",3600),("expire","W04")])
    for n,ids in {51:("W02","W07"),52:("W04","W07"),53:("W05","W07"),
                  54:("W04","W03"),55:("W20",),56:("W07","W08"),
                  57:("W04","W01"),59:("W05","W02")}.items():
        put(n,_casts(*ids)+[("fixture",f"paired-{n:03}")])
    put(58,_casts("W11")+[("wait",20),("release","W11")]+_casts("W09"))
    put(60,_casts("W07","W02")+[("release","W02")]+_casts("W04"))
    for n in range(61,71):
        put(n,[("fixture_cast","W06"),("fixture",f"healing-path-{n:03}")])
    orders = {71:("W03","W04","W05"),72:("W04","W05","W03"),73:("W05","W03","W04"),
              74:("W03","W04","W05"),75:("W04","W03","W05"),76:("W05","W04","W03"),
              77:("W03","W05","W04"),78:("W04","W03","W05"),79:("W05","W03","W04"),
              80:("W03","W04","W05")}
    releases = {74:"W03",75:"W04",76:"W05",77:"W03",79:"W03"}
    for n,ids in orders.items():
        steps = _casts(*ids)
        if n in releases:
            steps.append(("release",releases[n]))
        if n == 80:
            steps.extend(("release",wid) for wid in reversed(ids))
        put(n,steps+[("fixture",f"attention-{n:03}")])
    four = ("W03","W04","W05","W02")
    for n in range(81,91):
        steps = _casts(*(("W04","W05","W03","W02") if n == 82 else four))
        if n in (85,86,87):
            steps.append(("release",{85:"W02",86:"W04",87:"W03"}[n]))
        elif n == 88:
            steps += [("release","W02"),("cast","W07")]
        elif n == 89:
            steps += [("tie","W04"),("untie","W04")]
        put(n,steps+[("fixture",f"commitments-{n:03}")])
    put(91,_casts(*four,"W01"))
    put(92,_casts(*four)+[("release","W02"),("cast","W20"),("fixture","dummy-drop")])
    put(93,_casts(*four)+[("release","W03"),("cast","W07")])
    put(94,_casts(*four)+[("release","W05"),("cast","W20"),("fixture","dummy-drop")])
    put(95,_casts(*four)+[("release_all",),("fixture_cast","W06")])
    put(96,_casts("W12","W11")+[("wait",20),("fixture","appearance-is-not-safety")])
    put(97,_casts("W08")+[("fixture","one-litre-20-to-30-no-living-tissue")])
    put(98,_casts(*four)+[("fixture","retrieve-dropped-marker")])
    put(99,_casts("W04")+[("release","W04"),("cast","W04"),("fixture","one-then-two-metre-area")])
    put(100,_casts("W04","W05","W03","W02","W01")+
        [("release",wid) for wid in ("W02","W03","W05","W04")])
    return dict(sorted(programs.items()))


FORM_PROGRAMS = _programs()


def form_definition(identifier):
    need(identifier in FORM_PROGRAMS,"Unknown curriculum form.")
    return {"id":identifier,"group":f"G{(int(identifier[1:])-1)//10+1:02}",
            "instructions":FORM_TEXT[identifier],"steps":[list(step) for step in FORM_PROGRAMS[identifier]],
            "source":"curriculum.md","source_class":"campaign_invention","version":1}


CAPACITY_PROGRAMS = {1:_casts("W02","W07","W01"),2:_casts("W03","W04"),
                     3:_casts("W04","W05","W02"),4:_casts("W03","W04","W05"),
                     5:_casts("W03","W04","W05","W02"),
                     6:_casts("W03","W04","W05","W02","W01"),
                     7:_casts("W03","W04","W05","W02")+[("release","W02")]+_casts("W20","W01")}


def execute_pattern(pc, program, *, assessment=False, learning=None):
    """Execute an inert teaching program; return proof and final real Strain.

    All targets are supervised curriculum fixtures or consenting assistants.
    The programme never changes a person's body or an adventure object.
    """
    held,tied = {},{}
    strain = 0 if assessment else pc["strain"]
    spent=peak=slots=elapsed=casts=0
    ledger=[];instructions=[]
    for step in program:
        op = step[0]
        if op in ("cast","fixture_cast"):
            need(pc.get("vitality",1)>0 and not pc.get("magic",{}).get("shielded_by"),
                 "A conscious channeler needs access to the Source before a demonstration.")
            wid = step[1]
            card = prerequisites(pc,wid,require_known=wid != learning)
            need(wid not in held and wid not in tied, "A training effect cannot stack with itself.")
            load = sum(held.values())+sum(tied.values())+card["load"]
            reserved = card["held"] or card["casting_seconds"] > 10
            need(load <= pc["capacity"] and (not reserved or len(held)+1 <= pc["control"]),
                 "The demonstration exceeds existing Load or held slots.")
            need(strain+card["load"] <= 2*pc["capacity"], "Recover explicitly before this demonstration; Strain would exceed its limit.")
            need(op != "fixture_cast" or wid == "W06", "Unknown inert practice variant.")
            strain += card["load"]; spent += card["load"]; casts += 1
            elapsed += 10 if op == "fixture_cast" else card["casting_seconds"]
            peak=max(peak,load);slots=max(slots,len(held)+int(reserved))
            if card["held"]:
                held[wid] = card["load"]
        elif op == "release":
            need(step[1] in held, "Training release refers to an absent weave.")
            del held[step[1]]
        elif op == "release_all":
            held.clear()
        elif op == "tie":
            wid=step[1]
            need(pc["control"] >= 3 and wid in held and WEAVES[wid]["tying"] and
                 len(tied) < pc["control"] and strain+1 <= 2*pc["capacity"], "Illegal training tie.")
            tied[wid]=held.pop(wid);strain+=1;spent+=1;elapsed+=10
        elif op in ("untie","expire"):
            need(step[1] in tied, "Training tie is absent.")
            del tied[step[1]]
            elapsed += 10 if op == "untie" else 0
        elif op == "wait":
            need(integer(step[1],0,3600), "Invalid training interval.")
            elapsed += step[1]
        elif op == "fixture":
            need(type(step[1]) is str, "Unknown fixture instruction.")
        elif op == "instructions":
            need(step[1] in FORM_TEXT,"Unknown taught pattern.")
            instructions.append(FORM_TEXT[step[1]])
        else:
            raise RuleError("Unknown curriculum instruction.")
        ledger.append([list(step),sum(held.values())+sum(tied.values()),strain,elapsed])
    need(not held and not tied, "A training programme left an effect active.")
    need(elapsed <= DAY, "Split the demonstration before eight hours.")
    return {"hash":digest({"program":[list(step) for step in program],"instructions":instructions,
                           "ledger":ledger,"mode":"assessment" if assessment else "training"}),
            "strain":spent,"peak_load":peak,"peak_slots":slots,"seconds":elapsed,"casts":casts}, (pc["strain"] if assessment else strain)


def readiness(state, kind="full"):
    need(kind in ("accepted","technical","full"), "Unknown readiness review.")
    p,r=state["pc"],state["progression"]
    missing=[]
    if kind == "accepted":
        missing += [key for key in N_IDS if _entry(r,key)["status"] != "mastered"]
        if r["service_novice"]["days"] < 10 or r["service_novice"]["benefits"] < 1:
            missing.append("novice_service")
        if p["control"] < 2 or sum(v >= 2 for v in p["flows"].values()) < 3 or p["capacity"] < 5:
            missing.append("accepted_channel_ratings")
        missing += [wid for wid in ACCEPTED_WEAVES if wid not in p["known_weaves"]]
    else:
        missing += [key for key in G_IDS if _entry(r,key)["status"] != "mastered"]
        missing += [wid for wid in REQUIRED if wid not in p["known_weaves"]]
        if p["control"] < 4 or any(v < 2 for v in p["flows"].values()) or p["capacity"] < 8:
            missing.append("technical_channel_ratings")
        if kind == "full":
            service=r["service_accepted"]
            if service["days"] < 20 or len(service["settings"]) < 2 or not service["outside_group"]:
                missing.append("accepted_service")
            if _entry(r,"rehearsal")["status"] != "mastered":
                missing.append("rehearsal")
            if r["service_independent"]["days"] < 10 or r["service_independent"]["benefits"] < 1:
                missing.append("independent_service")
            from .regional import proof_facts
            facts=proof_facts(state)
            prior=r["reviews"]["full"]
            if not any("judgement" in key for key in facts) and not (prior and prior["status"]=="ready"):
                missing.append("independent_judgement")
    return {"kind":kind,"ready":not missing,"missing":missing,
            "bridge_sources":["appointed-tutor","curriculum-library"],"technical_bridge_max_days":5}


def public_view(state):
    r=state["progression"]
    courses={}
    for key in COURSES:
        entry=_entry(r,key)
        if r[key] is None:
            courses[key]={"status":"not_started","required_days":_required_seconds(key)//DAY}
            continue
        days,partial=divmod(entry["seconds"],DAY)
        if entry["status"]=="mastered":
            courses[key]={"days":days,"status":"mastered","evidence_event":entry["evidence"]}
        else:
            courses[key]={"days":days,"partial_seconds":partial,"required_days":_required_seconds(key)//DAY,
                          "status":entry["status"],"source":entry["source"],"evidence_event":entry["evidence"]}
        if key in G_IDS:
            if entry["status"]=="mastered":
                courses[key]["forms_mastered_count"]=10
            else:
                courses[key]["forms_mastered"]=sorted(entry["proofs"])
    return {"courses":courses,"readiness":{kind:readiness(state,kind) for kind in ("accepted","technical","full")},
            "chapter":deepcopy(r["chapter"]),"bridge":deepcopy(r["bridge"]),
            "qualification":deepcopy(r["qualification"])}


def course_detail(state, course_id):
    """Public detail for one course; omitted dashboard fields remain available."""
    need(course_id in COURSES,"Unknown curriculum course.")
    entry=_entry(state["progression"],course_id)
    return {"course_id":course_id,"rules_version":RULES_VERSION,
            "required_seconds":0 if entry["source"]=="creation" else _required_seconds(course_id),
            **deepcopy(entry)}


def available_choices(state):
    """Bounded suggestions; the closed intent API retains every legal option."""
    from . import regional
    p,r,w=state["pc"],state["progression"],state["world"]
    if not w.get("safe") or w.get("active_conflict"):
        return []
    choices=[]
    def offer(label,verb,**fields):
        choices.append({"label":label,"intent":{"verb":verb,**fields}})
    for kind in ("accepted","shawl"):
        test=r[kind+"_test"]
        if test["started"] and not test["completed"]:
            for choice,label in (("explain_limits","Explain your limits; accept ten minutes of later work"),
                                 ("offer_service","Offer one later service day")):
                offer(label,"formal_scene",kind=kind,choice=choice)
            return choices
    if r["qualification"]["shawl"] and p["rank"]!="aes_sedai":
        offer("Defer promotion and preserve your qualification","rank_choice",rank_choice="defer",oaths_choice="defer",ajah="defer")
        for ajah in AJAH:
            offer("Accept the shawl, swear the Oaths and choose "+ajah.title(),"rank_choice",rank_choice="proceed",oaths_choice="swear",ajah=ajah)
        return choices
    if r["chapter"]["stage"]=="boundary":
        offer("Begin the next chapter","begin_chapter")
        if p["control"]<4 and p["channel_points"]>=p["control"]+1:
            offer("Train the next Control rating","spend_points",kind="control",rating="control")
        for flow in FLOWS:
            if p["flows"][flow]<3 and p["channel_points"]>=p["flows"][flow]+1:
                offer("Train the next "+flow.title()+" rating","spend_points",kind="flow",rating=flow)
        return choices
    try:
        _safe(state)
    except RuleError:
        return choices
    for kind in ("accepted","shawl"):
        if not r[kind+"_test"]["started"] and readiness(state,"accepted" if kind=="accepted" else "full")["ready"]:
            offer("Begin the single "+kind+" assessment","formal_start",kind=kind)
    n=r["capacity"]["completed"]+1
    if n<=7 and p["strain"]==0 and p["capacity"]<p["potential"] and (
            n<=5 and r["chapter"]["number"]>=2*n or n>5 and p["rank"]=="aes_sedai"):
        try:
            execute_pattern(p,CAPACITY_PROGRAMS[n]+[("release_all",)])
            _participant(state,CAPACITY_PROGRAMS[n],f"CP{n:02}")
            offer("Demonstrate the next natural capacity proof","capacity_proof",proof_id=f"CP{n:02}")
        except RuleError:
            pass
    for category in (N_IDS,REQUIRED,G_IDS,("rehearsal",)):
        for course in category:
            entry=_entry(r,course)
            if entry["status"]=="mastered":continue
            try:_eligible(state,course)
            except RuleError:continue
            if course in W_IDS and entry["seconds"]==0 and (
                    r["chapter"]["number"]<2 or p["learning_opportunities"]==0):continue
            pending=None
            if course in G_IDS:
                low=(int(course[1:])-1)*10+1
                pending=next((f"F{i:03}" for i in range(low,low+10)
                              if f"F{i:03}" not in entry["proofs"] and entry["seconds"]>=(i-low+1)*DAY),None)
            if pending or course not in G_IDS and entry["seconds"]==_required_seconds(course):
                offer("Demonstrate "+(pending or course),"demonstrate",course_id=course,
                      **({"form_id":pending} if pending else {}))
            else:
                remaining=_required_seconds(course)-entry["seconds"]
                ledger=state['world']['main_activity']
                used=ledger['used_seconds'] if ledger['day']==state['world']['time_seconds']//86400 else 0
                seconds=min(DAY-used,remaining)
                if seconds>0 and regional._activity_fits(state,seconds,'study'):
                    offer("Study "+course,"study",course_id=course,seconds=seconds)
            break
    for kind in ("accepted","technical","full"):
        review=r["reviews"][kind]
        if readiness(state,kind)["ready"] and not (review and review["status"]=="ready"):
            offer("Record the "+kind+" readiness review","review",kind=kind)
    try:
        _chapter_checks(state)
        offer("Complete this chapter and claim its earned award","complete_chapter")
    except RuleError:
        pass
    return choices[:12]


def validate(state):
    p,r=state["pc"],state["progression"]
    need(all(integer(p.get(key)) for key in ("general_points","channel_points")), "Invalid advancement bank.")
    for key in COURSES:
        if r[key] is None:
            continue
        entry=r[key]
        need(type(entry) is dict and set(entry)=={"seconds","status","source","evidence","proofs"} and
             integer(entry["seconds"],0,_required_seconds(key)) and entry["status"] in
             ("not_started","in_progress","mastered","needs_bridge") and type(entry["proofs"]) is dict,
             "Invalid course progress.")
        need(entry["status"] != "mastered" or entry["seconds"] == _required_seconds(key) or
             key in ("W01","W02") and entry["source"]=="creation" and entry["seconds"]==0,
             "Mastery lacks its required study time.")
        ids={key}
        if key in G_IDS:
            start=(int(key[1:])-1)*10+1
            ids={f"F{i:03}" for i in range(start,start+10)}
        need(set(entry["proofs"]) <= ids and (entry["status"]!="mastered" or set(entry["proofs"])==ids),
             "Course mastery evidence is incomplete or belongs to another course.")
        need(all(type(proof) is dict and type(proof.get("hash")) is str and len(proof["hash"])==64 and
                 all(c in "0123456789abcdef" for c in proof["hash"]) and type(proof.get("event")) is str
                 for proof in entry["proofs"].values()),"Invalid compact demonstration evidence.")
    ch=r["chapter"]
    need(integer(ch["number"],1) and integer(ch["completed"]) and
         ch["stage"] in ("active","boundary","post_shawl"), "Invalid chapter state.")
    completed=ch["completed"]
    need(completed == ch["number"]-(ch["stage"]!="boundary") and
         ch["gp_awarded"] == 4*min(completed,11)+4*max(0,completed-12) and
         ch["cp_awarded"] == 2*min(completed,10)+2*max(0,completed-12) and
         ch["learning_awarded"] == 2*completed and p["level"]==min(12,completed+1),
         "Chapter award totals differ from completed chapters.")
    used=sum(r[wid] is not None and _entry(r,wid)["source"]!="creation" for wid in W_IDS)
    need(p["learning_opportunities"] == ch["learning_awarded"]-used,
         "Weave learning opportunities differ from completed chapter awards.")
    trained=sum(range(2,p["control"]+1))+sum(sum(range(2,value+1)) for value in p["flows"].values())-2
    need(r["channel_spent"]==trained,"Channel Point spending differs from trained ratings.")
    need(ch["gp_awarded"] == r["general_spent"]+p["general_points"] and
         ch["cp_awarded"] == r["channel_spent"]+p["channel_points"], "Advancement accounting differs.")
    need(integer(r["capacity"]["completed"],0,7) and p["capacity"] == 3+r["capacity"]["completed"] and
         p["capacity"] <= p["potential"], "Capacity proof accounting differs.")
    for track in ("novice","accepted","independent"):
        item=r["service_"+track]
        need(integer(item["seconds"]) and (item["days"],item["partial_seconds"]) == divmod(item["seconds"],DAY),
             "Service time accounting differs.")
        for credit in item["task_credit"].values():
            need(integer(credit["seconds"]) and credit["days"] == credit["seconds"]//DAY and
                 integer(credit["consumed_days"],0,credit["days"]), "Invalid service benefit watermark.")


def _proof(entry, identifier, proof, action_id):
    entry["proofs"][identifier]={**proof,"event":action_id}
    entry["evidence"]=action_id


def _chapter_checks(state):
    from .regional import chapter_proofs, proof_facts
    r=state["progression"];number=r["chapter"]["number"]
    contract=chapter_proofs(number)
    facts=proof_facts(state)
    requirements = contract["proof_ids"] if type(contract) is dict else [item["id"] for item in contract]
    need(3 <= len(requirements) <= 4, "A chapter needs three or four published proofs.")
    need(all(key in facts and facts[key] for key in requirements), "Complete the published chapter proofs through actual authored actions.")
    if number in (2,4,6,8,10):
        need(r["capacity"]["completed"] >= number//2, "Complete this chapter's legal capacity proof.")
    if number == 4:
        need(readiness(state,"accepted")["ready"], "Accepted readiness is incomplete.")
    if number == 5:
        need(r["accepted_test"]["completed"], "Complete the single Accepted test.")
    if number == 10:
        need(readiness(state,"technical")["ready"], "Technical readiness is incomplete.")
    if number == 11:
        need(readiness(state,"full")["ready"], "Full readiness is incomplete.")
    if number == 12:
        need(r["shawl_test"]["completed"], "Complete the single formal shawl test.")
    return requirements


def resolve(upfront,intent,action_id,*,advance,check,harm):
    """Mutate only the compiler's private copy; no save, network, or random draw."""
    need(handles(intent), "Unsupported progression action.")
    before_action(upfront,intent)
    p,r,w=upfront["pc"],upfront["progression"],upfront["world"]
    verb=intent["verb"]; goal=method=""
    _safe(upfront,no_work=verb not in ("review","rank_choice","complete_chapter","begin_chapter","spend_points"))
    if verb == "study":
        closed(intent,("course_id",),("seconds","source"))
        course=intent["course_id"];source=intent.get("source","curriculum-library")
        need(course in COURSES,"Unknown curriculum course.")
        _source(upfront,source);_eligible(upfront,course)
        need(not p["embraced"],"Release the Source before a study block.")
        entry=_entry(r,course);seconds=intent.get("seconds",DAY)
        need(integer(seconds,1,DAY) and entry["seconds"]+seconds <= _required_seconds(course),
             "Study exceeds the course's remaining time.")
        need(entry["status"] != "mastered","This course is already mastered.")
        if course in W_IDS and entry["seconds"] == 0:
            need(r["chapter"]["stage"] == "active" and r["chapter"]["number"] >= 2 and
                 p["learning_opportunities"] > 0,"Begin the following chapter with an earned learning opportunity.")
            p["learning_opportunities"]-=1
        result=_activity(upfront,seconds,"study",advance)
        credited=result["credited_seconds"]
        need(integer(credited,1,seconds),"No study interval was available.")
        entry["seconds"]+=credited;entry["source"]=source;entry["status"]="in_progress";entry["evidence"]=action_id
        if entry["seconds"] == _required_seconds(course):
            entry["status"]="needs_bridge"
        r[course]=entry
        if course in N_IDS:
            p["study_progress"][course]=entry["seconds"]
        goal=f"Retain {credited} exact study seconds for {course}; guided evidence is separate."
    elif verb == "demonstrate":
        closed(intent,("course_id",),("form_id","source","method"))
        course=intent["course_id"];source=intent.get("source","curriculum-library")
        need(intent.get("method","guided") in ("guided","showcase"),"Choose guided or showcase demonstration.")
        need(course in COURSES,"Unknown demonstration course.")
        _source(upfront,source);_eligible(upfront,course)
        entry=_entry(r,course)
        need(entry["status"] != "mastered","Mastery is retained; no repeated technical gate is needed.")
        if course in G_IDS:
            identifier=intent.get("form_id")
            low=(int(course[1:])-1)*10+1
            need(identifier in [f"F{i:03}" for i in range(low,low+10)],"This form belongs to another group.")
            need(identifier not in entry["proofs"],"This form already has retained evidence.")
            need(entry["seconds"] >= (int(identifier[1:])-low+1)*DAY,"Complete this form's study day before its demonstration.")
            program=FORM_PROGRAMS[identifier]
            reuse=identifier=="F090" and r["capacity"]["completed"]==5 and r["capacity"]["last_proof"] is not None
            if reuse:
                proof={"hash":digest({"form":identifier,"source_event":r["capacity"]["last_event"],
                                      "source_proof":r["capacity"]["last_proof"]["hash"]}),
                       "source_event":r["capacity"]["last_event"],"seconds":0,"strain":0,
                       "peak_load":7,"peak_slots":4,"casts":0}
                participant=None;strain=p["strain"]
            else:
                participant=_participant(upfront,program,identifier)
                proof,strain=execute_pattern(p,program)
        else:
            need(entry["seconds"] == _required_seconds(course),"Complete the stated study days before demonstration.")
            identifier=course
            program=[("fixture",course+"-guided-proof"),("release_all",)]
            if course in W_IDS:
                program=[("fixture_cast" if course=="W06" else "cast",course),("release_all",)]
            elif course=="N01":
                program=_casts("W02")+[("release_all",)]
            elif course=="rehearsal":
                program=CAPACITY_PROGRAMS[5]+[("release_all",)]
            participant=_participant(upfront,program,identifier)
            proof,strain=execute_pattern(p,program,learning=course if course in W_IDS else None)
        if participant:
            proof["participant"]=participant
        setup=10 if proof["casts"] and not p["embraced"] else 0
        proof["setup_seconds"]=setup
        advance(upfront,0 if proof.get("source_event") else max(10,proof["seconds"])+setup)
        p["strain"]=strain;p["embraced"]=False
        _proof(entry,identifier,proof,action_id)
        r[course]=entry
        entry["source"]=source
        if entry["seconds"] == _required_seconds(course) and (course not in G_IDS or len(entry["proofs"])==10):
            entry["status"]="mastered"
            if course in W_IDS and course not in p["known_weaves"]:
                p["known_weaves"].append(course)
        goal=f"Complete the guided {identifier} pattern, retaining its exact cost and evidence."
    elif verb == "capacity_proof":
        closed(intent,("proof_id",),("source",))
        source=intent.get("source","appointed-tutor");_source(upfront,source)
        n=r["capacity"]["completed"]+1
        need(intent["proof_id"] == f"CP{n:02}" and n <= 7,"Complete capacity proofs in their published order.")
        need(p["strain"] == 0,"Start a capacity proof rested with zero Strain.")
        need((n<=5 and r["chapter"]["number"] >= 2*n) or (n>5 and p["rank"]=="aes_sedai"),
             "This capacity proof is not available yet.")
        need(p["capacity"]+1 <= p["potential"],"No further natural capacity proof is available.")
        program=CAPACITY_PROGRAMS[n]+[("release_all",)]
        participant=_participant(upfront,program,intent["proof_id"])
        proof,strain=execute_pattern(p,program)
        if participant:
            proof["participant"]=participant
        setup=10 if not p["embraced"] else 0
        proof["setup_seconds"]=setup
        advance(upfront,proof["seconds"]+setup);p["strain"]=strain;p["embraced"]=False;p["capacity"]+=1
        r["capacity"]={"completed":n,"last_event":action_id,"last_proof":proof}
        goal=f"Demonstrate capacity {p['capacity']-1} legally and earn capacity {p['capacity']}."
    elif verb == "service":
        closed(intent,("task_id",),("seconds","method"))
        from .regional import service_task, complete_service
        task=service_task(intent["task_id"],upfront)
        need(w["region"]["location_id"] == task["location_id"],"Travel to the service beneficiary before crediting work.")
        track=task["track"];entry=r["service_"+track]
        method=intent.get("method",task["methods"][0])
        need(method in task["methods"],"Choose one of the service task's published methods.")
        seconds=intent.get("seconds",DAY);need(integer(seconds,1,DAY),"Invalid service duration.")
        result=_activity(upfront,seconds,"service",advance);credited=result["credited_seconds"]
        need(integer(credited,1,seconds),"No service interval was available.")
        credit=entry["task_credit"].setdefault(task["task_id"],{"seconds":0,"days":0,"consumed_days":0,"last_event":None})
        credit["seconds"]+=credited;credit["days"]=credit["seconds"]//DAY;credit["last_event"]=action_id
        entry["seconds"]+=credited;entry["days"],entry["partial_seconds"]=divmod(entry["seconds"],DAY)
        entry["status"]="in_progress";entry["last_event"]=action_id
        days=credit["days"]-credit["consumed_days"]
        if days:
            complete_service(upfront,task["task_id"],action_id,days=days)
            r["obligations"]["service_days"]=max(0,r["obligations"]["service_days"]-days)
        goal=f"Perform {credited} seconds of {task['description']} using {method}."
    elif verb == "review":
        closed(intent,("kind",))
        result=readiness(upfront,intent["kind"])
        status="ready" if result["ready"] else "needs bridge"
        r["reviews"][intent["kind"]]={"status":status,"missing":result["missing"][:1],"event":action_id}
        goal=f"Review {intent['kind']} readiness: {status}."
    elif verb == "start_bridge":
        closed(intent,("course_id",),("source",))
        course=intent["course_id"];source=intent.get("source","appointed-tutor")
        need(course == "channel_reassignment" or course in COURSES and
             _entry(r,course)["seconds"] == _required_seconds(course) and _entry(r,course)["status"] != "mastered",
             "A technical bridge addresses an already studied technique; retain unfinished core study.")
        need(r["bridge"]["status"] in ("none","complete"),"Finish the existing bounded bridge.")
        _source(upfront,source)
        r["bridge"]={"target":course,"seconds":0,"status":"in_progress","source":source,"evidence":action_id}
        goal=f"Start a bridge for {course}: at most five study days, then a guided demonstration."
    elif verb == "finish_bridge":
        closed(intent,(),("seconds",))
        bridge=r["bridge"];need(bridge["status"]=="in_progress","No bridge is in progress.")
        seconds=intent.get("seconds",DAY)
        need(integer(seconds,1,DAY) and bridge["seconds"]+seconds <= 5*DAY,"Bridge study exceeds its five-day bound.")
        result=_activity(upfront,seconds,"study",advance)
        bridge["seconds"]+=result["credited_seconds"];bridge["evidence"]=action_id
        if bridge["seconds"] == 5*DAY:
            bridge["status"]="complete"
        goal="Retain bridge instruction; the same guided demonstration remains available without random failure."
    elif verb == "spend_points":
        closed(intent,("kind","rating"))
        need(r["chapter"]["stage"]=="boundary","Spend banked points at a safe chapter boundary.")
        kind,name=intent["kind"],intent["rating"]
        if kind in ("skill","attribute"):
            ratings=p["skills"] if kind=="skill" else p["attributes"]
            need(name in (SKILLS if kind=="skill" else ATTRIBUTES),"Unknown rating.")
            target=ratings[name]+1;cap=4 if kind=="skill" else 3;cost=target*(3 if kind=="attribute" else 1)
            need(target<=cap and p["general_points"]>=cost,"Insufficient General Points or rating already capped.")
            ratings[name]=target;p["general_points"]-=cost;r["general_spent"]+=cost
            if kind=="attribute" and name=="body":
                p["max_vitality"]=6+2*target
        else:
            need(kind in ("control","flow"),"Unknown advancement kind.")
            need(kind=="control" and name=="control" or kind=="flow" and name in FLOWS,"Unknown channel rating.")
            target=(p["control"] if kind=="control" else p["flows"][name])+1
            need(target<=(4 if kind=="control" else 3) and p["channel_points"]>=target,"Insufficient Channel Points or rating already capped.")
            if kind=="control":p["control"]=target
            else:p["flows"][name]=target
            p["channel_points"]-=target;r["channel_spent"]+=target
        goal=f"Buy the next {name} rating with earned {kind} points."
    elif verb == "reassign_channel":
        closed(intent,("control","flows"))
        need(r["bridge"]["status"]=="complete" and r["bridge"]["seconds"]==5*DAY,
             "Complete one five-day bridge before free Channel Point reassignment.")
        control,flows=intent["control"],intent["flows"]
        need(integer(control,1,4) and type(flows) is dict and set(flows)==set(FLOWS) and
             all(integer(value,1,3) for value in flows.values()),"Invalid reassignment ratings.")
        # Genesis supplies one free Flow-2. Preserve that entitlement without
        # turning it into banked currency; require at least one Flow at two.
        need(any(value>=2 for value in flows.values()),"Retain the free starting Flow training.")
        cost=sum(range(2,control+1))+sum(sum(range(2,value+1)) for value in flows.values())-2
        need(cost <= r["chapter"]["cp_awarded"],"Reassignment cannot spend unearned Channel Points.")
        p["control"]=control;p["flows"]=deepcopy(flows);p["channel_points"]=r["chapter"]["cp_awarded"]-cost;r["channel_spent"]=cost
        r["bridge"]["status"]="none"
        goal="Reassign earned Channel Points without losing learned weave knowledge."
    elif verb == "complete_chapter":
        closed(intent,())
        need(r["chapter"]["stage"]=="active","This chapter award is already resolved.")
        _chapter_checks(upfront)
        ch=r["chapter"];n=ch["number"]
        need(n<=12 or p["rank"]=="aes_sedai","Post-shawl chapters require earned promotion.")
        gp=4 if n<=11 or n>12 else 0;cp=2 if n<=10 or n>12 else 0;learning=2
        p["general_points"]+=gp;p["channel_points"]+=cp;p["learning_opportunities"]+=learning
        p["level"]=min(12,p["level"]+int(n<=11))
        ch.update(completed=n,stage="boundary",last_award_event=action_id,
                  gp_awarded=ch["gp_awarded"]+gp,cp_awarded=ch["cp_awarded"]+cp,
                  learning_awarded=ch["learning_awarded"]+learning)
        if n == 11:
            r["reviews"]["full"]={"status":"ready","missing":[],"event":action_id}
        goal=f"Complete chapter {n} once: {gp} General Points, {cp} Channel Points, two learning opportunities."
    elif verb == "begin_chapter":
        closed(intent,())
        ch=r["chapter"];need(ch["stage"]=="boundary","Complete the current chapter first.")
        need(ch["number"]<12 or p["rank"]=="aes_sedai","Promotion choices can wait without repeating the formal test.")
        ch["number"]+=1;ch["stage"]="active"
        from .regional import begin_chapter
        begin_chapter(upfront,ch["number"],action_id)
        goal=f"Publish chapter {ch['number']}'s proof conditions and alternative methods."
    elif verb == "formal_start":
        closed(intent,("kind",))
        kind=intent["kind"];need(kind in ("accepted","shawl"),"Unknown formal test.")
        test=r[kind+"_test"]
        need(not test["started"],"A formal test is a single event; resume it instead of restarting.")
        need(readiness(upfront,"accepted" if kind=="accepted" else "full")["ready"],"Complete published readiness first.")
        need(p["strain"]==0 and p["vitality"]==p["max_vitality"] and p["wounds"]==0,"Begin the formal test rested and unwounded.")
        duration=1800 if kind=="accepted" else 2400+sum(
            execute_pattern(p,program,assessment=True)[0]["seconds"] for program in FORM_PROGRAMS.values())
        deadline=w.get("next_event_second")
        need(deadline is None or w["time_seconds"]+duration<deadline,
             "Resolve the pending world event before starting this protected assessment interval.")
        test["started"]=True
        goal=f"Begin the single {kind} test in protected assessment mode."
    elif verb == "formal_scene":
        closed(intent,("kind","choice"))
        kind=intent["kind"];need(kind in ("accepted","shawl"),"Unknown formal test.")
        test=r[kind+"_test"];need(test["started"] and not test["completed"],"No unfinished formal test is active.")
        need(intent["choice"] in ("explain_limits","offer_service"),"Choose a published response: explain limits or offer later service.")
        if intent["choice"]=="explain_limits":test["deferred_work_seconds"]+=600
        else:test["service_obligations"]+=1
        # The supervised scene includes setup and transitions. Its inert forms
        # use assessment resources, never expedition Strain or bodily effects.
        seconds=600
        if kind=="shawl":
            first=test["form_count"]+1;proofs=[]
            for number in range(first,min(first+25,101)):
                identifier=f"F{number:03}"
                proof,_=execute_pattern(p,FORM_PROGRAMS[identifier],assessment=True)
                proofs.append({"id":identifier,**proof})
                seconds+=proof["seconds"]
            need(len(proofs)==25,"The ordered formal sequence is complete.")
            test["form_count"]+=25
            test["form_hash"]=digest({"previous":test["form_hash"],"forms":proofs,"event":action_id})
        advance(upfront,seconds)
        test["scene"]+=1;test["evidence"].append(action_id)
        if test["scene"]==(3 if kind=="accepted" else 4):
            test["completed"]=True;r["qualification"][kind]=True
            p["pending_work_seconds"]+=test["deferred_work_seconds"]
            r["obligations"]["service_days"]+=test["service_obligations"]
            r["obligations"]["source_events"].append(action_id)
            if kind=="accepted":p["rank"]="accepted"
        goal=f"Complete {kind} assessment scene {test['scene']}; technical completion is protected."
    elif verb == "rank_choice":
        closed(intent,("rank_choice","oaths_choice","ajah"))
        need(r["qualification"]["shawl"],"Complete the formal shawl test before choosing promotion.")
        need(intent["rank_choice"] in ("proceed","defer") and intent["oaths_choice"] in ("swear","defer") and
             intent["ajah"] in (*AJAH,"defer"),"Choose explicit rank, Oaths and Ajah options.")
        need(p["rank"]!="aes_sedai","Promotion choices are complete; this action cannot rescind sworn Oaths or change Ajah.")
        r["qualification"].update(rank_choice=intent["rank_choice"],oaths_choice=intent["oaths_choice"],ajah_choice=intent["ajah"])
        if intent["rank_choice"]=="proceed" and intent["oaths_choice"]=="swear" and intent["ajah"] in AJAH:
            p["rank"]="aes_sedai";p["oaths_active"]=True;p["ajah"]=intent["ajah"]
            p["oaths_source_event"]=action_id
        goal="Record explicit promotion choices; deferral preserves every earned qualification."
    validate(upfront)
    return None,None,goal,method or verb,None
