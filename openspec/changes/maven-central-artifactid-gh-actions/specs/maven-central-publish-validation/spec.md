# Spec Delta

## Purpose
Define how the maven-central action resolves declared packages to reactor modules before publishing. It is the local view of the shared contract.

## ADDED Requirements

### Requirement: Resolve by pom artifactId
The validator SHALL resolve each declared artifactId to the single module whose pom declares it, regardless of directory name.

#### Scenario: Flat reactor with prefixed artifactIds
- **WHEN** a directory `clients` declares `karatetools-clients` and the descriptor lists it
- **THEN** validation selects that module

### Requirement: Verify identity and ambiguity
The validator MUST NOT accept a directory-name match whose pom declares another artifactId, and SHALL fail on zero or multiple matches.

#### Scenario: Directory name matches but pom differs
- **WHEN** no module declares the artifactId
- **THEN** validation fails with `package artifactId was not found in the reactor`

### Requirement: Preserve existing layouts
Layouts where directory equals artifactId, including nested modules with ancestor aggregators, SHALL resolve exactly as before.

#### Scenario: Nested module
- **WHEN** `xxx-api-rest-stable` under `openapi-test` is declared
- **THEN** the selection includes the aggregator and the module

