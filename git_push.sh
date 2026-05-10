#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${GIT_REMOTE_URL:-https://github.com/0906866006ben-debug/ai-stock.git}"
GIT_USERNAME="${GIT_USERNAME:-BenChang}"
ENV_FILE="${ENV_FILE:-backend/.env}"
BRANCH="${BRANCH:-$(git branch --show-current)}"

usage() {
  cat <<'USAGE'
Usage:
  ./git_push.sh
      Push the current branch. Fails if there are uncommitted changes.

  ./git_push.sh --commit "commit message"
      Stage all current changes, commit them, then push the current branch.

Environment overrides:
  GIT_REMOTE_URL   Remote HTTPS URL. Defaults to this project's GitHub repo.
  GIT_USERNAME     GitHub username. Defaults to BenChang.
  ENV_FILE         Env file containing the GitHub token. Defaults to backend/.env.
  BRANCH           Branch to push. Defaults to current branch.

Token lookup:
  Supports standard env keys such as GITHUB_TOKEN=... or GITHUB_PAT=...
  Also supports this project's existing line format:
  Personal-access-tokens:github_pat_...
USAGE
}

mask_secret() {
  local value="${1:-}"
  if [[ ${#value} -le 8 ]]; then
    printf '<masked>'
  else
    printf '%s...%s' "${value:0:4}" "${value: -4}"
  fi
}

read_token() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "Missing env file: $ENV_FILE" >&2
    return 1
  fi

  local token=""
  token="$(
    awk '
      BEGIN { token="" }
      /^[[:space:]]*(GITHUB_TOKEN|GITHUB_PAT|GH_TOKEN|PERSONAL_ACCESS_TOKEN)[[:space:]]*=/ {
        sub(/^[^=]*=/, "", $0)
        gsub(/^[[:space:]"'\''"]+|[[:space:]"'\''"]+$/, "", $0)
        token=$0
      }
      /^[[:space:]]*Personal-access-tokens:/ {
        sub(/^[^:]*:/, "", $0)
        gsub(/^[[:space:]"'\''"]+|[[:space:]"'\''"]+$/, "", $0)
        token=$0
      }
      END { print token }
    ' "$ENV_FILE"
  )"

  if [[ -z "$token" ]]; then
    echo "No GitHub token found in $ENV_FILE" >&2
    return 1
  fi

  printf '%s' "$token"
}

commit_message=""
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
elif [[ "${1:-}" == "--commit" ]]; then
  commit_message="${2:-}"
  if [[ -z "$commit_message" ]]; then
    echo "Missing commit message after --commit" >&2
    usage
    exit 1
  fi
elif [[ $# -gt 0 ]]; then
  echo "Unknown argument: $1" >&2
  usage
  exit 1
fi

if [[ -z "$BRANCH" ]]; then
  echo "Could not determine current branch. Set BRANCH=your-branch and retry." >&2
  exit 1
fi

GIT_TOKEN="$(read_token)"
export GIT_USERNAME GIT_TOKEN

echo "Remote: $REPO_URL"
echo "Branch: $BRANCH"
echo "Username: $GIT_USERNAME"
echo "Token: $(mask_secret "$GIT_TOKEN")"

git remote set-url origin "$REPO_URL"

if [[ -n "$commit_message" ]]; then
  git add -A
  if git diff --cached --name-only | grep -E '(^|/)\.env($|\.|/)|backend/\.env$' >/dev/null; then
    echo "Refusing to commit staged .env file(s). Unstage/remove secrets first." >&2
    git diff --cached --name-only | grep -E '(^|/)\.env($|\.|/)|backend/\.env$' >&2
    exit 1
  fi
  if git diff --cached --quiet; then
    echo "No staged changes to commit."
  else
    git commit -m "$commit_message"
  fi
else
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "There are uncommitted changes. Commit first, or run:" >&2
    echo "  ./git_push.sh --commit \"your commit message\"" >&2
    exit 1
  fi
fi

askpass_file="$(mktemp)"
cat > "$askpass_file" <<'ASKPASS'
#!/usr/bin/env bash
case "$1" in
  *Username*) printf '%s\n' "$GIT_USERNAME" ;;
  *Password*) printf '%s\n' "$GIT_TOKEN" ;;
  *) printf '\n' ;;
esac
ASKPASS
chmod 700 "$askpass_file"
trap 'rm -f "$askpass_file"' EXIT

GIT_ASKPASS="$askpass_file" GIT_TERMINAL_PROMPT=0 git push -u origin "$BRANCH"
