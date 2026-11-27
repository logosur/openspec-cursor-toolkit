# Spec Delta — llm-pool-gateway

## Purpose

Defines how the `llm-pool` module finds, checks and uses an OmniRoute gateway on the machine without changing how any Claude session is configured.

## ADDED Requirements

### Requirement: The gateway is reached on loopback from configuration
The module SHALL read the gateway's URL from the `llm-pool` config piece and SHALL refuse a URL whose host is not a loopback address.

#### Scenario: Non-loopback URL in the override
- **WHEN** the override sets the gateway URL to a host that is not loopback
- **THEN** every `llm-pool` command that would send a request exits with an error naming the key, and nothing is sent

### Requirement: The gateway key stays in its file
The gateway key SHALL be read from the file the config key `gateway_key_file` names (by default a file in the module's state directory) and SHALL be accepted only when that file is readable by its owner alone. It SHALL never be printed, logged, written to the ledger or the audit log, or shown by the console. The module SHALL NOT read the gateway's own data directory.

#### Scenario: Key file readable by others
- **WHEN** the key file's mode allows group or other to read it
- **THEN** `llm-pool doctor` reports it as a failure and `llm-pool ask` refuses to send

#### Scenario: The key never appears in output
- **WHEN** every command is run with `--json` and with a failing gateway, and the ledger and the audit log are read afterwards
- **THEN** the key's value appears in none of them

### Requirement: Global Claude configuration is never modified
The module SHALL add no hook fragment and no settings key, SHALL NOT write the Claude settings file, SHALL NOT set a base URL or a key in any persistent environment (shell profiles, service units, the settings file), and SHALL NOT run a gateway command that does so. Requests to the gateway SHALL be made by the module's own process.

#### Scenario: Installing with and without the module
- **WHEN** the toolkit is installed in two temporary homes, once with the `llm-pool` module and once without
- **THEN** the two Claude settings files are identical

#### Scenario: A day of commands
- **WHEN** every `llm-pool` command, the console included, has been run against a stub gateway
- **THEN** the hash of the Claude settings file is the one it had before, and no shell profile or service unit was created or changed

### Requirement: One pinned gateway version
The config piece SHALL name the gateway version the policy was evaluated with. When the running gateway reports another version, `llm-pool doctor` SHALL fail and every member SHALL be treated as `blocked` until the pin is updated.

#### Scenario: Gateway updated behind the module
- **WHEN** the gateway is updated and the pin is not
- **THEN** `llm-pool ask` answers "no eligible member" for every task kind and callers use the main model

### Requirement: The answering model is checked
`ask` SHALL compare the model the gateway's response names with the member's target. When they differ, the answer SHALL be discarded, the outcome SHALL be `wrong model`, and the member SHALL become `blocked` with that reason until `llm-pool doctor` passes for it again. The module SHALL create and change only combos whose name starts with `llm-pool-`.

#### Scenario: The gateway falls back to another model
- **WHEN** a request for one member is answered by a different model
- **THEN** the caller receives the "wrong model" code and uses the main model, and the ledger row names both models

### Requirement: The module works without the gateway
When the gateway is not installed, not running or not reachable within a bounded time, every command that needs it SHALL fail fast with a distinct exit code, and every caller SHALL treat that as "use the main model". No command SHALL wait longer than the configured timeout.

#### Scenario: Gateway stopped
- **WHEN** the watcher asks for a triage and the gateway is not running
- **THEN** the answer is `wake` within the configured timeout and the ledger records the outcome `unreachable`

### Requirement: Doctor reports the whole chain
`llm-pool doctor` SHALL check, without sending any private data: the gateway binary and version; the endpoint; the key file and its mode; that each `active` member answers a fixed public probe with its own model; and that the ledger is writable. It SHALL exit non-zero on any failure and list every finding in one run.

#### Scenario: One member's provider key expired
- **WHEN** a member's probe is refused for authentication
- **THEN** doctor reports that member, its state becomes `blocked` with the reason, and the other members keep their state

### Requirement: Doctor lists what the gateway sends elsewhere
`llm-pool doctor` SHALL also check each gateway feature that sends data elsewhere or rewrites a request: HTTP MCP transport, remote or cloud mode, telemetry, webhooks, log export and prompt compression for the module's key. A feature whose setting cannot be read SHALL be listed as "not verifiable", never as passed. When the machine's port registry is installed, doctor SHALL warn when the gateway's or the console's fixed port lies inside a leased block.

#### Scenario: A feature that cannot be read
- **WHEN** the gateway offers no way to read whether telemetry is on
- **THEN** doctor lists telemetry as "not verifiable" and its exit code is non-zero only if another check failed

#### Scenario: Compression is on for the module's key
- **WHEN** the gateway reports prompt compression enabled for the key the module uses
- **THEN** doctor reports it as a failure

### Requirement: The gateway is installed and connected by the developer
The installer SHALL NOT install the gateway, create a provider account or accept a provider's terms. The module's notes SHALL list the steps that are the developer's, the manifest SHALL declare the gateway binary as optional so that the installer warns when it is missing, and `llm-pool doctor` SHALL say exactly what is missing on that machine.

#### Scenario: Module enabled on a machine without the gateway
- **WHEN** `./install.sh install` runs with the `llm-pool` module enabled and no gateway binary
- **THEN** the module's files are installed, the installer prints the module's notes and the missing-binary warning, the dial is 0, and `llm-pool doctor` lists the gateway as not installed

### Requirement: State lives apart from the installed files
The module SHALL keep its decisions, observed state, ledger, audit log and (by default) the key file in one state directory under the Claude directory, replaceable with an environment variable so that tests run in a temporary home. It SHALL write nothing under the directories the installer manages. Uninstalling the toolkit SHALL leave the state directory; `llm-pool purge` SHALL remove it after confirmation.

#### Scenario: Reinstall after use
- **WHEN** the pool has been used and the toolkit is installed again
- **THEN** the install is not refused for edited files and the installer's drift check reports nothing for the module
