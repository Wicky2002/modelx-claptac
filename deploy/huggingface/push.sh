#!/usr/bin/env bash
# Push the current commit to a Hugging Face Docker Space.
#
#   bash deploy/huggingface/push.sh <hf-username>/<space-name>
#
# Create the Space first on huggingface.co (SDK: Docker, blank template). Git asks for your Hugging Face
# username and an access token with write permission when it pushes.
# The Space gets the repository with this folder's space-card.md as its README.md, which is what tells
# Hugging Face to build the Dockerfile and send traffic to port 8000.
set -euo pipefail
space="${1:?usage: push.sh <hf-username>/<space-name>}"
root="$(git rev-parse --show-toplevel)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

git -C "$root" archive --format=tar HEAD | tar -x -C "$work"
cp "$root/deploy/huggingface/space-card.md" "$work/README.md"
# Large binary files must go through Git LFS on Hugging Face.
cd "$work"
git init -q -b main
git lfs install --local >/dev/null
git lfs track "*.png" "*.gif" "*.jpg" "*.pdf" "*.pt" "*.tif" "*.npy" >/dev/null
git add -A
git commit -q -m "Deploy $(git -C "$root" rev-parse --short HEAD)"
git push --force "https://huggingface.co/spaces/$space" main
echo "Pushed. Build log: https://huggingface.co/spaces/$space?logs=build"
