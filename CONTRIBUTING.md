# Start here (new contributors)

A short path through the project. About an hour of reading before your first change.

## 0. Your own secrets and keys (set these first)

This repository contains **no secrets**: no tokens, passwords, API keys or personal contacts, in its files or in its GitHub settings. Each person who runs it sets **their own** values, pasted directly into GitHub or Home Assistant, never into a file, an issue or a chat.

| What | Where to set it | Needed for | Without it |
|---|---|---|---|
| **GitHub read-only token** (fine-grained, read access to this repository only, with an expiry date) | Home Assistant → Settings → Apps → App store → ⋮ → Repositories, inside the address `https://x-access-token:<TOKEN>@github.com/<OWNER>/<REPOSITORY>#staging` | Letting Home Assistant install the App from a **private** copy | Not needed if your copy is public |
| **`WIKIMEDIA_CONTACT`**: an email address or URL where you can be reached | GitHub → your repository → Settings → Secrets and variables → Actions → **New repository secret** (a *secret*, not a *variable*: GitHub hides secrets in logs) | The "Bird illustrations" workflow; Wikimedia asks automated downloaders to identify themselves | The workflow still runs, but Wikimedia throttles it heavily |
| **`XENO_CANTO_API_KEY`**: your personal key from a free xeno-canto account | Same place, as a repository secret | Downloading the reference bird songs ("tap to listen") | The library is built without songs |

Nothing else is needed: the GBIF statistics and the Perch model need no account or key, and the App itself never uses a cloud service.

If a value ever leaks, revoke it at its source (GitHub token settings, your xeno-canto account) and set a new one. More detail: [docs/install.md](docs/install.md) (sections 1 and 6) and [docs/security.md](docs/security.md).

## 1. Read, in this order

1. [README.md](README.md): what the App does, its status, credits and licences.
2. [AGENTS.md](AGENTS.md): the **hard rules** (branches, secrets, no audio ever kept, privacy of the household, licences) and the technical facts of the codebase. It applies to humans as well as AI agents.
3. [docs/architecture/README.md](docs/architecture/README.md): sections 1, 2 and 4 give the big picture and the App's inside; the later sections cover one feature each.
4. [docs/security.md](docs/security.md): section 1 (threat model) and the latest review at the end.
5. [docs/install.md](docs/install.md): how the App reaches a Home Assistant, for when you need it.

Everything else is listed in [docs/README.md](docs/README.md).

## 2. Run it on your machine

```bash
git clone --recurse-submodules <repository address>   # tests/data is a submodule (test audio)
pip install -e .[dev,gui-tests]                       # gui-tests brings Pillow, used by the screen tests
ruff check . && ruff format --check .
python -m pytest tests/mouflon tests/illustrations     # our own tests; the full suite is `python -m pytest`
```

If you cloned without `--recurse-submodules`, run `git submodule update --init --recursive`. A few tests download the BirdNET models on first use (several hundred MB); they skip when the download is not possible. The full setup, including the model pre-download, is in [docs/testing.md](docs/testing.md).

To see something without a Raspberry Pi:

- detections page: [docs/preview/index.html](docs/preview/index.html) (regenerate with the command in `AGENTS.md`);
- e-ink demo screen: [docs/screen-preview/preview.html](docs/screen-preview/preview.html).

## 3. Where things are

| Path | What it is |
|---|---|
| `app/` | The Home Assistant App: `config.yaml`, `Dockerfile`, the Python package `app/src/mouflon_population/`, the bundled bird library, fonts, `CHANGELOG.md` |
| `tools/illustrations/` | Builds the bird library on GitHub's servers (Wikimedia Commons, Wikidata, xeno-canto) and installs it into `app/library/` |
| `tools/screen_preview/` | Live preview of the e-ink screen while you edit (VS Code task) |
| `tests/mouflon/`, `tests/illustrations/`, `tests/e2e/` | Our unit tests, library tests, and the end-to-end test with a real Home Assistant |
| `docs/` | Our docs (Markdown) and diagrams; `docs/work/` holds the team's work-file template (past work files are internal and not included) |
| `birdnet_analyzer/`, most of `docs/*.rst` | The imported BirdNET-Analyzer code and docs, kept as they are (see [UPSTREAM.md](UPSTREAM.md)) |

## 4. Making a change

- Work on a branch merged into `staging`. Never push to `main`.
- Update the affected docs in the same commit, and re-render the diagrams with `python scripts/render_diagrams.py` (needs the Mermaid CLI).
- Household-facing text is in French and lives in `app/src/mouflon_population/i18n.py` (with English); logs and developer docs are in English. This is why `app/CHANGELOG.md` is in French from 0.5.0 on.
- Reference the Jira key (project MOUL) in commit messages.
- Describe the product generically: no detail about the owner's home, devices, network, location or people (rule 10).

## 5. Licences, in short

The code is MIT ([LICENSE](LICENSE), the BirdNET team). The BirdNET 2.4 and geo models are **non-commercial only** (CC BY-NC-SA 4.0): this is a personal, non-commercial project, and any commercial use, including inside a company, needs a new licence review first. Bird drawings are public domain, each with its credit line.

## Test data submodule (from the upstream project)

`tests/data` points to `birdnet-team/birdnet-test-data` at a pinned commit. To move it to a newer commit:

```bash
cd tests/data
git pull origin main
cd ..
git add data
git commit -m "Update testdata"
```
