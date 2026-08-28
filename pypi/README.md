# PyPI trusted-publishing validation action

This composite action has one responsibility: **validate** an already-built,
flat set of Python distributions against the PyPI trusted-publishing boundary.
It does not publish. Building and testing packages belong in an earlier
unprivileged job; the actual upload is performed by the caller's own job step
(see below). The action has no outputs.

```yaml
permissions:
  contents: read

jobs:
  publish:
    runs-on: ubuntu-24.04
    environment: pypi
    permissions:
      id-token: write
    steps:
      - name: Download distributions produced by the build job
        uses: actions/download-artifact@<immutable-sha>
        with:
          name: python-distributions
          path: dist

      # 1) Governed boundary check (this action).
      - name: Validate distributions
        uses: InditexTech/gh-actions/pypi@<immutable-sha>
        with:
          packages-dir: dist
          attestations: 'true'
          skip-existing: 'true'
          verify-metadata: 'true'

      # 2) Publish directly with the upstream PyPA action — NOT nested in a
      #    composite. Forward exactly the values validated above.
      - name: Publish distributions
        uses: pypa/gh-action-pypi-publish@<immutable-sha>
        with:
          packages-dir: dist
          attestations: true
          skip-existing: true
          verify-metadata: true
```

## Public contract

The action has no outputs and accepts exactly these inputs. Every input is
validated here and must be forwarded unchanged to `pypa/gh-action-pypi-publish`
in the caller's publish step:

| Input | Required | Default | Contract |
| --- | --- | --- | --- |
| `packages-dir` | Yes | — | Directory of pre-built distributions inside `GITHUB_WORKSPACE`. |
| `repository-url` | No | `https://upload.pypi.org/legacy/` | Exactly the official PyPI or TestPyPI legacy endpoint. |
| `attestations` | No | `true` | Exact boolean the caller will pass to PEP 740 attestations. |
| `skip-existing` | No | `false` | Exact boolean the caller will pass for duplicate-file tolerance. |
| `verify-metadata` | No | `true` | Exact boolean the caller will pass for upstream metadata verification. |

Validation is mandatory and fails the job before any publish step runs when:

- `id-token: write` is unavailable;
- a boolean is not exactly `true` or `false`;
- the destination is not the official PyPI or TestPyPI endpoint;
- `packages-dir` escapes the workspace or contains a symbolic path component;
- the directory is empty, nested, or contains symlinks, special files, or
  anything other than wheels, `.tar.gz`, or `.zip` source distributions.

The validator never reads or logs the OIDC request token. The caller remains
responsible for selecting the intended package names before creating the
artifact; file extensions alone cannot establish package ownership.

## Why the publish step is not part of this action

The upstream `pypa/gh-action-pypi-publish` action generates and runs a
Docker-based action at runtime. When it is invoked from **inside another
composite action**, GitHub derives the generated image name from the enclosing
composite's repository — here `InditexTech/gh-actions` — and rejects it with
`docker: invalid reference format: repository name must be lowercase`. The
project also does not support being invoked from another composite action as
part of its public compatibility contract.

An earlier revision wrapped the PyPA publish step inside this composite and
gated it behind a protected TestPyPI canary in `internal-ops`. That canary
proved the nested-composite path fails, so publishing was moved out: callers
invoke `pypa/gh-action-pypi-publish` **directly as a job step**, where the
generated image name derives from the lowercase upstream repository and the
casing failure cannot occur.

Un-nesting does not affect OIDC. A composite runs inline in the caller's job, so
the trusted-publisher `workflow_ref` binding was always the caller's workflow
file; moving the publish step out of this composite leaves that binding
unchanged. The Node OIDC POC separately confirmed that an external composite
preserves the consumer workflow's `job_workflow_ref`.

## Support boundary

Only GitHub-hosted GNU/Linux jobs are supported for the downstream PyPA publish
step, which uses Docker. Self-hosted runners, job containers, reusable-workflow
publication, building in the privileged publish job, and non-PyPI indices are
outside this action's contract.
