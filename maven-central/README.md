# Maven Central publishing action

This composite action has one responsibility: sign and publish an
already-built, checked-out Maven reactor to the Central Portal. Compiling,
testing, and verifying the reactor belong in an earlier unprivileged job.

The consumer `pom.xml` deliberately carries **no** publish plumbing — no
`distributionManagement`, no `central-publishing-maven-plugin`, no
`maven-gpg-plugin`. The action injects the governed publish plugins into an
ephemeral copy of the reactor POM for this deploy only, and writes an ephemeral
`settings.xml`. Nothing it writes is ever committed back to the consumer.

```yaml
permissions:
  contents: read

jobs:
  publish:
    runs-on: ubuntu-24.04
    environment: maven-central
    # Set the credentials on the job so they reach the composite's run steps
    # through the runner process environment. Step-level env on a `uses:` step
    # is not a reliable channel into a composite action.
    env:
      MAVEN_CENTRAL_USERNAME: ${{ secrets.MAVEN_CENTRAL_USERNAME }}
      MAVEN_CENTRAL_PASSWORD: ${{ secrets.MAVEN_CENTRAL_PASSWORD }}
      CI_GPG_SECRET_KEY: ${{ secrets.CI_GPG_SECRET_KEY }}
      CI_GPG_SECRET_KEY_PASSWORD: ${{ secrets.CI_GPG_SECRET_KEY_PASSWORD }}
    steps:
      - name: Check out the released commit
        uses: actions/checkout@<immutable-sha>
        with:
          persist-credentials: false

      - name: Set up the governed JDK and Maven
        uses: actions/setup-java@<immutable-sha>
        with:
          distribution: temurin
          java-version: '25'

      - name: Publish to Maven Central
        uses: InditexTech/gh-actions/maven-central@<immutable-sha>
        with:
          working-directory: code
          project-type: single
```

## Public contract

The action has no outputs and accepts exactly these inputs:

| Input | Required | Default | Contract |
| --- | --- | --- | --- |
| `working-directory` | Yes | — | Reactor root relative to `GITHUB_WORKSPACE`; the parent `pom.xml` lives here. |
| `project-type` | Yes | — | Exactly `single` or `monorepo`. |
| `packages` | No | — | Comma-separated released module directories for an independent monorepo release. Empty publishes the whole reactor. |
| `strategy` | No | `maven-central-gpg` | Only `maven-central-gpg` is implemented; `oidc` is a reserved seam and is rejected until it ships. |
| `auto-publish` | No | `true` | Exact boolean. `true` releases once the Portal validates the bundle; `false` stops at a validated deployment awaiting a manual release. |

Credentials are **not** action inputs. The caller sets them on the publish
job's environment from organization secrets, and the action reads them from the
process environment:

| Environment variable | Purpose |
| --- | --- |
| `MAVEN_CENTRAL_USERNAME` | Central Portal token user name. |
| `MAVEN_CENTRAL_PASSWORD` | Central Portal token password. |
| `CI_GPG_SECRET_KEY` | ASCII-armored GPG private key imported for signing. |
| `CI_GPG_SECRET_KEY_PASSWORD` | Passphrase for that GPG key. |

The ephemeral `settings.xml` references `${env.MAVEN_CENTRAL_USERNAME}` and
`${env.MAVEN_CENTRAL_PASSWORD}` so Maven interpolates them at runtime; the token
**values** are never serialized to disk. The GPG passphrase reaches the signing
plugin through `MAVEN_GPG_PASSPHRASE` in the deploy step's environment and is
likewise never written to disk.

Validation is mandatory and fails before any signing or publication when:

- any of the four required credentials is absent or empty;
- `strategy` is `oidc` (the reserved seam is not implemented) or any value other
  than `maven-central-gpg`;
- `project-type` is not exactly `single` or `monorepo`;
- `auto-publish` is not exactly `true` or `false`;
- `working-directory` escapes the workspace, is absolute, or contains a symbolic
  path component, or the reactor has no `pom.xml`;
- `packages` is supplied for a `single` project, or names anything other than a
  single-segment reactor module directory that contains a `pom.xml`.

The validator never reads or logs any credential value.

## Support boundary

The caller is responsible for checking out the released commit and setting up
the governed JDK and Maven (Temurin 25 LTS) before invoking the action; the
action installs no toolchain. Only GitHub-hosted GNU/Linux jobs are supported.

For a `monorepo` with an independent release strategy, `packages` selects the
released reactor modules (`mvn -pl <selected> deploy`); each inherits the
injected `central-publishing` extension from the parent. A `single` project and
a locked-step `monorepo` deploy the whole reactor.

`oidc` is a reserved strategy seam: the value is accepted by the input schema but
rejected at validation until keyless signing ships, so the OIDC path can be
added additively without changing the public contract.

## Promotion gate

Local tests prove the boundary guard, the ephemeral injection, and the
deploy-phase wiring. They do not perform a live upload. A new `maven-central`
action SHA must not be promoted to consumers until the protected Maven canary in
`internal-ops` publishes successfully from that exact commit.
