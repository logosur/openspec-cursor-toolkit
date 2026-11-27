# Spec Delta — llm-pool-gateway

## Purpose

Defines how the `llm-pool` module finds, checks and uses an OmniRoute gateway on the machine without changing how any Claude session is configured.

## ADDED Requirements

### Requirement: The gateway is reached on loopback from configuration
The module SHALL read the gateway's URL from the `llm-pool` config piece and SHALL refuse a URL whose host is not a loopback address. The gateway key SHALL be read from a file outside the repository and outside the config piece, with mode 0600, and SHALL never be printed, logged or stored in the ledger.

#### Scenario: Non-loopback URL in the override
- **WHEN** the override sets the gateway URL to a host that is not loopback
- **THEN** every `llm-pool` command that would send a request exits with an error naming the key, and nothing is sent

#### Scenario: Key file readable by others
- **WHEN** the key file's mode allows group or other to read it
- **THEN** `llm-pool doctor` reports it as a failure and `llm-pool ask` refuses to send

### Requirement: Global Claude configuration is never modified
The module SHALL NOT write the Claude settings file, SHALL NOT set a base URL or a key in any persistent environment, and SHALL NOT run a gateway command that does so. Requests to the gateway SHALL be made by the module's own process.

#### Scenario: After installing and using the module
- **WHEN** the module is installed, the pool is used for a day and then uninstalled
- **THEN** the Claude settings file is byte-identical to what it was before

### Requirement: One pinned gateway version
The config piece SHALL name the gateway version the policy was evaluated with. When the running gateway reports another version, `llm-pool doctor` SHALL fail and every member SHALL be treated as `blocked` until the pin is updated.

#### Scenario: Gateway updated behind the module
- **WHEN** the gateway is updated and the pin is not
- **THEN** `llm-pool ask` answers "no eligible member" for every task kind and callers use the main model

### Requirement: The module works without the gateway
When the gateway is not installed, not running or not reachable within a bounded time, every command that needs it SHALL fail fast with a distinct exit code, and every caller SHALL treat that as "use the main model". No command SHALL wait longer than the configured timeout.

#### Scenario: Gateway stopped
- **WHEN** the watcher asks for a triage and the gateway is not running
- **THEN** the answer is `wake` within the configured timeout and the ledger records the outcome `unreachable`

### Requirement: Doctor reports the whole chain
`llm-pool doctor` SHALL check, without sending any private data: the gateway binary and version, the endpoint, the key file, that each `active` member answers a fixed public probe, that the gateway's HTTP MCP transport and remote mode are not exposed beyond loopback, and that the ledger is writable. It SHALL exit non-zero on any failure and list every finding in one run.

#### Scenario: One member's provider key expired
- **WHEN** a member's probe is refused for authentication
- **THEN** doctor reports that member, its state becomes `blocked` with the reason, and the other members keep their state

### Requirement: The gateway is installed and connected by the developer
The installer SHALL NOT install the gateway, create a provider account or accept a provider's terms. It SHALL print what is missing and how the developer provides it.

#### Scenario: Module enabled on a machine without the gateway
- **WHEN** `./install.sh install` runs with the `llm-pool` module enabled and no gateway binary
- **THEN** the module's files are installed, the dial is 0 and the installer prints the steps that are the developer's
