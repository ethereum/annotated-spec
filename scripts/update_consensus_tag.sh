#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONSENSUS="$ROOT/consensus-specs"

if [[ ! -d "$CONSENSUS/.git" ]]; then
  echo "consensus-specs submodule is missing" >&2
  exit 1
fi

cd "$CONSENSUS"
git fetch --tags --force > /dev/null
LATEST_TAG=$(git tag --list 'v*' --sort=-version:refname | head -n 1)
if [[ -z "$LATEST_TAG" ]]; then
  LATEST_TAG=$(git tag --sort=-creatordate | head -n 1)
fi
if [[ -z "$LATEST_TAG" ]]; then
  echo "No tags found in consensus-specs" >&2
  exit 1
fi

git checkout "$LATEST_TAG" > /dev/null

echo "consensus-specs checked out at tag $LATEST_TAG"
