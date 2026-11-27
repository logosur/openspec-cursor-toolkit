# store-access

## ADDED Requirements

### Requirement: Providers and apps are named in configuration

The `stores` command SHALL take each provider's settings (ids, key file path, console user index, endpoints) and its apps (alias, package or bundle id, console app id) from the config piece `stores`, and the repository SHALL ship that piece with no app and no key.

#### Scenario: Apps listed without credentials

- **WHEN** `stores apps` runs with apps configured and no key file
- **THEN** it lists each app with its provider, alias and identifier, and exits 0

#### Scenario: Nothing configured

- **WHEN** `stores apps` runs with the shipped defaults
- **THEN** it prints that no app is configured and which file to add one to, and exits 0

#### Scenario: Unreadable configuration

- **WHEN** the config piece is not valid JSON
- **THEN** the command names the file in one line, prints no traceback and behaves as if nothing were configured

### Requirement: Doctor names exactly what is missing

`stores doctor [PROVIDER]` SHALL check every prerequisite of a provider in order, print each as `ok` or `missing` with the single action that fixes it, and exit 3 if any is missing. A check that can only hold if an earlier one does (the key file's existence, privacy and form after its path) SHALL NOT be printed once that earlier one is missing.

#### Scenario: No key file

- **WHEN** the provider's key file path is empty or the file does not exist
- **THEN** that line says `missing`, names the setting to fill, no later line about that key file is printed, and no network call is made

#### Scenario: Key file readable by others

- **WHEN** the key file is readable by group or others
- **THEN** that line says `missing` with the required mode, and the key is not used

#### Scenario: Key valid but access not granted

- **WHEN** `--live` is given, a token is obtained and the service answers that the caller has no permission
- **THEN** the line for access says `missing` and names where the account owner grants it

#### Scenario: Signing tool absent

- **WHEN** the `openssl` binary is not on the machine
- **THEN** the line for signing says `missing`

### Requirement: Nothing in a store is changed

The `stores` command SHALL only read. It SHALL offer no subcommand that uploads, releases, changes a rollout, edits a listing, answers a review or submits for review.

#### Scenario: Requests are limited to an allow-list

- **WHEN** every read subcommand runs against the simulated services
- **THEN** the only non-GET requests are the token exchange and, for Google Play, opening and deleting an edit, and no edit is ever committed

#### Scenario: Edit cleaned up

- **WHEN** a Google Play read that needs an edit fails midway
- **THEN** the edit is still deleted

### Requirement: Google Play reads

For a configured Google Play app the command SHALL read its tracks and releases, its recent reviews and its store listing.

#### Scenario: Tracks

- **WHEN** `stores tracks APP` runs
- **THEN** each line gives a track, the release name, its status, its version codes and its rollout fraction when present

#### Scenario: Reviews window

- **WHEN** `stores reviews APP` runs
- **THEN** the output states that the service only returns the last week of reviews

#### Scenario: Listing

- **WHEN** `stores listing APP --lang LANG` runs
- **THEN** it prints the title, the short description and the length of the full description for that language

### Requirement: App Store Connect reads

For the App Store Connect provider the command SHALL read the apps of the team, and for an app its versions with their state, its builds with their processing state, and its review submissions.

#### Scenario: Versions

- **WHEN** `stores versions APP` runs
- **THEN** each line gives the platform, the version string and its store state

#### Scenario: Builds

- **WHEN** `stores builds APP` runs
- **THEN** each line gives the build number, its upload date, its processing state and whether it expired

#### Scenario: Token lifetime

- **WHEN** a token is signed for this provider
- **THEN** it expires at most 15 minutes after it was issued

### Requirement: Console addresses are built, not remembered

`stores url PROVIDER [APP] [PAGE]` SHALL print the web console address for a provider, an app or a page of an app, built from the configured ids, and SHALL work without credentials.

#### Scenario: App page

- **WHEN** `stores url play APP releases` runs with a developer id, a console app id and a console user index configured
- **THEN** it prints one address containing those three values and exits 0

#### Scenario: Unknown page

- **WHEN** the page name is not in the page table
- **THEN** it is appended unchanged to the app's address

#### Scenario: Missing id

- **WHEN** the id needed for the address is not configured
- **THEN** the command names the setting to fill and exits 3

### Requirement: The public listing is checked without credentials

`stores public APP` SHALL report whether the app's public store page exists, using only the store's public web endpoints and the configured package or bundle id.

#### Scenario: Published app

- **WHEN** the public page of a Google Play app answers 200
- **THEN** the command prints `public` with the page address and exits 0

#### Scenario: Not published

- **WHEN** the public page answers 404, or the App Store lookup returns no result
- **THEN** the command prints `not public` and exits 4

#### Scenario: No key needed

- **WHEN** the provider has no key file configured
- **THEN** `stores public` still answers

### Requirement: Keys and tokens never reach the output

The command SHALL never print a private key, a client secret or a token, in any mode, and SHALL offer no subcommand that hands a token to another program.

#### Scenario: Token absent from every output

- **WHEN** every subcommand runs against the simulated services, in text and in JSON mode, with and without errors
- **THEN** neither the token returned by the simulated service nor any line of the key file appears in what is printed

#### Scenario: A redirect never carries a token

- **WHEN** a request that carries credentials (a bearer token or a signed assertion) is answered with a redirect
- **THEN** the redirect is not followed, the target never receives the credentials, and the command prints one error line and exits 1

#### Scenario: Not connected

- **WHEN** a read runs for a provider whose `doctor` would report something missing
- **THEN** it prints one line pointing to `stores doctor PROVIDER` and exits 3

### Requirement: Output is bounded and errors are plain

The command SHALL print one line per item of at most 160 characters by default, offer `--json`, and turn a service error into one line.

#### Scenario: Service error

- **WHEN** the service answers with an error status
- **THEN** one line gives the status and the service's message, and the exit code is 3 for a permission error, 4 for not found and 1 otherwise

#### Scenario: Limit

- **WHEN** a read returns more items than the limit (default 20)
- **THEN** that many lines are printed and the total is stated

### Requirement: The command checks itself offline

`stores self-test` SHALL exercise signing, the token exchange, one read per provider and the console addresses against a simulated service on the loopback interface, with keys generated for the run.

#### Scenario: Self-test passes

- **WHEN** `stores self-test` runs on a machine with `openssl` and nothing configured
- **THEN** it exits 0 without contacting any external host

#### Scenario: Signature verified

- **WHEN** the repository's tests sign a token with each algorithm
- **THEN** the signature verifies against the matching public key

#### Scenario: Elliptic-curve signature in token form

- **WHEN** a token is signed with the elliptic-curve algorithm
- **THEN** its signature segment decodes to exactly 64 bytes, and those bytes, re-encoded as a DER signature, verify against the public key
