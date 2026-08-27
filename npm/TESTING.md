# npm action test coverage

The repository owns only tests for the isolated action implementation and its
public input contract. Protected OIDC publication, registry behavior, provenance,
the `NPM_TOKEN` fallback, and cross-repository consumers remain in the
`internal-ops` control plane.

| # | Area | Applicability and evidence |
| ---: | --- | --- |
| 1 | Responsibility and scope | **Covered.** `action.yml` validates and publishes pre-built `.tgz` tarballs only. The README excludes build, test, and packing. Contract tests require the catalog to expose exactly this action and no outputs. |
| 2 | Public contract | **Covered.** `action-validator` checks metadata syntax. `test_npm_contract.py` fixes the exact inputs, defaults, descriptions, README table, and absence of outputs. |
| 3 | Input validation | **Covered.** Subprocess tests exercise missing paths, empty/nested directories, exact `project-type`/`dist-tag` allowlists, traversal, symlinks, special files, unsupported artifacts, and the single-project tarball-count rule. |
| 4 | Functional correctness | **Locally covered; live gate required.** CI invokes `uses: ./npm` and proves the action fails before publication when no OIDC and no `NPM_TOKEN` are available. The protected npm canary in `internal-ops` proves the successful OIDC path from the exact commit. |
| 5 | Security | **Covered for the local boundary.** Inputs reach shell through environment variables, `project-type`/`dist-tag` allowlists reject injection, lexical and resolved path checks prevent escape, `lstat` rejects symlinks and special files, `--ignore-scripts` blocks lifecycle execution, and Zizmor audits the composite. There is no dependency manifest for dependency audit. |
| 6 | Permissions and credentials | **Covered.** The action accepts no token input, checks for the runner-provided OIDC environment or an ambient `NPM_TOKEN`, never logs either credential, and documents job-scoped `id-token: write`. The protected canary proves real minimal-permission OIDC trusted publishing. |
| 7 | Idempotency and side effects | **Contract covered; live gate required.** The registry-existence probe selects OIDC for known packages and the Environment-scoped `NPM_TOKEN` fallback only for brand-new ones. The protected canary publishes a snapshot version and re-runs from the same commit. |
| 8 | Reliability and cleanup | **Covered for the local boundary.** The temporary `.npmrc` carrying the registry and any fallback token is created with `chmod 600` and removed by an `EXIT` trap; nothing is persisted. No locks, child daemons, or `pre`/`post` lifecycle. |
| 9 | Portability | **Covered within the supported envelope.** Only GitHub-hosted GNU/Linux (`ubuntu-24.04`) is supported. Tests cover absolute paths, spaces, read-only files, symlinks, and POSIX special files; macOS/Windows execution is intentionally unsupported. |
| 10 | Determinism and dependencies | **Covered.** All CI actions and the composite's own `actions/setup-node` use immutable SHAs. The runtime validator uses only the Python standard library; the publish step provisions Node 22 through the pinned `setup-node`, raises npm to the `>= 11.5.1` trusted-publishing floor, and otherwise uses only pre-installed `tar` and `curl`. `action-validator` is versioned and downloaded with a fixed SHA-256. |
| 11 | Observability and errors | **Covered.** Failures use exit code 1 and the stable `npm publish validation failed:` prefix, explain the rejected boundary, keep stdout empty, and never expose the OIDC request token or `NPM_TOKEN`. |
| 12 | Performance | **No separate benchmark required.** Validation performs one sorted, linear directory scan with no network or API calls. Publication duration is controlled by `npm` and measured by the protected canary. |
| 13 | Maintainability, tests, and releases | **Covered.** Runtime validation is isolated in one typed stdlib module, contract and adversarial tests are separate, Actionlint/Zizmor/action-validator are blocking, and consumers must use an immutable catalog commit. |

## Promotion gate

The Node OIDC PoC proved that an external composite preserves the caller
workflow's `workflow_ref`, so an npm publish delegated through a publish job of
the single registered top-level `code-npm_node-publish-release-and-snapshot.yml`
presents that one trusted-publisher identity across both the snapshot and release
lanes. The local suite does not reach the registry: it proves the fail-closed
boundary only. A new `npm` action SHA must not be promoted until the protected
npm workflow in `internal-ops` succeeds for that exact SHA.
