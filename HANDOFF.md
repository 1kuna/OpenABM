# OpenABM Handoff

Prepared: 2026-06-22 14:27 EDT

## Repository State

- Checkout: `/Users/zach/Developer/OpenABM`
- Branch at handoff start: `main`
- Base HEAD at handoff start: `56667aed3ee8cc3d56cb2876c70bc4b840ce30b7`
  (`Record UX direction completion`)
- Remote: `origin https://github.com/1kuna/OpenABM.git`
- Tracking status after `git fetch --prune`: `main` matched `origin/main` before
  this handoff document was committed.
- Local untracked/generated state intentionally left uncommitted:
  - `.claude/`
  - `.openabm/`
  - `.pytest_cache/`
  - `.ruff_cache/`
  - `.venv/`
  - `apps/web/dist/`
  - `apps/web/node_modules/`
  - Python `__pycache__/` trees
  - `artifacts/`
  - ignored local-only `openabm_implementation_spec.md`

`openabm_implementation_spec.md` is the local read-only SSOT and is ignored on
purpose. Public progress and resume context live in tracked docs.

## Authority Files

- `openabm_implementation_spec.md`: local ignored implementation SSOT.
- `IMPLEMENTATION_PROGRESS.md`: tracked phase status, validation history,
  current blockers, and latest completed slice.
- `docs/ux-direction.md`: product-direction lens for current and future UI work.
- `README.md`: public project framing and primary developer commands.
- `docs/synthetic-pilot.md`: synthetic validation commands, report boundaries,
  and latest local proof.
- `docs/deployment.md`: reference deployment contract.
- `governance/decisions/` and `docs/decisions/`: implementation decisions and
  revisit triggers.

## Last Work Completed

The last completed tracked work was the UX direction slice on `main`, ending at
commit `56667ae`:

- Now/work-surface actions were implemented as executable app actions.
- Investigations and Reviews gained bulk selection and bulk action coverage.
- Settings owns local API base URL and API key controls.
- Library create forms were demoted into collapsed manual escape hatches.
- Browser QA fixed desktop review bulk-action clipping and mobile nav overflow.
- `IMPLEMENTATION_PROGRESS.md` records the UX direction as complete for the
  current local-reference app.

The `.claude/worktrees/tender-mirzakhani-f93a27` worktree is older local
generated state on `claude/tender-mirzakhani-f93a27` at `4414245`; its remote
tracking branch is gone, and it trails the committed `main` UX work. Treat it
as local generated context, not the resume authority.

## Validation Run For This Handoff

Ran on 2026-06-22 from `/Users/zach/Developer/OpenABM`:

- `git fetch --prune`
  - `main` matched `origin/main` before this handoff commit.
  - Only unrelated Dependabot remote branch churn was observed.
- `make ci`
  - `ruff check .`: passed.
  - `pytest`: 113 tests passed.
  - OpenAPI JSON check: passed.
  - docs link check: passed.
  - `npm --prefix apps/web run build`: passed.
- `make deploy-config-check`
  - `docker compose -f deploy/compose.yaml config --quiet`: passed.
- `gh run list --repo 1kuna/OpenABM --workflow CI --branch main --limit 5`
  - Latest CI run for `56667ae` was successful on 2026-05-14.

No model-backed synthetic pilot or real deployment smoke was rerun for this
handoff; the request was to preserve a handoff state, and the local deterministic
repo gates already passed.

## Blockers And Cautions

- Phase 9 real-world pilots remain blocked on real users/workloads. Synthetic
  validation is extensive, but it does not prove usability, production
  deployment confidence, or real customer workflows.
- External IdP/OAuth, vendor-specific invite providers, production secret
  managers, vendor ChatOps, production observability backends, and deployment
  supervision remain adapter/integration work beyond the local reference.
- Production vector-store/ANN decisions, broader clustering experiments, image
  OCR quality tuning, and deeper UI usability polish remain future hardening.
- For model-backed work, keep the project guardrail: use LM Studio or another
  explicit OpenAI-compatible local provider, keep context at or above 32k, do
  not add generation timeouts, and do not replace semantic judgment with
  brittle deterministic heuristics.
- Do not commit ignored/generated local state unless a future task explicitly
  promotes it. In particular, keep `.claude/`, `.openabm/`, build output,
  caches, virtualenvs, and the ignored local spec out of commits.

## Exact Next Steps

1. If resuming product implementation, read `IMPLEMENTATION_PROGRESS.md` first,
   then `docs/ux-direction.md`, then the relevant section of the ignored local
   `openabm_implementation_spec.md`.
2. Pick the next task from the real blockers, not from already-complete local
   reference work:
   - run a real pilot with real traces/users,
   - implement a concrete external integration target,
   - run production-reference deployment smoke against an actual deployment,
   - or start a focused hardening pass such as vector/ANN, clustering, OCR, or
     usability based on real evidence.
3. Before changing code, rerun the narrow gate for the area being touched.
   For general repo health, `make ci` is currently fast and clean.
4. If model-backed validation is needed, first verify the loaded LM Studio model
   and context with `lms ps`, then use the commands in `docs/synthetic-pilot.md`.
5. Keep commits coherent and small. Do not include `.claude/` or other generated
   local state in product commits.
