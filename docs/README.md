# Documentation index

## Mouflon Population (our docs)

| Page | What it is |
|---|---|
| [../README.md](../README.md) | What the project is, status, credits, licences |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | **Start here** for a new contributor: reading order, running the tests, where things are |
| [architecture/README.md](architecture/README.md) | Architecture proposal: Raspberry Pi + Home Assistant, cameras, screen, test environments |
| [security.md](security.md) | Threat model and security review, findings ranked |
| [testing.md](testing.md) | How to run the tests and the latest test reports |
| [install.md](install.md) | Installation and set-up: repository access token, MQTT, camera streams, dashboard |
| [../app/DOCS.md](../app/DOCS.md) | The household user guide shown in Home Assistant: settings, statuses, privacy, demo and test mode |
| [home-assistant/birds-dashboard.yaml](home-assistant/birds-dashboard.yaml) | Reference copy of the "Birds" dashboard in Home Assistant (and the Outdoor section) |
| [illustrations/before-after.html](illustrations/before-after.html) | The 33 multi-species plates of the full library before (whole plate) and after their crop box (0.6.0), also as a PNG |
| [illustrations/contact-sheet.html](illustrations/contact-sheet.html) | Full contact sheet of the installed library (0.6.0), with credits and crop sources; also as an image (`contact-sheet.jpg`) |
| [illustrations/coverage.md](illustrations/coverage.md) | Coverage report of the full library: species with a plate, missing, weak matches |
| [screen-preview/preview.html](screen-preview/preview.html) | Preview of the e-ink demo screen, from sample data |
| [preview/index.html](preview/index.html) | Preview of the detections page, from sample data |
| [work/](work/) | Shared work files of the product team, one per piece of work |
| [diagrams/README.md](diagrams/README.md) | All diagrams as images (generated) |
| [../AGENTS.md](../AGENTS.md) | Rules and technical facts for developers and AI agents |
| [../SECURITY.md](../SECURITY.md) | How to report a security problem |
| [../UPSTREAM.md](../UPSTREAM.md) | Where the code comes from |

## Diagrams

Diagrams are written in Mermaid inside the Markdown pages (the text is the reference). After changing one, render them again and commit the result:

```
python scripts/render_diagrams.py
```

This needs the Mermaid command-line tool (`npm install -g @mermaid-js/mermaid-cli`).

## Inherited BirdNET-Analyzer docs

The other files in this folder (`*.rst`, `usage/`, `best-practices/`, `implementation-details/`, `_static/`, `_site/`, `conf.py`) are the original BirdNET-Analyzer user documentation (Sphinx). They are kept as reference for now and are not maintained by us; see [upstream-README.md](upstream-README.md) and https://birdnet-team.github.io/BirdNET-Analyzer/.
