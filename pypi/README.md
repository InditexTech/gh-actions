# PyPI publishing action

This composite action has one responsibility: publish an already-built, flat
set of Python distributions through PyPI trusted publishing. Building and
testing packages belong in an earlier unprivileged job.

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

      - name: Publish distributions
        uses: InditexTech/gh-actions/pypi@<immutable-sha>
        with:
          packages-dir: dist
```

## Public contract

The action has no outputs and accepts exactly these inputs:

| Input | Required | Default | Contract |
| --- | --- | --- | --- |
| `packages-dir` | Yes | — | Directory of pre-built distributions inside `GITHUB_WORKSPACE`. |
| `repository-url` | No | `https://upload.pypi.org/legacy/` | Exactly the official PyPI or TestPyPI legacy endpoint. |
| `attestations` | No | `true` | Exact boolean controlling PEP 740 attestations. |
| `skip-existing` | No | `false` | Exact boolean controlling duplicate-file tolerance. |
| `verify-metadata` | No | `true` | Exact boolean controlling upstream metadata verification. |

Validation is mandatory and fails before publication when:

- `id-token: write` is unavailable;
- a boolean is not exactly `true` or `false`;
- the destination is not the official PyPI or TestPyPI endpoint;
- `packages-dir` escapes the workspace or contains a symbolic path component;
- the directory is empty, nested, or contains symlinks, special files, or
  anything other than wheels, `.tar.gz`, or `.zip` source distributions.

The validator never reads or logs the OIDC request token. The caller remains
responsible for selecting the intended package names before creating the
artifact; file extensions alone cannot establish package ownership.

## Support boundary

Only GitHub-hosted GNU/Linux jobs are supported because the pinned upstream
PyPA publisher uses Docker. Self-hosted runners, job containers, reusable
workflow publication, building in the privileged publish job, and non-PyPI
indices are outside this action's contract.

The upstream `pypa/gh-action-pypi-publish` project does not support being
invoked from another composite action. InditexTech keeps this narrow wrapper as
a governed exception because it performs no build or dependency installation
and is used only in an isolated OIDC publish job. The exact nested-composite
path must pass the protected TestPyPI canary in `internal-ops` before a new
wrapper commit is promoted to consumers.

OIDC itself is not the uncertainty: an external composite action was proven to
preserve the consumer workflow's `job_workflow_ref` and publish successfully in
the Node registry POC. The protected PyPI canary exists to prove the additional
PyPA nesting behavior.
