# UX Direction

A product-direction supplement to the implementation spec. This document does
not redefine the data model, contracts, or services already specified — it
defines how those capabilities surface to users. Engineering decisions that
affect product behavior should be evaluated against this document; structural
decisions (storage, transport, schema) continue to be governed by the
implementation spec and the records in `docs/decisions/`.

## Stance

> **OpenABM is an agent that monitors, reports, and proposes fixes for your
> other agents. The UI is the agent's surface area — not a database browser.**

The current UI is feature-first: eleven equally weighted surfaces, each a
view onto a part of the schema. The intended UI is workflow-first: a single
live feed of what the system noticed, with proposed actions, and a small set
of drill-downs behind it. If a screen does not reflect the stance above, it
should not exist.

Concretely, the product must do three things in the order below. The current
UI does the first two only weakly and the third not at all.

1. **Monitor unprompted.** Live stream of agent activity. Counts update in
   place. New errors arrive as notifications. No refresh button anywhere in
   the daily-work surface.
2. **Report pre-ranked.** Users do not search to find problems. Problems
   find users, already clustered by behavior or error signature, with
   severity and trend inferred.
3. **Propose a fix.** Every detected cluster carries a structured
   recommendation and a one-click approve path. Manual investigation is
   available, but it is the fallback, not the default.

## The loop

Every detected thing — error cluster, behavior match, drift signal, eval
regression — is an object with a state machine. State is visible in the UI
per item, and the system advances state automatically wherever it can.

```
DETECT  →  CLUSTER  →  PROPOSE FIX  →  APPLY  →  VERIFY  →  CLOSE
```

- **DETECT** — a trace, span, or eval result enters the system.
- **CLUSTER** — backend grouping pass: similar failures, behavior matches,
  drift exceedances. Output: clusters with size, trend, suggested action.
- **PROPOSE FIX** — typed recommendation object. Example types: `revert_prompt`,
  `route_tool`, `raise_threshold`, `add_behavior`, `disable_judge`. Each
  recommendation is renderable and one-click approvable.
- **APPLY** — on approval, the system performs the change (writes a new
  prompt version, updates a config, files a behavior). The user signed it;
  the system executed it. This step is the difference between a dashboard
  and an agent.
- **VERIFY** — the system re-runs the relevant regression eval or watches the
  cluster's signal for N minutes. Advances state on its own.
- **CLOSE** — the cluster is archived with full provenance.

This loop is the spine of the product. Today, only DETECT exists in any
meaningful form; the rest is implicit in manual user actions across
disconnected views.

## The Now surface

Replace the current default landing (Traces) with a single inbox-style feed.
This is the home screen and, for most users, the entire product on most days.
Every other surface is a destination from here.

```
NOW                                                       today · 14:22 PT

  ▸ 3 traces failed `lookup_order` for refund intents · last 22m
    cluster: refund_routing_violation     suggested: route to lookup_order_v2
    [ apply to 3 ]  [ open cluster ]  [ ignore ]

  ▸ behavior `wrong_tool_for_refund` matched 7× in past hour (+340%)
    cause: prompt_v3 omits refund-tool guidance
    [ revert to prompt_v2 ]  [ patch v3 ]  [ open ]

  ▸ judge `refund_policy_v1` calibration drifted −8pts vs last week
    [ recalibrate ]  [ open ]

  ▸ 12 reviews queued · 4 over SLA
    [ open queue ]

  ▸ dataset eval `refund_regression_2026-05` finished · 47/50 pass
    [ open ]
```

Each row is a typed event with a suggested action. Each action button is
backed by a real, executable action — not a navigation. The cluster, judge,
prompt, and dataset are reachable via "open" links for users who want to
inspect first.

## Navigation model

Collapse the current eleven sibling surfaces into three zones aligned with
user intent:

| Zone | Surfaces | When touched |
|---|---|---|
| **WORK** | Now (default), Investigations, Reviews | Daily. ~80% of time. |
| **LIBRARY** | Behaviors, Judges, Datasets, Prompts, Configs | Read-mostly. Authored as a byproduct of WORK. |
| **SETTINGS** | MCP, Ops, Auth, Secrets, Retention | Rarely. |

WORK's default is Now. Investigations is the drill-down surface for an
individual cluster — the existing Trace Explorer demoted from home page to
detail page. Reviews is the existing queue, retained.

LIBRARY surfaces are auditable lists, not create-forms. Authoring happens via
the prompt-paths described below; LIBRARY pages may include a manual "create"
escape hatch but it is not the primary affordance.

SETTINGS contains everything currently in MCP and Ops, plus the
sidebar's API/Key controls. These are infrastructure, not product.

## Setup-as-byproduct

The current model asks users to enter LIBRARY surfaces and fill create-forms
before they can do work. Invert this.

- **Behaviors** are proposed when a user repeatedly labels similar traces
  the same way ("the system noticed these 4 traces all failed in the same
  shape — should I watch for this pattern?"). The form, if any, is a
  confirmation, not the action.
- **Judges** are proposed when human review labels cluster on a measurable
  axis ("you've rejected 6 traces for missing refund policy citations —
  should I draft a judge from these?").
- **Datasets** are proposed when users pin or bookmark traces.
- **Prompt versions** are captured automatically when a user applies a
  proposed fix that edits a prompt.
- **Automations** are renamed **Routes** and exist as a side effect of an
  approved recommendation being marked "always apply."

The LIBRARY remains, but as a curated catalog of what the system has
learned with the user. Naked create-forms are removed from the primary
navigation path.

## What the surface stops doing

- **Trace Explorer as home.** Demoted to Investigations. Linked from Now.
- **Issues as a separate surface.** Folded into Now. An "issue" in the new
  model is a cluster that has been triaged and assigned a state.
- **Standalone create-forms** for Judges, Behaviors, Datasets, Prompts,
  Automations as the primary affordance. The forms still exist for the
  manual case; they are no longer entry points.
- **Manual refresh.** Every WORK-zone view subscribes to a live stream. The
  Refresh button is removed from these surfaces. It remains in LIBRARY and
  SETTINGS where data is rarely changing.
- **Empty states that announce absence.** Every empty state must be either
  (a) a call to action with one button, or (b) a description of the event
  that will populate it. "no judges" is not acceptable copy.

## Interaction principles

- **Live by default.** WORK surfaces stream. The status bar counts move.
- **One primary action per page.** Multiple equal-weight actions in a row
  is forbidden. Either one button is primary (filled signal color) or the
  page is doing too many things.
- **Bulk selection on every list.** Triage is inherently many-at-once.
- **Context propagates.** Actions taken from a trace pre-fill the new
  artifact with the trace ID, span context, and user intent. No surface
  asks the user to retype data the system already has.
- **Status bar is interactive.** Clicking a count filters to it. Clicking a
  keybind hint opens the action. Today the bar is labels; it must become
  commands.
- **Command palette (⌘K) is canonical.** Every action available via mouse
  must be available via the palette. The terminal-native visual language
  promises this.
- **Plain-English explanations are first-class.** Hover or focus on any
  detected event yields a one-sentence explanation. "Span used
  `lookup_order` after a refund-shaped utterance. Pattern matches
  `refund_routing_violation` (12 prior cases)." No jargon without an inline
  expansion on first encounter.

## The one-line test

A new user opens any screen for the first time.
**Can they answer "what should I do here?" within five seconds, without
documentation?**

If not, the screen has failed. Fix it or delete it. This applies to every
view added or modified from this point forward.

## Visual language

The visual system established in `apps/web/src/styles.css` (terminal-native,
Swiss-disciplined, IBM Plex Mono, single signal color `#FF7A1A`, sharp
1px rules, persistent status bar) is the correct vessel for this direction
and is unchanged by this document. Future surfaces should adopt it; nothing
described above is a license to introduce new color, type, or shape
primitives.

## Scope of this document

This document defines product intent. It does not:

- specify exact event types, payload schemas, or transport;
- specify the backend services that implement clustering, suggestion, or
  state-machine advancement;
- enumerate every screen.

Those belong in the implementation spec and in per-feature design records
under `docs/decisions/`. This document is the lens through which those
choices are made.
