# multiagent-apply-validation Specification

## Purpose

This repository supports unattended multi-agent execution for general tasks and OpenSpec apply/validation work.

## Requirements

### Requirement: Slash command starts unattended multi-agent execution

The repository SHALL provide a Cursor command `/multiagente [task]` that interprets the request as unattended multi-agent execution until all acceptance criteria are completed and verified, or until a genuine human blocker is encountered.

#### Scenario: A task is provided inline

- **WHEN** the user runs `/multiagente fix the failing checkout flow`
- **THEN** the agent treats the remaining text as the task
- **AND** follows the multi-agent skill before substantial work
- **AND** does not stop for ordinary fixable failures

#### Scenario: A task is missing

- **WHEN** the user runs `/multiagente` with no task body
- **THEN** the agent asks once for the task
- **AND** does not invent the task scope

### Requirement: OpenSpec apply cannot hide partial state

OpenSpec apply commands SHALL read the multi-agent skill, OpenSpec status, apply instructions, context files, and task/spec artifacts before implementation when those files or commands are available.

#### Scenario: Apply finishes all tasks

- **WHEN** all pending OpenSpec tasks are implemented and verified
- **THEN** the final response includes verification evidence
- **AND** reports all tasks complete

#### Scenario: Apply cannot finish

- **WHEN** any OpenSpec task remains unchecked or any required behavior is unverified
- **THEN** the final response lists the remaining tasks
- **AND** states the blocker or reason
- **AND** gives the smallest next action
- **AND** does not imply the apply is complete

### Requirement: Verification reports explicit evidence

OpenSpec verification commands SHALL separate proven facts from unknown or not-verifiable claims.

#### Scenario: Verification has incomplete evidence

- **WHEN** a required gate has no executed command, test, browser check, or other evidence
- **THEN** the verdict for that gate is `NOT VERIFIABLE` or `BLOCKED`
- **AND** the overall verdict is not `PASS`
