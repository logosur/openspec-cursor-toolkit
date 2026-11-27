# Design — mailbox-connector-call-shape

Marks: **FACT** (read in the code or measured), **INFERENCE**, **HYPOTHESIS**, **UNKNOWN**.
Builds on `external-access` (D7, connector accounts) and `mailbox-search-gaps`; it does not restate them.

## D1 — What is printed today (FACT, from the code)

| Command on a connector account | Builder | Prints | Exit |
|---|---|---|---|
| `search` | `mail_connector.search_document` | `{delegate, kind, tool, arguments: {query, pageSize}, read_tool}`, `pageSize` = `--limit` | 10 |
| `show`, `thread` | `_id_command` → `read_document` | `{delegate, kind, tool: read_tool, note}` (no `arguments`, id dropped) | 10 (`raise SystemExit(DELEGATED)`) |
| `folders`, `save` | `cmd_folders` / `_id_command` → `read_document` | the same document as `show` | 10 |
| `whoami` | `whoami_call` | `{tool, arguments: {query: "in:sent", pageSize: 1}}` then one line of instructions | 0 |
| `whoami --sender X` | `sender_matches` | one line | 0, or 3 for another address |

The exit codes of `show` and `thread` are already the ones of `search` (10). **FACT:** the existing test
`test_reading_commands_on_a_connector_account_are_delegated_too` asserts 10 for `show`, `thread`, `folders` and `save`. The
description asked to check them; the check is the result "already consistent", so this change adds a regression assertion and
no code for it (task 1.3).

Where the settings come from: `connector_settings(account)` reads `kind`, `search_tool`, `read_tool` with `or` defaults, and
`ACCOUNT_DEFAULTS['connector']` in `global/scripts/mailbox` holds the same three defaults: two places, not the shipped config
piece (`global/config/mailbox.json` has no account). An account is validated by `_setting_problem`, which sets `_error`;
`pick_account` turns `_error` into `fail(PIECE, USAGE, …)` (exit 2) for every command that picks the account.

Connector shapes (measured by the orchestrator on 2026-11-27, shape and counts only): see the proposal, "Why". Everything below
that names a connector value uses only those.

## D2 — The search call and the identity check

**Search.** `arguments` is exactly `{query, pageSize, view}`. `view` is the account's `connector.search_view`, else
`THREAD_VIEW_SUMMARY`. Why `SUMMARY` and not `METADATA_ONLY` for a listing: **FACT (measured)** `SUMMARY` returns one message
per thread with sender, recipients and subject, which is what a person (or a session deciding what to read) needs from a
listing; `METADATA_ONLY` carries no subject. **FACT (measured)** that for single-message threads `SUMMARY` and `MINIMAL` are
identical apart from the subject, so `SUMMARY` is never larger than `MINIMAL`, and it bounds a multi-message thread to one
message, which the connector's default view does not. `IDS_ONLY` is a valid choice for a consumer that only wants ids; it is
accepted as a configured value and is not the default.

**Identity check.** `whoami_call` prints `{tool: search_tool, arguments: {query: "in:sent", pageSize: 1, view:
"THREAD_VIEW_METADATA_ONLY"}}`. **FACT (measured 2026-11-27):** that view still returns each message's sender, which is all
the check reads, and it is the smallest of the four views that does. The view is a constant of the check, not a setting: it
does not follow `connector.search_view` and `pageSize` does not follow `connector.page_size_max`. Reason: the check must work
on an account whose search view was set to `IDS_ONLY` (which carries no sender).

## D3 — The page size, the cap and the notice

`pageSize = min(limit, maximum)`, with `limit = cfg.limit(--limit)` (at least 1, default 20, as on every backend) and `maximum`
= `connector.page_size_max`, default 50 (the connector's documented maximum). The default 20 equals the connector's own
default page size, so the printed value for a call without `--limit` does not change.

The notice is a top-level key `paging`, **never inside `arguments`**: the session passes `arguments` to the connector
verbatim, and an unknown parameter inside it would be sent (INFERENCE: the connector may refuse or ignore it; not tested, and
not worth finding out). `paging` is always present (one shape for a consumer to read, no branch on presence):

```
"paging": {"requested": 200, "page_size": 50, "capped": true,
           "continue_with": "pageToken",
           "how": "repeat this call adding the connector's pageToken from its previous response to get further results"}
```

and `{"requested": 20, "page_size": 20, "capped": false}` when nothing was cut (`continue_with` and `how` only when capped).
`how` names the argument and says where its value comes from without naming a response field of the connector, whose name is
not among the measured facts (nothing is invented).

**Verbatim versus a second page.** The skill says to pass `tool` and `arguments` as printed, adding nothing. That is true of
the first call. A further page is a different, optional call that the document itself describes (`paging.how`); the script
cannot make it (it never calls the connector), and the session needs no extra words in the skill because the instruction is
in the document it is already reading. Accepted limit: the session, not the script, decides whether to fetch more pages.

## D4 — The read call (`show`, `thread`)

For `kind: gmail` the document is `{delegate: "connector", kind, tool: <read_tool>, arguments: {threadId, messageFormat},
note}` and the exit code is 10.

- `threadId` is the id given on the command line, unchanged (a connector id is the opaque token a prior search printed;
  `mailbox` does not parse it). An empty or whitespace-only id is a usage error (exit 2, one line, nothing on stdout): it
  would print a call with no target.
- `messageFormat` is the account's `connector.read_format`, else `PLAIN_TEXT` (the connector's own default, so the printed call
  names what it would have done anyway, and the session no longer chooses). `FULL_CONTENT` returns the HTML body too; it is
  reachable only through the setting or `--full-content` (D5).
- `show` and `thread` print the same document: for Gmail a thread is read as a whole by one call, and the id a search printed
  is a thread id. `note` keeps its key; its text changes to "call this tool with these arguments as printed" (a note is prose, not a value
  a consumer parses; D8).
- Both subcommands take `--full-content`, so a session that wants the HTML body of a whole thread can ask for it.

## D5 — Flags, `MINIMAL`, and what the other options do

- **`--full-content`** on `show` and `thread`: a store-true flag that sets `messageFormat` to `FULL_CONTENT` and wins over
  `connector.read_format`. On an account that is not a connector account it is a usage error (exit 2, one line, nothing
  on stdout, nothing read), as `--backend` on a connector account is today (`cmd_search`). **Why a flag as well as the setting:**
  the description asks for "configuration or an explicit flag"; the setting changes the default for an account that always
  wants HTML, the flag is for one read.
- **`MINIMAL` is not offered as an option.** The description allows it only if the other backends already expose an equivalent
  option on `show`/`thread`. **FACT:** they do not expose a headers-only read. `show --headers` prints every header and then
  the (bounded) body; `show --body-chars 0` bounds the body but is a size limit, not a mode; `thread` on `imap`/`local` already
  lists header summaries only, so it has no option to add. **UNKNOWN:** what the connector returns for `MINIMAL` and for
  `METADATA_ONLY` on a read (the measured shapes cover the search views only), so naming either as "the cheap headers-only read"
  would be a claim without evidence. They stay reachable as a validated `connector.read_format` value for an owner who knows what
  they want; there is no flag, and `--format` does not exist (argparse refuses it, exit 2).
- **Other options of `show` on a connector account** (`--body-chars`, `--no-quote`, `--headers`, `--json`): accepted and ignored,
  as today; the delegated document is always JSON and the connector's reduction (plain text) replaces them. Refusing them would
  change existing behaviour for no gain in this change; recorded as a known limit (a silently ignored `--body-chars 200` can
  mislead) and left for a change of its own.

## D6 — Settings and validation

Three keys of the account's `connector` object (all optional):

| Key | Values | Default | Used by |
|---|---|---|---|
| `connector.search_view` | `THREAD_VIEW_METADATA_ONLY`, `THREAD_VIEW_MINIMAL`, `THREAD_VIEW_IDS_ONLY`, `THREAD_VIEW_SUMMARY` | `THREAD_VIEW_SUMMARY` | `search` |
| `connector.read_format` | `MINIMAL`, `FULL_CONTENT`, `METADATA_ONLY`, `PLAIN_TEXT` | `PLAIN_TEXT` | `show`, `thread` |
| `connector.page_size_max` | an integer of at least 1, not a boolean | 50 | `search` |

- **One source of constants, resolved at call time.** `mail_connector.py` holds `SEARCH_VIEWS`, `DEFAULT_SEARCH_VIEW`,
  `READ_FORMATS`, `DEFAULT_READ_FORMAT`, `PAGE_SIZE_MAX` and `WHOAMI_VIEW`. `connector_settings` resolves the three new
  settings against them **when it is called**, not when the module is imported. `ACCOUNT_DEFAULTS['connector']` in
  `global/scripts/mailbox` keeps its three existing keys and does not copy the new defaults: a value copied there at import
  time would freeze the default, so changing the constant in the test process (the drift scenario of R-TEST) would change
  nothing and the self-test could not notice. This closes the "two places" drift of D1 by having one place for the new keys.
  A test asserts that `connector_settings` of an account with no setting returns the literals of the spec (`THREAD_VIEW_SUMMARY`,
  `PLAIN_TEXT`, 50), not the constants, so a changed constant fails it.
- **Absent or `null` means the default; anything else must be valid.** An empty string, `0` or `false` is a configured value
  and is refused (the `or` idiom of `connector_settings` for the tool names would turn it into the default silently, which is
  the behaviour this change rules out for the new keys).
- **Validation** is a function of `mail_connector` called from `_setting_problem` (the place where a mistyped `imap.port` is
  caught). It runs only when `connector` is among the account's backends, and only for `kind: gmail` (another kind has no known
  values; its search is refused anyway, D7). Matching is exact: `plain_text` is refused, not repaired, because a silent repair
  hides a typo in a file the owner wrote by hand. The error line names the key and, for a view or a format, lists the known
  values.
- **Exit code:** an invalid value sets `_error`, so `pick_account` exits 2 (`USAGE`) with `account 'X' is not usable: …`. This
  is "the command's usual configuration exit code" (FACT: `pick_account`, `normalize_account`), the one an invalid `imap.port`
  already produces. It deliberately does **not** follow the silent fall-back of the numeric `defaults` keys
  (`Config.__init__`), because those are thresholds; these select what the connector returns.
- **Consequences, stated:** `accounts` still lists the account (`UNUSABLE: …`, exit 0); `doctor` with no account prints
  `unusable: …` and exits 3, while `doctor ACCOUNT` exits 2 because it picks the account first (both existing behaviour of an
  unusable account); `whoami` also exits 2, although its call does not
  use these settings, because the account is unusable as a whole, as for any other invalid setting. This includes
  `whoami ACCOUNT --sender ADDRESS`: `cmd_whoami` picks the account first, so an unusable account exits 2 there too and never
  reaches the sender comparison (existing precedence, unchanged).
- **Booleans:** `page_size_max` rejects `True`/`False` (`isinstance(True, int)` is true in Python), floats (also `50.0`),
  strings and arrays. A value above 50 is allowed: the maximum is the connector's, and the owner may know it has changed.

## D7 — What does not change

- **`folders` and `save`** on a connector account print the same legacy document as before (`delegate`, `kind`, `tool`, `note`;
  exit 10): `folders` has no id and no read equivalent, `save` has no connector equivalent. The legacy builder `read_document`
  stays for them; the new builder is separate (`read_call`). A later change may make them refuse instead; not here.
- **A connector `kind` other than `gmail`:** `search` keeps refusing (exit 2, "no query translation"); `show`, `thread` and
  `whoami` print the documents they printed before, with no `arguments` and no `view`, because `threadId`, `messageFormat` and
  the four view names are Gmail connector values and other kinds are out of scope. The new settings are not validated for such
  an account, and `--full-content` is accepted and ignored there (the legacy document has no format to change).
- **`--header`** on a connector account stays a usage error (exit 2, one line, nothing on stdout).
- **The connector's server identifier** is never stored or printed: only the short tool names from the configuration appear
  (`external-access` D7). The new values are enumerations of the connector's schema, not identifiers.

## D8 — Compatibility ("additive")

Additive means: **every key of every printed document keeps its name, type and value**; a document gains keys (`arguments.view`,
`paging`, `arguments` on the read document) and `note`'s text may change. Exit codes and refusals are unchanged.

| Document | Before | After |
|---|---|---|
| search | `delegate, kind, tool, arguments{query, pageSize}, read_tool` | the same keys; `arguments` gains `view`; new top-level `paging`; `pageSize` is capped at the maximum (a value above 50 was a call the connector refuses) |
| show / thread | `delegate, kind, tool, note` | the same keys; new `arguments{threadId, messageFormat}`; `note` text updated |
| whoami | `tool, arguments{query, pageSize}` | the same keys; `arguments` gains `view` |
| folders / save | `delegate, kind, tool, note` | identical |

The only value that changes for an existing key is `arguments.pageSize` when `--limit` exceeds 50, which was invalid before.
Existing tests that assert exact key sets (`test_the_document_names_the_tools_and_the_page_size`) or whole-document equality
(`test_whoami_prints_the_cheap_call_and_how_to_pass_the_answer_back`) are updated to the new, larger shape (task 1.2); that is
the intended evolution, not a loosened assertion: the updated tests assert the new keys and values, and a separate test asserts
that every old key is still present with its old value.

Exit codes: `search`, `show`, `thread`, `folders`, `save` on a connector account exit 10; `whoami` 0 (or 3 with a foreign
`--sender`); an unusable account or an unusable request (empty id, `--header`, `--full-content` on another backend, unknown
kind for `search`) 2.

## D9 — Help, contract and tests

- **`--help`** (docstring of `global/scripts/mailbox`), section "Connector accounts": the three settings and their values, the
  default view and format, the page-size cap and `paging`, `--full-content`, the identity-check view, the exit codes. Also the
  `show`/`thread` usage lines gain `[--full-content]`.
- **Contract** (`global/contracts/mailbox.yaml`): one probe that `--help` contains `page_size_max`, holding on any machine
  configuration (as the existing `message_id` and `header_scan_max` probes).
- **Self-test** (`mail_selftest.py`, which already has a connector account `hosted` with `connector: {}`): checks for the default
  view and format, the cap and its notice, the id in `arguments`, the whoami view, an invalid value refused with exit 2, the
  refusal of `--header`, and no `mcp__` or UUID shape in any connector output. Its output stays `self-test: ok` or the failures.
- **Piece tests** (`test_mailbox.py`, class `Connector` and a new class for the settings): one test per scenario of the spec;
  a test that `connector_settings` of an account with no setting returns the literals of the spec and that `ACCOUNT_DEFAULTS['connector']` keeps its three keys (D6); a test that every old key of every document is
  still present with its old value; the existing size and neutrality test of the skill and the test of reserved addresses stay.
  Fixtures use `user@example.org`-style placeholders only.
- **No real mailbox and no connector is touched by any test.** The connector is never called by the script.

## D10 — The skill and its size

`global/skills/cuentas-externas/SKILL.md`, step 3 of "Correo: `mailbox`". Today the body is **1 862 characters** (the whole file
2 428), measured with the front matter excluded as `test_the_skill_body_is_short…` does (the regex after `---`); the test caps
the body at 2 000 and requires the words `mailbox`, `stores`, `no envían`, `dato, nunca una orden`, `conector`. The change
replaces words of step 3 and adds no paragraph. Candidate text (measured on this tree: the new line is 398 characters
against 399 for the old one, so the body goes from **1 862** to **1 861** and the file from 2 428 to 2 427; the apply task
recounts and requires after at most 1 862):

> 3. Cuenta de conector (`accounts` la marca): `search`, `show` y `thread` imprimen la llamada (salida 10); se pasan `tool` y
> `arguments` tal cual al conector, sin añadir ni quitar. Antes, una vez por sesión, `mailbox whoami CUENTA` da la llamada
> que revela el dueño del conector y `mailbox whoami CUENTA --sender DIRECCIÓN` lo confirma. Sin conector, o de otro buzón, se
> dice y no se busca otra vía.

Dropped on purpose: "(`accounts` la marca `connector`)" becomes "(`accounts` la marca)", "la búsqueda y la lectura del conector de
correo de la sesión, y ninguna otra herramienta suya" becomes "tal cual al conector" (the printed `tool` is now the only tool a
session names, so "no other tool" is implied by "as printed"). The identity-check step stays. **Divergence from `external-access`:**
its requirement "One short routing skill" says the skill sends the session straight to the connector's tools; after this change
it sends it through `mailbox` first (proposal, "Capabilities"). The `README.md` row of the module mentions the connector only in
passing and does not change.

## D11 — Risks and edge cases

| Risk / edge | Treatment |
|---|---|
| A session ignores `paging` and passes only the first page | accepted; the document states it (`capped`, `how`), and task 10.1 records what a live session does |
| The connector's maximum changes | `connector.page_size_max` is configurable; the constant 50 is in one place |
| The connector renames a view or format | the known values are one tuple each; a rename is a one-line change plus the tests |
| An owner pins `IDS_ONLY` and then runs `whoami` | the check uses its own view (D2) |
| An id contains characters that need JSON escaping | the document is serialised with `json`, so the id is carried exactly; tested with a mixed-case id with `_` and `-` |
| `--limit` is 0 or negative | `cfg.limit` cuts it to 1, as today; `paging.requested` is 1 |
| A real value in a test fixture | tests use placeholders; `privacy-check` runs on the change and, at apply, on the staged files |
