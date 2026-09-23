#!/usr/bin/env bash
#
# One-time GCP setup for the caveman-agent GitHub Actions deploy.
#
# Run once, from anywhere, with an account that has roles/owner on the project.
# Every step is idempotent: re-running adds nothing and fails nothing.
#
#   bash caveman-agent/setup-gcp.sh
#
# It prints the two GitHub repository variables to set at the end.

set -euo pipefail

PROJECT_ID="deepak-jump-start"
PROJECT_NUMBER="75549320992"
REGION="us-central1"
GITHUB_REPO="deepakkumar-egen/caveman"

POOL="github-pool"
PROVIDER="github-provider"

# Deploys from CI and builds the image. Never runs the agent.
DEPLOY_SA="agent-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
# What the agent runs as. Holds roles/aiplatform.user and nothing else.
RUNTIME_SA="caveman-agent-run@${PROJECT_ID}.iam.gserviceaccount.com"

say() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }

say "Enabling APIs"
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  --project "${PROJECT_ID}"

say "Creating runtime service account (skipped if present)"
gcloud iam service-accounts create caveman-agent-run \
  --display-name="caveman-agent Cloud Run runtime" \
  --description="Runtime identity for caveman-agent. Vertex model calls only." \
  --project "${PROJECT_ID}" 2>/dev/null || echo "already exists"

say "Granting the runtime account its single role"
# roles/aiplatform.user is the whole grant. A prompt injection against the
# deployed agent inherits exactly this and nothing else.
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/aiplatform.user" \
  --condition=None --quiet >/dev/null

say "Granting the build account what a CUSTOM Cloud Build SA needs"
# roles/cloudbuild.builds.editor lets an account MANAGE builds; it does not let
# one EXECUTE as the build worker. A custom build SA must write its own build
# logs and read the source tarball gcloud uploads to the staging bucket, or the
# build fails at startup before it ever reads the Dockerfile.
for role in roles/logging.logWriter roles/storage.objectUser; do
  echo "  ${role}"
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOY_SA}" \
    --role="${role}" \
    --condition=None --quiet >/dev/null
done

say "Letting the deploy account act as the runtime account"
# Deploying a service that RUNS AS another identity requires this on the
# target account. Without it the deploy fails at the last step with a
# serviceAccountUser error, after the image has already been built.
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
  --member="serviceAccount:${DEPLOY_SA}" \
  --role="roles/iam.serviceAccountUser" \
  --project "${PROJECT_ID}" --quiet >/dev/null

say "Creating the Workload Identity pool (skipped if present)"
gcloud iam workload-identity-pools create "${POOL}" \
  --location=global \
  --display-name="GitHub Actions" \
  --project "${PROJECT_ID}" 2>/dev/null || echo "already exists"

say "Creating the GitHub OIDC provider (skipped if present)"
# The attribute condition is the security boundary. Without it, ANY GitHub
# repository on github.com could mint tokens for this pool. gcloud refuses to
# create a provider without one for exactly that reason.
gcloud iam workload-identity-pools providers create-oidc "${PROVIDER}" \
  --location=global \
  --workload-identity-pool="${POOL}" \
  --display-name="GitHub" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository=='${GITHUB_REPO}'" \
  --project "${PROJECT_ID}" 2>/dev/null || echo "already exists"

say "Allowing ${GITHUB_REPO} to impersonate the deploy account"
PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${GITHUB_REPO}"
gcloud iam service-accounts add-iam-policy-binding "${DEPLOY_SA}" \
  --member="${PRINCIPAL}" \
  --role="roles/iam.workloadIdentityUser" \
  --project "${PROJECT_ID}" --quiet >/dev/null

WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"

cat <<EOF

────────────────────────────────────────────────────────────────────────
Setup complete. Set the two repository VARIABLES (not secrets — neither
value is sensitive, and variables are visible in run logs where they help
with debugging):

  gh variable set WIF_PROVIDER --repo ${GITHUB_REPO} \\
    --body "${WIF_PROVIDER}"

  gh variable set DEPLOY_SERVICE_ACCOUNT --repo ${GITHUB_REPO} \\
    --body "${DEPLOY_SA}"

Then trigger a deploy:

  gh workflow run "Deploy caveman-agent" --repo ${GITHUB_REPO}
────────────────────────────────────────────────────────────────────────
EOF
