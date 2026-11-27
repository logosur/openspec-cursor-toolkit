# Proposal — external-access

> **Status:** PROPOSED. Nothing implemented yet.

## Why

Sessions keep needing three things that live outside every repository: mailboxes, the Google Play Console and App Store Connect. A project that needs one tends to grow its own skill and script for it, and those rot:

- A script that reads a desktop mail client's local store through a hard-coded profile and folder path breaks without notice when the client switches profile or renames a folder.
- Projects that read the same mailbox each write their own credential loader and keep their own copy of the password.
- Without a tool, every look at a release or a review means driving the browser, and the console address (developer id, app id, which signed-in user) is rebuilt by hand from notes.
- Detail about stores and mail ends up in always-loaded rules, because there is no on-demand place for it.

The cost is paid three times: in tokens (each project re-explains the mechanism), in reliability (a path written in prose breaks silently) and in model responsibility (the model resolves profiles, builds queries and judges freshness, which a script does better).

## What Changes

- A new optional module, `access`, with two read-only command-line pieces and one short skill:
  - **`mailbox`**: one interface over the backends an account can have — the local store of a desktop mail client, live IMAP, or a mail connector. Accounts are named in the piece's configuration; the command resolves the store, indexes it, searches, shows a message, lists a thread and saves attachments. For a connector account the command cannot make the call itself: it says which connector tools the session has to call and checks the connector's identity.
  - **`stores`**: one interface over Google Play (Developer API, service account) and App Store Connect (API key). It diagnoses what is missing, reads tracks, releases, reviews, versions and builds, checks the public listing, and prints the exact console address for what the API does not cover.
  - **`cuentas-externas`** skill: a routing page of a few lines. It is the only text a session loads; each command's `--help` is the documentation.
- Machine values (addresses, hosts, credential file paths, developer and app ids) live in the config pieces `mailbox` and `stores`; the repository ships empty defaults.
- No new rule under `rules/` and no hook.

## Capabilities

- `mailbox-access` (new): `specs/mailbox-access/spec.md`.
- `store-access` (new): `specs/store-access/spec.md`.

## Impact

- New files only, all owned by the new module: `global/modules/access.yaml`, `global/scripts/mailbox`, `global/scripts/stores`, `global/scripts/lib/access/`, `global/skills/cuentas-externas/SKILL.md`, `global/config/{mailbox,stores}.json`, `global/contracts/{mailbox,stores}.yaml`, and tests under `scripts/toolkit/tests/pieces/`.
- Edited: `README.md` (module table), `CLAUDE.md` (list of optional modules), `examples/override-full/` (module on, example config with reserved example domains).
- Not default: a machine gets it by naming `access` in its override. Without accounts configured both commands answer with an empty list and a hint.
- Dependencies: Python standard library only. `stores` signs tokens with the `openssl` binary; without it `stores doctor` says so and `mailbox` is unaffected.

## Out of scope

- **Any write.** No sending, replying, moving, flagging or deleting mail; no upload, release, rollout, reply to a review or listing edit in a store. A later change may add writes behind their own authorisation.
- **Lending a token to another program** (an external store CLI). The token of either store is read-write, so handing it to an arbitrary command is a write path; it belongs with the writes.
- Creating credentials (a service account, an API key, a mail password). The owner of the account does that; `doctor` names exactly what is missing.
- Installing external store or mail CLIs.
- Replacing project scripts that run a workflow of their own on a mailbox (filing, moving processed mail). They can read the resolved store path from `mailbox where`.
- Moving store and mail detail out of the always-loaded rules. This change gives that detail a home; removing it from the rules is a follow-up, because every live supervisor reloads when a rule changes.
