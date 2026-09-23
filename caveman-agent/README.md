# caveman-agent

The caveman skill as a standalone [ADK](https://google.github.io/adk-docs/)
agent on Vertex AI, deployable to Cloud Run.

| | |
|---|---|
| Agent | `caveman-agent` |
| Model | `gemini-2.5-flash` |
| Project | `deepak-jump-start` |
| Region | `us-central1` |
| Backend | Vertex AI via ADC — no API keys |
| Runtime SA | `caveman-agent-run@` — `roles/aiplatform.user` only |
| Build SA | `agent-deployer@` — pushes the image, never runs |

This directory is self-contained. It consumes `skills/caveman/SKILL.md` and
touches nothing else in the repository — not the Go proxy, not the plugin
distribution, not the installer.

## Layout

```
caveman-agent/
├── caveman_agent/
│   ├── __init__.py       # ADK discovery: `from . import agent`
│   ├── agent.py          # root_agent — model, description, instruction
│   ├── instruction.md    # GENERATED — do not edit
│   └── .env              # local runs only; gitignored
├── sync_instruction.py   # regenerates instruction.md; --check verifies it
├── setup-gcp.sh          # one-time GCP + Workload Identity setup
└── README.md

.github/workflows/deploy-caveman-agent.yml   # the deploy
```

Deployment is CI-only. There is no local deploy script: a laptop deploying
straight to Cloud Run produces a service nobody can trace back to a commit.

## The instruction is generated

`skills/caveman/SKILL.md` stays the single source of truth for caveman
behavior. `instruction.md` is a vendored copy with the YAML frontmatter
stripped — that frontmatter is plugin activation metadata, and a model reading
it as instruction would treat the activation triggers as behavior.

The copy exists because `adk deploy cloud_run` packages only the agent source
folder into the image, so a path reaching up into `../../skills/` resolves
locally and is missing at runtime.

**Change behavior in `skills/caveman/SKILL.md`, then re-run the sync.**
`deploy.ps1` runs it for you; the header in `instruction.md` carries a hash of
the body it was generated from.

```bash
python caveman-agent/sync_instruction.py
```

`agent.py` prepends a short runtime note to the skill body. The skill was
written for Claude Code, where hooks own the intensity level via `/caveman`
slash commands and re-inject the ruleset after compaction. None of that exists
here, so the note tells the model to start at `full` and take level changes
conversationally instead.

## Run locally

Vertex AI resolves through Application Default Credentials:

```bash
gcloud auth login
gcloud auth application-default login
```

Then, from the repository root:

```bash
adk run caveman-agent/caveman_agent     # terminal
adk web caveman-agent                   # browser UI at http://localhost:8000
```

## Deploy

GitHub Actions, keyless. Pushing to `main` with changes under `caveman-agent/`
or in `skills/caveman/SKILL.md` deploys automatically; `workflow_dispatch`
deploys on demand.

```bash
gh workflow run "Deploy caveman-agent"
```

GitHub mints an OIDC token, Google exchanges it for short-lived credentials.
**No service-account JSON key exists**, so there is none to leak or rotate. The
provider's attribute condition pins the trust to this repository — without it,
any repo on github.com could mint tokens for the pool.

ADK generates its own Dockerfile and submits to Cloud Build. No image to build
or push by hand, and no secret in the image: project and region are baked in as
plain `ENV`, and the model call authenticates as the runtime service account.

The service deploys **without** public access. Reach it through a local proxy:

```bash
gcloud run services proxy caveman-agent --region us-central1
```

Run the workflow with `public: true` to use `--allow-unauthenticated` instead.
That lets anyone with the URL spend Vertex quota against `deepak-jump-start`.

### The instruction check is a gate, not a convenience

CI runs `sync_instruction.py --check` and **fails** if `instruction.md` has
drifted from the skill. It deliberately does not regenerate: doing so would
deploy an instruction that differs from the one reviewed in the pull request.
Edit the skill, run the sync, commit the result.

## One-time setup

```bash
bash caveman-agent/setup-gcp.sh
```

Idempotent — safe to re-run. It enables the APIs, creates the runtime service
account and its single role, grants the build account what a custom Cloud Build
SA needs, creates the Workload Identity pool and GitHub provider, and binds the
repository to the deploy account. It prints the two `gh variable set` commands
to finish with.

| Variable | Value |
|---|---|
| `WIF_PROVIDER` | `projects/75549320992/locations/global/workloadIdentityPools/github-pool/providers/github-provider` |
| `DEPLOY_SERVICE_ACCOUNT` | `agent-deployer@deepak-jump-start.iam.gserviceaccount.com` |

Repository *variables*, not secrets — neither value is sensitive, and variables
stay readable in run logs where they help debugging.

## Two service accounts, on purpose

Cloud Run separates the identity that *builds* the image from the identity the
service *runs as*. They are not the same risk.

| | Account | Roles |
|---|---|---|
| **Build** | `agent-deployer@` | `artifactregistry.writer`, `cloudbuild.builds.editor`, `run.admin`, `logging.logWriter`, `storage.objectUser` |
| **Runtime** | `caveman-agent-run@` | `roles/aiplatform.user` |

The runtime account is the identity the model acts with on every request, so it
holds exactly one role: call Vertex. A successful prompt injection inherits
that and nothing else — it cannot touch Cloud Run, Artifact Registry or
storage. The build account never runs; it only pushes the image at deploy time.

The default compute service account would have worked too, but it carries
`roles/editor` across the whole project.

`logging.logWriter` and `storage.objectUser` are on the build account because a
*custom* Cloud Build service account has to write its own build logs and read
the uploaded source. `cloudbuild.builds.editor` alone does not cover either,
and the build fails at startup without them.

### Required once per project

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project deepak-jump-start

gcloud iam service-accounts create caveman-agent-run \
  --display-name="caveman-agent Cloud Run runtime" \
  --project deepak-jump-start

gcloud projects add-iam-policy-binding deepak-jump-start \
  --member="serviceAccount:caveman-agent-run@deepak-jump-start.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# The build account needs these two to function as a custom Cloud Build SA.
for role in roles/logging.logWriter roles/storage.objectUser; do
  gcloud projects add-iam-policy-binding deepak-jump-start \
    --member="serviceAccount:agent-deployer@deepak-jump-start.iam.gserviceaccount.com" \
    --role="$role"
done
```

## Known limits

- **Sessions are in-memory.** Conversation history dies when the instance
  scales down. Fix with `--session_service_uri` pointing at Agent Engine or a
  SQL backend; deliberately not wired up yet.
- **`--with_ui` is development only.** ADK's own CLI help says so.
- **Spend is not metered by caveman.** This agent calls Vertex directly and
  does not pass through `caveman-proxy`, so none of the repository's token
  accounting applies to it.
