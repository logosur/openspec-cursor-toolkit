# Spec Delta — skill-routing

## Purpose

Defines what a skill description must say so that agents route requests to the right skill, and how a duplicate skill is taken out of routing without breaking the name that projects and other skills already use.

## ADDED Requirements

### Requirement: Routing applies to model-invocable skills only
The routing contract SHALL apply to every skill whose frontmatter does not set `disable-model-invocation: true`. Skills that set it are reached only by explicit command and SHALL be exempt from the trigger-clause and collision rules, but not from frontmatter validity or parity.

#### Scenario: Command wrapper is exempt
- **WHEN** `opsx-apply/SKILL.md` sets `disable-model-invocation: true` and its description has no trigger clause
- **THEN** the validator reports no routing finding for it

### Requirement: Description carries a trigger clause
A model-invocable skill's `description` SHALL contain at least one trigger clause introduced by `Use when`, `Use on`, `Auto-invoke on` or `Triggers on` (case-insensitive). A description without one SHALL be an `ERROR`.

#### Scenario: Purpose-only description
- **WHEN** `00-openspec-orchestrator` is described as "OpenSpec orchestration layer"
- **THEN** the validator reports an `ERROR` for both trees that contain the skill

#### Scenario: Description with trigger clause
- **WHEN** a description reads "Hydrates weak OpenSpec proposals until every requirement is testable. Use when a proposal is vague, untestable or missing scenarios, …"
- **THEN** no trigger-clause finding is reported

### Requirement: Description length budget
A skill `description` SHALL be at most 1024 characters.

#### Scenario: Over-long description
- **WHEN** a description has 1100 characters
- **THEN** the validator reports an `ERROR` with the measured length

### Requirement: No colliding descriptions
Within each tree, no two model-invocable skills SHALL have descriptions whose similarity is at or above the collision threshold (0.50); a pair at or above the warning threshold (0.30) SHALL be reported as `WARN`. Similarity is the cosine of TF-IDF vectors computed over the descriptions of that tree's model-invocable skills, with a fixed stop-word list, so the score is reproducible run to run.

#### Scenario: Near-duplicate pair
- **WHEN** `20-hydrate-spec` and `20-openspec-hydrate-spec` are both model-invocable with today's descriptions (measured 0.57)
- **THEN** the validator reports an `ERROR` naming the pair and the score

#### Scenario: Related but distinct pair
- **WHEN** two skills score 0.35
- **THEN** the validator reports a `WARN` and exits `0` if nothing else fails

#### Scenario: Deterministic score
- **WHEN** the validator runs twice on the same catalog
- **THEN** both runs report identical scores

### Requirement: Descriptions say what and when without inventing
A rewritten description SHALL state what the skill does and when to use it, SHALL draw its trigger vocabulary (including Spanish phrases) from text already present in the repository — `README.md`, the skills READMEs, command files, `CLAUDE.md` or the skill body — and SHALL NOT summarize the skill's step sequence or name commands, files or behaviours the skill does not contain.

#### Scenario: Trigger phrase traceable to the repo
- **WHEN** a rewritten description includes the phrase "hidrata la spec"
- **THEN** that phrase, or the behaviour it names, appears in the skill body or in one of the listed documents

#### Scenario: Step summary rejected at review
- **WHEN** a description lists the skill's phases in order ("explore, then propose, then hydrate, then verify")
- **THEN** the review rejects it and asks for the trigger condition instead

### Requirement: Rule descriptions follow homonym skills
When a skill description is rewritten, every Cursor rule with the same base name whose `description` equalled that skill's description before the rewrite SHALL receive the same new description.

#### Scenario: Equal before, equal after
- **WHEN** `00-openspec-master.mdc` and `00-openspec-master/SKILL.md` share a description and the skill's is rewritten
- **THEN** the rule carries the identical new description

### Requirement: Deprecated alias keeps the name and leaves the router
A duplicate skill SHALL be retired by turning it into a deprecated alias, not by deleting it: the folder and `name` remain; the frontmatter sets `disable-model-invocation: true`; the `description` starts with `Deprecated alias of` followed by the canonical skill name; and the body is a short pointer to the canonical skill with no workflow content of its own. Its homonym Cursor rule, if any, SHALL become the same pointer with the same description.

#### Scenario: Alias resolves to canonical
- **WHEN** a consumer project or another skill references `20-hydrate-spec`
- **THEN** the file still exists and directs the agent to `20-openspec-hydrate-spec`

#### Scenario: Alias does not compete
- **WHEN** the routing rules run after consolidation
- **THEN** `20-hydrate-spec` and `openspec-anti-hallucination` are exempt as non-invocable and no collision is reported for their former pairs

### Requirement: Canonical members of the duplicate pairs
`20-openspec-hydrate-spec` SHALL be canonical over `20-hydrate-spec`, and `30-openspec-anti-hallucination` canonical over `openspec-anti-hallucination`, because the numbered names belong to the `00-`..`40-` series the repository declares and are the names other skills and rules reference.

#### Scenario: References point to canonical names
- **WHEN** a skill or rule body references either concept after this change
- **THEN** it uses the numbered canonical name, and the only remaining mentions of the alias names are the alias files themselves, index tables and the exceptions or deprecation notes

### Requirement: Validator flags an alias that carries content
The validator SHALL report an `ERROR` for a skill whose description starts with `Deprecated alias of` when it is model-invocable, names a skill that does not exist, or has a body longer than 15 non-blank lines.

#### Scenario: Alias regains a workflow
- **WHEN** someone pastes the full hydrate workflow back into `20-hydrate-spec/SKILL.md`
- **THEN** the validator reports an `ERROR` for the alias body length

#### Scenario: Alias to a missing skill
- **WHEN** an alias description names `20-openspec-hydrate-specs` (typo)
- **THEN** the validator reports an `ERROR` that the canonical skill does not exist
