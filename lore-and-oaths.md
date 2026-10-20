# Lore and Oaths module

Status: researched planning module, 17 October 2026. No play test has been done.

Use the [main plan](plan.md) and [mechanics](mechanics.md) for the campaign contract. Source identifiers below refer to the [source register](source-register.md).

## 1. What the evidence establishes

Publisher-hosted passages support the basic test structure and the selected Oaths wording. They do not verify every institutional practice in 950 NE.

| Claim | Evidence | Status and limit |
|---|---|---|
| The Accepted test uses a device with three arches. | S03, quoted description from *The Great Hunt*, chapter 23. | `canon / verified` for the physical structure. |
| The formal shawl test requires one hundred ordered weaves and composure. | S02, quoted instructions from *New Spring*, chapter 9. | `canon / verified` for these requirements. |
| The raising ceremony includes the Oaths. | S01, quoted passage from *New Spring*, chapter 11. | `canon / verified` for the shown ceremony. |
| The campaign uses these institutions in 950 NE. | Earlier plan plus the sources above. | `inference / provisional` for the date extension. |
| Ordinary failure preserves the earned route. | Mechanics, rank rules. | `house_rule`. It is a deliberate protection. |
| All hundred game exercises reproduce published canonical forms. | No supporting source. | Reject this claim. Mark new exercises as `invention`. |

S02 also gives a sequence of signs and instructions. Use that structure as background. Do not reproduce the book character's personal scenes.

The three-arch test and the hundred-weave test are different events. Do not use the same curriculum or random-failure procedure for both.

The quoted passages support selected details. Editorial summaries on the same pages remain secondary evidence. Reader comments are excluded.

## 2. The 950 NE boundary

Keep the selected start at 950 NE. Use an original novice, teachers, allies, and local problems.

S04 verifies a Tower arrival date of 998 NE within the main-series chronology. S07 separately places the opening story in that year.

The 48-year separation follows if S07's opening date is accepted. That exact opening-date claim remains provisional here because its primary locator was not verified.

This evidence supports the chosen earlier window. It does not validate the government, personnel, calendar, or available weave knowledge for every year.

Do not name the Amyrlin, senior officeholders, or national rulers until their terms are checked. Use an office title when a name is unnecessary.

Keep later rediscoveries, political changes, and character outcomes outside the play packet. A fact known to the reader is not automatically known in 950 NE.

Check admission age before final character creation. The adult-character choice does not establish that the Tower accepts a novice of every adult age.

Do not copy the exceptional pace of a book protagonist. Use the campaign's training periods, readiness proofs, and agreed time skips.

## 3. Selected Oaths basis

Use the *New Spring*, chapter 11 passage located in S01 as the wording basis. Do not silently combine it with another version.

Its restrictions concern false spoken statements, weapons made for human killing, and weapon use of the One Power. Its third restriction names Shadowspawn and extreme defence of the speaker, her Warder, or another sister.

The located third restriction does not list Darkfriends separately. S11 reports a broader exception. Do not treat the omission as a proven historical change.

For this campaign, use the located prequel variant. An accusation of being a Darkfriend does not create a separate combat exception.

These summaries are not replacement oath text. Keep the exact source locator in the rules manifest. Do not substitute television wording.

Apply the module before the first relevant decision by an oath-bound teacher. Apply it to the player character after her Oaths event.

Novices and Accepted do not acquire these mechanical restrictions merely from their rank. Tower rules and consequences for their actions remain separate.

The preceding rank applicability is a campaign default pending full institutional verification. Set each character's `oaths_active` field explicitly. Do not infer it from a displayed title alone.

## 4. Ruling procedure

These procedures are house rules for consistent play. They do not claim that the books define an executable decision algorithm.

1. Load the actor's Oaths status and module version.
2. Load only that actor's relevant knowledge and beliefs.
3. Record the intended statement or action before resolution.
4. Identify each applicable restriction.
5. Record the intended use, target, and relevant danger.
6. Ask for the player's intent when the player's meaning is unclear.
7. Return `ALLOW`, `BLOCK`, or `CLARIFY`, with a rule identifier.
8. Explain a block before spending time or resources.
9. Permit a revised action before dice or consequences.
10. Save the decision and its evidence with the action.

The GM must not create a convenient belief after the action. A persuasion roll cannot alter an oath restriction.

NPC beliefs need observation, testimony, or inference identifiers. False testimony can produce a mistaken belief. The GM still records the testimony's actual status separately.

Do not reveal secret evidence when explaining a ruling. Give the player the reason that the character can know.

An unfamiliar case returns `CLARIFY`. Use an existing safe alternative while resolving the rule. Do not charge a penalty for missing rules.

## 5. Original adjudication cases

These fixtures use original people and situations. They are proposed house defaults, not claims that an identical case appears in the books.

| ID | Situation | Result | Basis and control |
|---|---|---|---|
| O01 | A teacher repeats a wrong date from a record she trusts. | `ALLOW`. | Honest-error default. Preserve the belief's source; correct it when contrary evidence arrives. |
| O02 | A teacher witnessed the departure, but intends to deny it. | `BLOCK`. | Direct application of the first restriction. Load the witnessed fact. |
| O03 | A teacher truthfully says the archive closes at dusk, while omitting another entrance. | `ALLOW`. | Limited-truth default. Do not declare the omission a false spoken statement. |
| O04 | A teacher intends to promise an action she has already decided to refuse. | `BLOCK`. | False-promise default. Do not replace her recorded intent after the ruling. |
| O05 | A sister uses the Power to forge a blade for a planned human killing. | `BLOCK`. | Weapon-making restriction; record intended use. |
| O06 | A sister makes a pruning tool for ordinary garden work. | `ALLOW`. | Tool-purpose default. Its possible misuse alone does not make the stated task weapon-making. |
| O07 | An attacker creates an immediate lethal danger to the sister. | `ALLOW` an otherwise legal defensive weave. | Extreme-defence default. Record the perceived danger and why it qualifies. |
| O08 | An insult is followed by a proposed fire attack. | `BLOCK`. | No qualifying exception in the declared facts. Social hostility alone is insufficient. |
| O09 | A sister holds an uninjured person with Air to prevent flight. | `ALLOW` under the restraint default. | The action must not crush, suffocate, injure, or expose the target to immediate harm. |
| O10 | The same restraint is intended to cause injury or make a target helpless for an attack. | Reassess as weapon use. | A harmless weave name cannot hide its intended harmful use. |
| O11 | A novice proposes a combat weave. | Do not apply Oaths she has not taken. | Check learned knowledge, mechanics, safety, and institutional consequences separately. |
| O12 | A teacher helps with a circle intended to perform a prohibited act. | `BLOCK` her participation under the campaign default. | Linking must not provide an automatic bypass. Exact canonical edge cases remain unresolved. |

O01, O03–O04, O06–O07, O09–O10, and O12 need further source review for their exact boundaries. Their deterministic game results remain explicitly labelled house rules.

O07 also covers the named protected people in the adopted wording. It does not create a general lethal-force exception for every endangered bystander.

A sister can still offer a barrier, evacuation, warning, healing, negotiation, or another permitted intervention. Check the actual effect and intended use.

For this module, weapon-making concerns manufactured items. Check a direct attack weave under the weapon-use restriction. Check a persistent weapon construct under both restrictions.

This distinction is a house default. Mundane manufacture is not an automatic exception. An unclear object or effect returns `CLARIFY`.

The source does not make every nonlethal act permissible. Pain, coercion, restraint, tools, and indirect harm need purpose-specific rulings.

The literal meaning must be credible in context. The GM must not invent an obscure definition solely to permit a desired outcome.

## 6. Record format and test expectations

Each ruling needs these fields:

| Field | Content |
|---|---|
| `oath_ruling_id` | Stable identity and module version. |
| `actor_id` | The person whose action is resolved. |
| `oaths_active` | Status before this action, with source event. |
| `statement_or_action` | The exact proposed meaning or effect. |
| `belief_ids` | Relevant beliefs available to the actor. |
| `intent` | Intent established before resolution. |
| `danger_basis` | Perceived threat, protected person, and evidence. |
| `rule_ids` | Applicable restrictions and house defaults. |
| `result` | `ALLOW`, `BLOCK`, or `CLARIFY`. |
| `public_reason` | A short explanation without secret facts. |

Run every case for both an NPC and a qualifying player character. Change only the actor's available belief in the honest-error variant.

A hidden world fact must not change an actor's ruling before the actor can know it. A changed intention requires a new proposed action.

A blocked action spends no Strain or Supply. A permitted action still pays ordinary costs and can fail for unrelated reasons.

No result is marked tested. Implement these fixtures after the rules module and controller interface exist.

## 7. Magic and curriculum controls

All numerical ratings, costs, ranges, load limits, and recovery rates are house rules. Campaign Potential 8–10 is not the Companion's strength scale.

A canonical effect does not establish a canonical combination of flows, training date, or availability to a novice. Check these claims separately.

Give every catalogue entry a lore class, certainty, source locator, date scope, and permitted disclosure. Record invented names and effects as inventions.

Keep special Talents, overchanneling, severing, large circles, and exceptional devices unavailable until their modules are defined and reviewed.

Review the optional small-circle, Shield, and angreal modules before use. Their numerical completeness does not establish their fidelity to the setting.

Do not infer a universal Healing rule from one recovery example. The initial effect and recovery limits remain campaign rules.

Formal test exercises can be original constructions. They need stable identifiers, defined effects, and assessment evidence. Do not label an invented exercise as a recovered book form.

## 8. Remaining evidence work

Resolve the exact 950 NE institutional date scope before claiming historical verification. Verify admission rules and officeholders only when the campaign needs them.

Compare the adopted Oaths passage against a lawful copy of the novel. Record the edition and page locator without copying the full passage.

Resolve variant wording before expanding exceptions. Check belief, indirect harm, circle participation, and restraint against primary passages or authenticated author answers.

Keep the source pages in GM research. Give the narrator only approved claim summaries. Never load comments or whole-series character entries into play context.

