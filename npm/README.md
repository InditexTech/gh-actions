# npm publishing action

This composite action has one responsibility: publish already-packed npm
tarballs through npm trusted publishing. Building, testing, and packing belong in
an earlier unprivileged job; this action only ships the pre-built `.tgz`
artifact, so nothing in the package can run code in the privileged publish stage.

```yaml
permissions:
  contents: read

jobs:
  publish:
    runs-on: ubuntu-24.04
    environment: npm-registry
    permissions:
      contents: read
      id-token: write
    env:
      # Fallback for a brand-new package only; the OIDC path needs no token.
      NPM_TOKEN: ${{ secrets.NPM_TOKEN }}
    steps:
      - name: Download tarballs produced by the build job
        uses: actions/download-artifact@<immutable-sha>
        with:
          name: npm-distributions
          path: ${{ runner.temp }}/publish-dist

      - name: Publish packages
        uses: InditexTech/gh-actions/npm@<immutable-sha>
        with:
          working-directory: .
          project-type: single
          artifact-directory: ${{ runner.temp }}/publish-dist
```

## Public contract

The action has no outputs and accepts exactly these inputs:

| Input | Required | Default | Contract |
| --- | --- | --- | --- |
| `working-directory` | Yes | — | Project root relative to `GITHUB_WORKSPACE`; the `package.json` / workspaces root. |
| `project-type` | Yes | — | Exactly `single` (one package) or `workspaces` (declared members). |
| `artifact-directory` | Yes | — | Directory of pre-built `.tgz` tarballs inside `GITHUB_WORKSPACE` or `RUNNER_TEMP`. |
| `dist-tag` | No | `latest` | Exactly `next` (snapshots) or `latest` (releases). |
| `registry-url` | No | `https://registry.npmjs.org/` | Reserved seam for a governed private registry; defaults to the public npm registry. |

`NPM_TOKEN` is **not** an input. When a brand-new package cannot yet use trusted
publishing, the action reads `NPM_TOKEN` from the job environment — supply it
only from the reviewer-gated publish Environment, never an org-wide or plain
repository secret. It is written only to a temporary `.npmrc` that a trap removes
on exit and is unreachable from the unprivileged build stage.

Validation is mandatory and fails **before anything is published** when:

- neither `id-token: write` (trusted publishing) nor an `NPM_TOKEN` fallback is available;
- `project-type` is not exactly `single` or `workspaces`;
- `dist-tag` is not exactly `next` or `latest`;
- `working-directory` or `artifact-directory` escapes its allowed root or contains a symbolic path component;
- the artifact directory is empty, nested, or holds symlinks, special files, or anything other than `.tgz` tarballs;
- `project-type` is `single` but the artifact directory holds more than one tarball.

The validator never reads or logs the OIDC request token or `NPM_TOKEN`. Every
`npm publish` runs with `--ignore-scripts`, so nothing in the artifact re-runs a
consumer lifecycle in this privileged stage. Provenance is enabled
only when the repository is public and the OIDC path applies; a private or
unknown visibility degrades safely to publishing without provenance rather than
failing.

## Support boundary

Only GitHub-hosted GNU/Linux jobs (`ubuntu-24.04`) are supported. The action
provisions its own Node toolchain (`actions/setup-node`, Node 22) and raises npm
to the trusted-publishing floor, so the calling job supplies only the pre-built
artifact and `id-token: write` — never a Node setup of its own.

Invoke it only from an `id-token: write` publish job of the single registered
top-level workflow `code-npm_node-publish-release-and-snapshot.yml`. That
top-level file is the npm trusted-publisher binding: the OIDC claim every npm
publish presents identifies that one workflow, for both the snapshot (`next`) and
release (`latest`) lanes. Self-hosted runners, job containers, building or packing
in the privileged publish job, and non-npm registries are outside this action's
contract.

The successful OIDC path — an external composite preserving the caller workflow's
`workflow_ref` and publishing to the npm registry — was proven in the Node
registry PoC. A new `npm` action commit must still pass the protected npm canary
in `internal-ops` before promotion to consumers.
