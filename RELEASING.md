# Releasing pymantic

Releases are published to PyPI by the `Release to PyPI` workflow
(`.github/workflows/release.yaml`) using PyPI trusted publishing. No API
token is stored in the repository; PyPI issues a short-lived token to the
workflow based on GitHub's OIDC identity for it.

## One-time setup

### PyPI: register the trusted publisher (project owner only)

Only a PyPI user with the **Owner** role on the `pymantic` project can do
this. Maintainers can upload releases but cannot change the project's
publishing settings.

1. Sign in to PyPI and open https://pypi.org/manage/project/pymantic/settings/publishing/
   (Your projects -> pymantic -> Manage -> Publishing).
2. Under "Add a new publisher", choose the GitHub Actions tab and fill in:

   | Field (as named in the PyPI docs)               | Value       |
   |-------------------------------------------------|-------------|
   | Repository owner's name                          | `norcalrdf` |
   | Repository's name                                | `pymantic`  |
   | Filename of the GitHub Actions workflow          | `release.yaml` |
   | GitHub Actions environment (optional, but strongly recommended) | `pypi` |

3. Click "Add". The publisher appears at the top of the page.

Reference: https://docs.pypi.org/trusted-publishers/adding-a-publisher/

The environment name must match `environment: pypi` in `release.yaml`, and
the workflow filename must match the file in `.github/workflows/`. If either
is renamed, update the publisher on PyPI.

### GitHub: create the `pypi` environment (repository admin)

Anyone with admin access to `norcalrdf/pymantic` can do this.

1. Open https://github.com/norcalrdf/pymantic/settings/environments and
   click "New environment". Name it `pypi` (exactly; PyPI checks the name).
2. Recommended protection rules:
   - **Required reviewers**: add the maintainers who should approve a
     release. Each publish run then pauses until one of them approves it.
   - **Deployment branches and tags**: restrict to protected branches or to
     tags matching your release tags, so only releases cut from `main` can
     publish.

No secrets are needed in the environment.

## Cutting a release

1. Bump the version in `src/pymantic/__init__.py` (`version = "X.Y.Z"`).
   `setup.cfg` reads it via `version = attr: pymantic.version`.
2. Commit and merge that change to `main`, and make sure CI is green.
3. Tag the release commit and push the tag:

       git tag -a vX.Y.Z -m "pymantic X.Y.Z"
       git push origin vX.Y.Z

4. Create a GitHub release for that tag at
   https://github.com/norcalrdf/pymantic/releases/new and click "Publish
   release". The `release` event with type `published` starts the workflow.
5. The workflow's `build` job builds the sdist and wheel and runs
   `twine check` on them. The `publish` job then waits for the `pypi`
   environment (including any required reviewer approval) and uploads
   `dist/` with `pypa/gh-action-pypi-publish`.
6. Check https://pypi.org/project/pymantic/ for the new version.

If the publish job fails after the build succeeded, fix the cause and re-run
the failed job from the Actions UI; the built artifact is reused. PyPI does
not allow re-uploading a version that already exists, so a genuinely bad
release needs a new version number.

## Repository protection

`.github/rulesets/` holds the repository rulesets as JSON so they can be
reviewed alongside the code:

- `main.json`: the default branch can only change through a pull request
  whose review threads are resolved and whose CI checks (the five test
  jobs and the lint job) pass against the latest `main`. Force pushes and
  deletion are blocked. No one is on the bypass list, including admins.
- `release-tags.json`: tags matching `v*` cannot be moved or deleted once
  pushed. A mistaken release tag therefore needs a new version number, which
  matches PyPI's own rule against re-uploading a version.

To apply or update one: repository Settings -> Rules -> Rulesets -> New
ruleset -> Import a ruleset, and choose the file. The status check names in
`main.json` come from the job names in `continuous-integration-workflow.yaml`;
if a job is renamed, update both.
