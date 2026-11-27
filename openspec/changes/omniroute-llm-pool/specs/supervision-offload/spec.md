# Spec Delta — supervision-offload

## Purpose

Defines what a supervisor and its child sessions hand to the pool, the evidence needed before the watcher's triage is built at all, and the rules that keep a wrong pool answer from stalling or damaging work.

## ADDED Requirements

### Requirement: The pool is optional for supervision
Supervision SHALL work unchanged when the `llm-pool` module is not installed, the pool is stopped or at level 0, the project is not enabled or is paused, or the gateway is unreachable. Every offload point SHALL have the behaviour it had before as its fallback. The supervision manifest SHALL declare the pool's command as a piece another module provides.

#### Scenario: Module not installed
- **WHEN** the supervision module runs on a machine without `llm-pool`
- **THEN** the watcher wakes the supervisor for every event exactly as before, prints nothing about the pool, and the supervision self-test passes unchanged

### Requirement: A simulator replays recorded wakes before any triage is built
Before any triage code is written, a simulator SHALL read recorded supervisor wakes from the transcripts and classify each soft wake. The supervisor was needed when, in the turn that wake started, it messaged, started, stopped or archived a session, ran a git command that writes, deployed, called a panel or queued a question. A wake whose end cannot be found SHALL be unclassified and left out of every rate.

#### Scenario: A known transcript
- **WHEN** the simulator runs on a seeded transcript whose soft, hard, needed, routine and unclassified wakes are known
- **THEN** it reports the known counts of each

#### Scenario: A tick that only checks
- **WHEN** after a soft wake the supervisor takes its census, reads two files and re-arms the watcher
- **THEN** that wake counts as not needed

### Requirement: A watcher that was stopped is a hard wake
A recorded wake whose notice says the watcher was stopped, and whose output holds no event, SHALL count as hard: the watcher never finished, so there was nothing to triage. A wake with no output whose watcher did finish SHALL stay unclassified.

#### Scenario: The watcher died with the app
- **WHEN** the notice of a wake says "stopped" and no event line can be found for it
- **THEN** the wake counts as hard, is not in the unclassified share, and the fixed rule does not sleep it

#### Scenario: A finished watcher with no output
- **WHEN** the notice of a wake says "completed" and no event line can be found for it
- **THEN** the wake is unclassified and left out of every rate

### Requirement: The watcher keeps the events of each wake
Before it exits, the watcher SHALL append the event lines of that wake, with the lock's owner and the times the wait started and ended, to a file beside the supervisor's lock, kept for 30 days. The simulator SHALL read a wake's events from that file, matched by owner and end time, when the transcript does not hold them. The file SHALL stay on the machine, and no report SHALL print a line of it.

#### Scenario: The machine was restarted
- **WHEN** the simulator runs after a restart that erased the temporary output files, on wakes recorded since the file exists
- **THEN** each of those wakes that started a turn is classified from the file

#### Scenario: A wake older than the file
- **WHEN** a wake was recorded before the watcher kept its events and its output is in neither the transcript nor a temporary file
- **THEN** it is unclassified, as before

#### Scenario: A wake that started no turn
- **WHEN** the events of a soft wake are known and another message arrived before the supervisor answered it
- **THEN** it is unclassified, because what the supervisor did for it cannot be told apart

### Requirement: The simulator compares today with a fixed rule
A recorded wake SHALL count as soft when the watcher's output was only idle-to-busy lines or only `TIMEOUT`. The simulator SHALL report, for today's behaviour and for a fixed rule with no model that sleeps every soft wake: the wakes, the main-model tokens raw and weighted, and the needed wakes the rule would have slept. The rule's figures SHALL be labelled upper bounds, because the deadline, the report time and what waited for the supervisor are not in the history.

#### Scenario: The fixed rule on a known transcript
- **WHEN** the simulator runs on the seeded transcript
- **THEN** it reports the known saving of the fixed rule and the known list of needed wakes it would have slept, both labelled as upper bounds

#### Scenario: No weights measured
- **WHEN** the cache weights of the usage limit could not be measured
- **THEN** the report gives raw tokens only and says so in its first lines

### Requirement: Nothing is built for a small saving, and a safe fixed rule wins
The decision SHALL be the first of these that applies to the simulator's report. With fewer than 100 classified soft wakes, or more than one soft wake in ten unclassified, it SHALL stay open. With the fixed rule's saving under 5 % of the supervisors' flow, nothing SHALL be built for triage. With at most one classified soft wake in 100 needed, the fixed rule SHALL be proposed as a change of its own and `wake-triage` SHALL NOT be built.

#### Scenario: Too few wakes
- **WHEN** the report holds 40 classified soft wakes
- **THEN** the decision stays open, more days are recorded and nothing is built

#### Scenario: The saving is too small either way
- **WHEN** the fixed rule would save 2 % of the supervisors' weighted flow
- **THEN** the decision is "no-go" and nothing is built for triage

#### Scenario: Safe and too small
- **WHEN** the fixed rule would save 2 % and none of 300 classified soft wakes was needed
- **THEN** the decision is "no-go", nothing is built for triage and the rule is not proposed

#### Scenario: The fixed rule is safe
- **WHEN** the fixed rule would save 12 % and 1 of 300 classified soft wakes was needed
- **THEN** the decision is "no-go for wake-triage", the triage tasks are closed as not built, and the fixed rule is proposed separately

### Requirement: Triage is built only if a model is safer than the fixed rule
When the saving is worth it and the fixed rule is unsafe, the decision SHALL stay open and nothing that honours a `sleep` SHALL be built until a candidate member is shown to sleep at most one needed wake per 100 classified soft wakes while keeping at least half of the fixed rule's saving and no less than 3 % of the supervisors' flow. Shown otherwise, neither SHALL be built. The developer MAY set other thresholds in writing after reading the report.

#### Scenario: The fixed rule is unsafe and a model is not better
- **WHEN** 9 of 100 classified soft wakes were needed and the tested member sleeps 6 of them
- **THEN** the decision is "no-go": neither is built

#### Scenario: A model is safe and keeps the saving
- **WHEN** 9 of 100 classified soft wakes were needed, and the tested member sleeps 1 of them and keeps 60 % of the saving, which is 4 % of the flow
- **THEN** the decision is "go" and the triage tasks are opened

#### Scenario: No member has been tested
- **WHEN** the fixed rule is unsafe and no member has been tested
- **THEN** the decision stays open, nothing is built, and the report says what is missing

### Requirement: A candidate member is tested in shadow on live wakes
On the decision "a model must be tested", the member SHALL be tested in `shadow` on live wakes and not by replay. The watcher SHALL record the member's verdict for each soft wake and wake the supervisor as before; the simulator SHALL read from the transcript whether that wake was needed. The test SHALL run until 100 classified soft wakes carry a verdict. A late, failed or malformed answer SHALL count as `wake`.

#### Scenario: The member would have slept a needed wake
- **WHEN** the member said `sleep` in shadow and, in the turn that wake started, the supervisor sent a message to a session
- **THEN** the wake counts as a needed wake the member would have slept

#### Scenario: An answer arrives late
- **WHEN** the member answers after the triage's time limit
- **THEN** the verdict counts as `wake` and adds nothing to the member's saving

#### Scenario: The test ends
- **WHEN** 100 classified soft wakes carry a verdict
- **THEN** a written result gives the needed wakes the member would have slept per 100, and its saving as a share of the fixed rule's and of the flow, and the decision is recorded as "go" or "no-go"

### Requirement: The shadow test is built only when it can run
What the shadow test needs (the soft-event list, the brief builder, the verdict parser, shadow mode and the pool's `ask` for `wake-triage`) SHALL be built only after the developer has installed the gateway and connected a member. Nothing that honours a `sleep` SHALL be built before the decision is "go".

#### Scenario: The gateway is not installed
- **WHEN** the decision is "a model must be tested" and no gateway is installed
- **THEN** nothing is built, the decision stays open, and the report says the test waits for the developer's install

#### Scenario: The gateway is installed and the decision is open
- **WHEN** the decision is "a model must be tested" and a member answers through the gateway
- **THEN** the shadow test's pieces are built and the test starts, and no sleep is honoured while it runs

### Requirement: Only two shapes of event are soft
The watcher SHALL send to triage only: (a) a batch of events made only of lines that say a session went from idle to busy; (b) a timeout with no event, and only when the watcher was armed with a wake-by time. A batch that contains any other line SHALL wake the supervisor at once and nothing SHALL be sent to the pool. An event kind the code does not list as soft SHALL be hard.

#### Scenario: A session crashes while the pool is in auto
- **WHEN** the watcher sees a crash event
- **THEN** the supervisor is woken at once and no pool request is made

#### Scenario: A turn ends
- **WHEN** a session of the project goes from busy to idle, or its count of finished turns changes
- **THEN** the supervisor is woken at once, because a finished turn has to be verified on disk

#### Scenario: A mixed batch
- **WHEN** one poll shows one session going from idle to busy and another one waiting for a person
- **THEN** the supervisor is woken at once and no pool request is made

#### Scenario: A timeout without a wake-by time
- **WHEN** the watcher was armed without a wake-by time and its timeout passes
- **THEN** the supervisor is woken and no pool request is made

### Requirement: Guard mode and repeated notices are never triaged
Triage SHALL NOT run in guard mode. The repeated notices of the wake-economy rules SHALL NOT be triaged. The soft list SHALL be a constant of the code that configuration can only shorten.

#### Scenario: An idle notice
- **WHEN** the watcher produces the notice that nobody in the project is working
- **THEN** the supervisor is woken as today and no pool request is made

#### Scenario: A supervisor on guard
- **WHEN** the watcher runs in guard mode and its timeout passes
- **THEN** the supervisor is woken and no pool request is made

#### Scenario: An override adds an event to the soft list
- **WHEN** an override lists a crash as a soft event
- **THEN** the key is ignored, a crash still wakes at once, and the pool's doctor reports the ignored key

### Requirement: The triage brief is built from structured fields only
The brief sent for `wake-triage` SHALL contain only: the kinds of the events; per session its id, status, idle age and count of turns; the seconds left to each bound of a sleep; and the number of sleeps already honoured in the stretch. It SHALL NOT contain a session title, a raw watcher line, a job label, register text, transcript text, code, command output or file contents. Its size SHALL stay below the configured limit (default 2 000 tokens).

#### Scenario: Building the brief
- **WHEN** a brief is built for a project whose sessions have titles, queued jobs with labels and a register
- **THEN** none of those texts appears in the brief, and a test proves it with marker strings planted in each

### Requirement: The answer is a verdict in a fixed format
The triage answer SHALL be accepted only as one JSON object with a `verdict` of `sleep` or `wake` and a `reason` from this list: `started-work`, `nothing-changed`, `deadline-near`, `many-sessions`, `long-busy`, `unsure`. A timeout, an error, a refusal, text outside the object, another verdict, an unknown reason, any exit code other than success or a response from a model other than the member's SHALL wake the supervisor.

#### Scenario: The model answers with prose
- **WHEN** the triage answer has text around the object
- **THEN** the supervisor is woken and the ledger row is "malformed answer"

#### Scenario: The model writes its own reason
- **WHEN** the answer's reason is a sentence instead of a listed code
- **THEN** the supervisor is woken, and that sentence is never printed to it

### Requirement: The triage has a short time limit
The triage's own time limit SHALL be short (default 20 seconds, never above 30). It is the longest a hard event that arrives during a triage can be delayed.

#### Scenario: A slow model and a crash
- **WHEN** a triage is still waiting for its answer after the time limit and a session crashed meanwhile
- **THEN** the supervisor is woken at the limit, the wake names the crash, and the ledger row is "timeout"

### Requirement: A sleep is recorded on disk and refreshes the watcher's baseline
In `auto`, the watcher SHALL honour a `sleep` by appending the slept events, with their time, reason code and ledger id, to a journal on disk kept per project under the supervisor's home; by replacing the snapshot it compares against with the current one; and by going on waiting instead of exiting. The journal SHALL hold when the stretch of sleeps started and how many were honoured, so that the stretch survives the watcher's exit and re-arm.

#### Scenario: The same session, twice
- **WHEN** a session's start of work was slept and the watcher polls again with nothing new
- **THEN** no event is produced for that session, and the sleep count is still one

#### Scenario: The slept session then finishes its turn
- **WHEN** a session whose start of work was slept goes back to idle
- **THEN** the supervisor is woken at once

#### Scenario: The watcher dies after a sleep
- **WHEN** the watcher is killed after honouring a sleep and a new one is armed
- **THEN** the journal still lists the slept event and the new watcher continues the same stretch

### Requirement: A sleep is bounded
The watcher SHALL honour a `sleep` only while all of these hold, and SHALL wake the supervisor at the first of them to pass: the wake-by time it was armed with, when given, and otherwise the timeout the supervisor chose; the start of the stretch plus the maximum silent time (default and upper limit 2 hours); the time the supervisor's periodic report falls due; and fewer consecutive sleeps than the limit (default and upper limit 4).

#### Scenario: Fifth soft event in a row
- **WHEN** four consecutive sleeps were honoured and a fifth soft event arrives
- **THEN** the supervisor is woken without a pool request, and the wake lists the five events

#### Scenario: Deadline inside the wait
- **WHEN** a `sleep` would keep the supervisor asleep past the wake-by time
- **THEN** the supervisor is woken at that time at the latest

#### Scenario: The report falls due
- **WHEN** a sleep is honoured and the supervisor's periodic report falls due 10 minutes later with no event
- **THEN** the supervisor is woken at that moment

### Requirement: The deadline is an argument, and nothing is triaged while something waits
The supervisor SHALL pass the nearest deadline of its work in flight as the wake-by time when it arms the watcher; the watcher SHALL NOT read the register. While the project has an item that the supervision counts as waiting for the supervisor by time alone, no event SHALL be triaged.

#### Scenario: Something already waits for the supervisor
- **WHEN** the project has a session that the supervision would count as unattended
- **THEN** every event wakes and no pool request is made

#### Scenario: Arming the watcher
- **WHEN** the supervisor arms its watcher with work in flight due in 40 minutes
- **THEN** the watcher's command line carries that time as its wake-by, and the watcher opens no register file

### Requirement: A wake after sleeps says what was slept
When the supervisor is woken after one or more honoured sleeps, the watcher's output SHALL list each slept event with its time, reason code and ledger id before the event that woke it. A supervision command SHALL print the same list from the journal, so that it can be read when the wake came from somewhere else.

#### Scenario: Reading the wake
- **WHEN** a supervisor wakes after two honoured sleeps
- **THEN** the first lines of the watcher's output name both slept events and their ledger ids

#### Scenario: Woken by the developer during a stretch
- **WHEN** the developer writes to the supervisor while its watcher holds two slept events
- **THEN** the judging step of that turn lists both from the journal

### Requirement: The supervisor judges the sleeps with an explicit command
The supervision skill's tick SHALL have a step, right after reading the watcher's output, that lists the journal with one supervision command and records for each entry whether the supervisor was `needed` or `not-needed` for that event before now. One supervision command SHALL record the answers and pass them to the pool's ledger. The stretch SHALL close when no entry is left unjudged; an entry that is not judged SHALL stay `unknown` and SHALL be listed again at the next wake.

#### Scenario: Nothing was missed
- **WHEN** the supervisor judges every slept event as `not-needed`
- **THEN** the rows are `agreed`, the journal is empty and a new stretch starts at the next sleep

#### Scenario: The tick ends without the step
- **WHEN** the supervisor skips the judging step
- **THEN** the rows stay `unknown`, they add nothing to the saving, and the next wake lists them again

### Requirement: Shadow triage changes nothing and is judged by the same question
In `shadow`, the watcher SHALL run the triage, wake the supervisor exactly as without the pool, and append the verdict to the same journal, marked as shadow, so that the judging step lists it. The entry SHALL be judged by the same question as a sleep: whether the supervisor was needed for that event.

#### Scenario: Shadow sleep, supervisor was needed
- **WHEN** the pool said `sleep` in shadow and the supervisor judges that it was `needed`
- **THEN** the row is `missed` and counts as a false sleep in the pair's scorecard

#### Scenario: Shadow sleep, routine tick
- **WHEN** the pool said `sleep` in shadow and the supervisor only took its census and re-armed the watcher
- **THEN** the supervisor judges `not-needed` and the row is `agreed`

#### Scenario: Shadow wake, routine tick
- **WHEN** the pool said `wake` in shadow and the supervisor judges `not-needed`
- **THEN** the row is `overwake`: it lowers the agreement and is not a miss

### Requirement: Digests are data the main model reads, never instructions
`turn-report-check`, `log-digest`, `closing-evidence-summary` and `dialog-draft` SHALL be used by a session only as input it reads, and each answer SHALL arrive inside the envelope that marks it as data from another model. A session SHALL NOT follow an instruction found in a digest and SHALL NOT forward a digest to another session as a message. The supervision skill and the briefs it gives its child sessions SHALL say so.

#### Scenario: A log that carries an instruction
- **WHEN** the digested output contains a line telling the reader to run a command
- **THEN** the digest arrives marked as data, and the skill's rule tells the session not to act on it

#### Scenario: No member accepts private data
- **WHEN** no active member accepts `private`
- **THEN** the session reads the output itself, as before

### Requirement: Each digest task kind has one caller and one step
`turn-report-check` SHALL be asked for by the supervisor, when a child's end-of-turn report arrives and before it decides that child's next step. `closing-evidence-summary` SHALL be asked for by the closing session, after its checks on disk and before it writes the register. `dialog-draft` SHALL be asked for by the question session, before it opens a dialog. `log-digest` SHALL be open to every session in scope.

#### Scenario: A child's report is classified as done
- **WHEN** the supervisor receives `done` for a child's report
- **THEN** it uses the answer to order its work and still checks on disk before it closes that child

#### Scenario: A check on disk failed
- **WHEN** one of the closing session's checks failed
- **THEN** it asks for no summary and writes the failure itself

#### Scenario: A draft for the developer
- **WHEN** the question session receives a draft
- **THEN** it checks every fact of the draft against the queued question and rewrites it before the dialog opens; the draft is never shown as it arrived

#### Scenario: A child session asks for a report check
- **WHEN** a child session asks for `turn-report-check`
- **THEN** the skill's rule for its role does not list that task kind, and the call is recorded with its caller's role

### Requirement: A digest says what it left out, and the original stays the authority
A digest SHALL say what it left out (the size of the original and the number of lines dropped). A session SHALL open the original before any action that cannot be undone, and SHALL report when it read the whole original anyway.

#### Scenario: A test log of two megabytes
- **WHEN** a child session asks for a `log-digest` of a long test output and a member that accepts private data is active
- **THEN** it receives the failing tests with their locations and the count of lines dropped, and reads the original only for the failures it will fix

### Requirement: Scope is the supervisor and its child sessions
Only the live supervisor of an enabled project and the sessions its census lists in that project SHALL use these offload points. `wake-triage` SHALL be used by the watcher of the supervisor only. The supervision skill and the briefs it gives its child sessions SHALL name the task kinds each role may use.

#### Scenario: A session opened by the developer in a supervised project
- **WHEN** the census lists it as a session of the project
- **THEN** it may use the digest task kinds, and not `wake-triage`

### Requirement: The report carries the saving
The supervisor's periodic report SHALL include one line with the pool tokens spent, the main-model tokens avoided (as an estimate, raw and weighted when weights are set), the leverage and the misses since the previous report, taken from the ledger with one command. With the pool stopped or at level 0 the line SHALL be absent.

#### Scenario: A day with misses
- **WHEN** two misses were recorded since the last report
- **THEN** the line names them and says which pair was demoted

### Requirement: The triage is switched off when it does not pay
After 7 days of `wake-triage` in `auto`, a written result SHALL compare the supervisors' wakes and tokens per hour with the simulator's baseline. The triage SHALL be switched off, and the result SHALL say so plainly, when the weighted leverage is under 10, when there was more than one miss per 100 honoured sleeps, or when the measured saving is under 3 % of the supervisors' flow. Without cache weights the comparison SHALL use raw tokens, say so, and leave the leverage test out.

#### Scenario: A week with too many misses
- **WHEN** the week shows 3 misses in 120 honoured sleeps
- **THEN** the result recommends switching the triage off and the pair is set to `off`

#### Scenario: No weights were ever measured
- **WHEN** the week ends and the cache weights are not set
- **THEN** the result compares raw tokens, says so in its first lines, and applies the other two tests
