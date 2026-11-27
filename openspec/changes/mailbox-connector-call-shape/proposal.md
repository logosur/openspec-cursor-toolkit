# Proposal — mailbox-connector-call-shape

> **Created by:** `/prepara-tarea mailbox-connector-call-shape` (phase P1 of `run-spec`), 2026-11-27.
> **Status:** PROPOSED. Nothing implemented yet.
> **Related:** `external-access` (adds `mailbox` and its connector delegation; merged and installed, not archived yet, so its
> capability `mailbox-access` has no baseline under `openspec/specs/`), `mailbox-search-gaps` (archived; its capability
> `mailbox-search-results` is permanent). Marks used below: **FACT** (read in the code or measured), **INFERENCE**,
> **HYPOTHESIS**, **UNKNOWN**.

## Why

For a connector account (`kind: gmail`), `mailbox` reads nothing: the assistant session holds the mail connector, so the
command prints the call to make and exits 10. The session is meant to pass that call on as printed. Three printed calls are
incomplete or unbounded today, so the session has to choose values itself, and the choices are the expensive ones.

1. **`search`.** FACT (`mail_connector.search_document`): it prints `arguments` with `query` and `pageSize`, where `pageSize`
   is `--limit` unchanged, and names `read_tool`. Two defects. A `--limit 200` prints a call the connector refuses (its
   maximum page size is 50). No `view` is given, so the connector's default applies, which returns up to five messages per
   thread: an unbounded listing in tokens.
2. **`show` and `thread`.** FACT (`mail_connector.read_document`, `global/scripts/mailbox` `_id_command`): both print only
   `{"delegate": "connector", "kind": …, "tool": "get_thread", "note": "call this tool with the id returned by the search
   call"}`. There is no `arguments`; the id typed on the command line is dropped; the session picks the message format. The
   expensive format (`FULL_CONTENT`) also returns the HTML body, and nothing stops a session from choosing it.
3. **`whoami`.** FACT (`whoami_call`): it prints `{"tool": "search_threads", "arguments": {"query": "in:sent", "pageSize":
   1}}` with no `view`, so the one-message check can still return a whole thread at the connector's default view.

Connector shapes, measured by the orchestrator against the live connector on 2026-11-27, shape and counts only, no content:
the search `view` is one of `THREAD_VIEW_METADATA_ONLY`, `THREAD_VIEW_MINIMAL`, `THREAD_VIEW_IDS_ONLY`, `THREAD_VIEW_SUMMARY`;
`pageSize` defaults to 20 and is at most 50; `pageToken` continues a search. With `THREAD_VIEW_METADATA_ONLY` each message
carries its id, sender, thread id and recipients (all the identity check needs). With `THREAD_VIEW_SUMMARY` and
`THREAD_VIEW_MINIMAL`, single-message threads come back identical (the subject is added), so `SUMMARY` is never larger than
`MINIMAL` and bounds a multi-message thread to one message. The read tool takes a required `threadId` and a `messageFormat`
that is one of `MINIMAL`, `FULL_CONTENT`, `METADATA_ONLY`, `PLAIN_TEXT` (default `PLAIN_TEXT`).

The cost is in tokens on every connector search and read of a session, and in a decision (which view, which format) that a
script can make once, deterministically, and a session can get wrong.

## What Changes

- **`search`** prints `arguments` `{query, pageSize, view}`. `view` defaults to `THREAD_VIEW_SUMMARY` and is overridable per
  account with `connector.search_view`, validated against the four known values. `pageSize` is `min(limit, page-size
  maximum)`, the maximum being 50 or the account's `connector.page_size_max`. A new top-level key `paging` (`requested`,
  `page_size`, `capped`, and when capped `continue_with: "pageToken"` and a one-sentence `how`) states a cut. It is outside
  `arguments`, so a verbatim pass sends the connector nothing it does not know.
- **`show` and `thread`** on a connector account print `arguments` `{threadId: <id as typed>, messageFormat}`, exit 10, and keep
  `delegate`, `kind`, `tool` and `note`. `messageFormat` defaults to `PLAIN_TEXT`, is overridable with `connector.read_format`
  (validated against the four known values), and is `FULL_CONTENT` only through that setting or the new flag
  `--full-content`. No flag selects `MINIMAL` (design D5).
- **`whoami`** prints `view: THREAD_VIEW_METADATA_ONLY` in the check call, fixed.
- **Validation:** an invalid `connector.search_view`, `connector.read_format` or `connector.page_size_max` makes the account
  unusable like any other mistyped account setting (exit 2, a line naming the setting and the known values), never a silent
  fallback to the default.
- **Additive:** every existing key of every document keeps its name, type and value; the connector's server identifier is
  still never stored or printed.
- **Skill `cuentas-externas`:** its connector step says to run `mailbox search|show|thread` and pass the printed `tool` and
  `arguments` as printed, adding and removing nothing. Words are replaced, not added: the body must not grow (1 862 characters
  now; the existing test caps it at 2 000).
- `--help`, a contract probe, the self-test and the piece tests are updated (design D9).

## Capabilities

- New: `mailbox-connector-calls` (ADDED requirements only). **How the delta is expressed:** `mailbox-access` of
  `external-access` is not under `openspec/specs/` yet, so a `MODIFIED` delta against it would be refused at archive (the
  precedent of `mailbox-search-gaps`). The connector requirements are therefore new ones that add to it.
- Modified: `mailbox-search-results`, requirement "Existing output is unchanged and costs nothing more". It ends with the bare
  invariant "Connector accounts SHALL behave as before", which this change makes false in the letter (a search document gains
  `arguments.view` and `paging`). The requirement is restated whole (the permanent capability has a baseline), with its
  connector sentence and the scenario "Connector accounts do not change" reworded to "keeps its keys, exit codes and refusals".
- **Divergence recorded, not edited:** `external-access` (`mailbox-access`, "One short routing skill") says the skill sends
  the session "straight to the connector's search and read tools". After this change the skill sends the session first through
  `mailbox search|show|thread`, which prints the call. That open change is not edited here; the skill requirement of the new
  capability governs the skill from now on, and the divergence is to be reconciled when `external-access` is archived.

## Impact

- Edited, all inside the module `access`: `global/scripts/lib/access/mail_connector.py` (constants, settings, validation, the
  three call builders), `global/scripts/mailbox` (`_setting_problem`, `_id_command`,
  `--full-content` on `show` and `thread`, the `--help` section "Connector accounts"), `global/scripts/lib/access/mail_selftest.py`
  (the connector checks), `global/contracts/mailbox.yaml` (a probe), `global/skills/cuentas-externas/SKILL.md` (wording), and
  the tests `scripts/toolkit/tests/pieces/test_mailbox.py` (two existing tests assert exact keys and are updated, a third reads only the tool and is kept; new tests).
- Not edited: `external-access`, `global/config/mailbox.json` (the shipped config has no account; the per-account defaults live
  in code, D6), `examples/override-full/` (its connector account sets only `kind`, which keeps working), `README.md`, `stores`,
  the `imap` and `local` backends, `output.py`.
- Cost: none at run time (no new I/O). Savings are in the session's tokens per connector search and read (INFERENCE; measured
  only as shapes, task 9.1).
- Compatibility: design D8. Document keys, exit codes and refusals do not change; values gain `view`, `paging` and `arguments`.

## Out of scope

- Any write to a mailbox; other connector kinds (their documents are unchanged); calling the connector from the script; the
  `imap` and `local` backends.
- `folders` and `save` on a connector account: they print the same document as before (no `arguments`); they have no connector
  read equivalent. Recorded in design D7.
- Following `pageToken` automatically: the script cannot call the connector; it states how to continue (D3).
- A flag or setting for the headers-only read as an option of `show`/`thread` (D5).
