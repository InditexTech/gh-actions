# PyPI publishing action

This composite action publishes pre-built Python distributions with PyPI trusted
publishing. It rejects an empty directory, nested directories, files outside
`GITHUB_WORKSPACE`, and files other than wheels, `.tar.gz`, or `.zip` source
distributions before invoking PyPI's official action.

```yaml
- uses: InditexTech/gh-actions-publish/pypi@<immutable-sha>
  with:
    packages-dir: .release/pypi
```

The caller is responsible for constructing `packages-dir` from explicitly
declared artifacts. `validate-distributions` protects the publication boundary;
it cannot infer which package names a workspace intended to release.
The action accepts only the production PyPI and TestPyPI legacy endpoints, so a
workflow cannot redirect trusted-publishing credentials to an arbitrary index.

## TestPyPI smoke publishing

The manual `TestPyPI trusted publishing smoke` workflow requires a protected
`testpypi` GitHub environment and a TestPyPI trusted publisher configured for
this repository and environment. It publishes a uniquely versioned smoke
package only when manually dispatched. Production releases use the default
`https://upload.pypi.org/legacy/` endpoint.
