# Contributing to PeponBot

Thank you so much for taking the time to read this. It genuinely means a lot. PeponBot is a small project born as a personal fast-build project, and the fact that you are here considering contributing to it is something we do not take for granted.

## Before you start

- I (Luis Garbayo) am currently the only maintainer, reviewing this in my spare time around a day job — not a funded team with dedicated support hours. My target is to acknowledge new issues and pull requests within **24 hours on business days**, but that's a best-effort goal, not a guarantee — please be patient if it slips.
- For anything non-trivial, open an issue first to discuss the approach before investing time in a pull request. It avoids wasted work if the direction doesn't fit the project.
- Read [`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md) first — it explains *why* things are built the way they are, which will save you from re-litigating settled trade-offs.

## Setting up your environment

```sh
git clone git@github.com:lgarbayo/pepon-bot.git
cd pepon-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pytest playwright   # test-only dependencies, not needed to run the app
playwright install chromium     # only needed for static/tests/browser_checks.py

ollama serve                    # in another terminal
ollama pull hf.co/unsloth/gemma-3-4b-it-GGUF:Q4_K_M
```

Run the app with `python3 server/main.py` from `server/`, and open `https://localhost:8000`.

## Coding standards

The codebase has no formatter or linter configured yet, so until one is added, please just match the style of the surrounding code (this is also enforced in CI, see `.github/workflows/lint.yml`, which runs [ruff](https://docs.astral.sh/ruff/) for Python against [PEP 8](https://peps.python.org/pep-0008/) and [Prettier](https://prettier.io/) defaults for the static JS/CSS/HTML):

- Python: PEP 8, type hints where they clarify intent (not everywhere), docstrings only where the *why* isn't obvious from the code.
- JavaScript/CSS/HTML: no build step, no framework — keep it that way unless discussed first. Prettier defaults for formatting.
- Comments explain *why*, not *what* — if removing a comment wouldn't confuse a future reader, it shouldn't be there.

## Tests

```sh
python3 -m pytest server/tests -q
node static/tests/voice-vad.test.cjs
python3 static/tests/browser_checks.py
```

A pull request that changes behavior should come with a test that would have failed before the change. `server/tests/test_gemma_agent.py` and `server/tests/test_companion.py` are good examples of the expected style: no live Ollama/GPU dependency, deterministic, one behavior per test.

## Commit conventions

This project follows [Conventional Commits](https://www.conventionalcommits.org/) (see `docs/` reference used internally: qoomon's commit-conventions guide). Format:

```
<type>(<optional scope>): <description>

<optional body>

<optional footer>
```

Common types: `feat`, `fix`, `refactor`, `perf`, `style`, `test`, `docs`, `build`, `ops`, `chore`. A commit that introduces a breaking change adds `!` before the colon (e.g. `feat(api)!: remove status endpoint`) and a `BREAKING CHANGE:` footer.

Every commit must be signed off per the [DCO](DCO) (`git commit -s`), certifying you have the right to submit the contribution under this project's license. See [`docs/GPG_KEY.md`](docs/GPG_KEY.md) if you'd also like to sign commits with GPG (encouraged, not yet required).

## Pull request process

1. Fork the repository and create a descriptive branch off `develop` (e.g. `feature/short-description`, `fix/short-description`) — see the branching model below.
2. Make your change with a clean build/test run locally.
3. Open the PR against `develop` (or `main` only for an urgent `hotfix/*`), filling in the template.
4. At least one maintainer approval is required before merge. As the sole maintainer today, that means I'll review and merge it myself once CI is green and the change makes sense — the review step still exists to keep a clear record of why each change was accepted, even without a second person.

### Branching model

- `main` — stable, deployable code only; tagged releases (`vX.Y.Z`).
- `develop` — integration branch for the next release.
- `feature/*` — branches off `develop`, merges back into `develop`.
- `release/*` — branches off `develop` when preparing a release, merges into both `main` (tagged) and `develop`.
- `hotfix/*` — branches off `main` for urgent fixes, merges into both `main` (tagged) and `develop`.

## Definition of done

A contribution is ready to merge when:

- [ ] It does one thing, described clearly in the PR description.
- [ ] Relevant tests pass locally and in CI.
- [ ] `CHANGELOG.md` has a new entry under `[Unreleased]` if the change is user-facing.
- [ ] Commits follow Conventional Commits and are signed off (DCO).
- [ ] Documentation (`README.md`, `docs/ARCHITECTURE_DECISIONS.md`) is updated if behavior or setup changed.

Thanks again for reading this far — see you in the issues.
