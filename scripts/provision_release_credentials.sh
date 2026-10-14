#!/usr/bin/env bash
# Create the release job's Bottle token and SSH key and store them as
# production-release environment secrets. No credential is printed or kept.
set -euo pipefail
umask 077

INSTANCE=akaisenghor.bottle.cloud
REPO=AkaiS/california-political-knowledge-map
ENVIRONMENT=production-release
LABEL="ca-map-github-release-$(date +%F)"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

ssh_options=(
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=$work/known_hosts"
  -o GlobalKnownHostsFile=/dev/null
  -o ConnectTimeout=15
)

echo "1/5 Reading the zone's SSH host key (trusted on first use)"
ssh-keyscan -t ed25519 "$INSTANCE" 2>/dev/null >"$work/known_hosts"
if [ ! -s "$work/known_hosts" ]; then
  echo "Could not read an ed25519 host key from $INSTANCE." >&2
  exit 1
fi
ssh-keygen -lf "$work/known_hosts"

echo "2/5 Generating the release SSH key"
ssh-keygen -q -t ed25519 -N '' -C "$LABEL" -f "$work/identity"
entry="restrict $(cat "$work/identity.pub")"

echo "3/5 Authorizing it on the zone with your own SSH login"
# The pinned host key also protects this session, so the secret matches the
# host that accepted the new key.
ssh "${ssh_options[@]}" "host@$INSTANCE" \
  "grep -qxF '$entry' ~/.ssh/authorized_keys || printf '%s\n' '$entry' >>~/.ssh/authorized_keys"
# A forced command would answer without running df.
check=$(ssh "${ssh_options[@]}" -i "$work/identity" -o IdentitiesOnly=yes \
  -o BatchMode=yes "host@$INSTANCE" "df -P / >/dev/null && echo release-key-ok")
if [ "$check" != release-key-ok ]; then
  echo "The new key cannot run release commands on the zone." >&2
  exit 1
fi

echo "4/5 Creating the 90-day Bottle API token $LABEL"
bottle tokens create --instance "$INSTANCE" --name "$LABEL" --expiry-hours 2160 \
  | sed -n 's/^Token: //p' >"$work/token"
if [ ! -s "$work/token" ]; then
  echo "Bottle did not return a token." >&2
  exit 1
fi
printf 'Authorization: Bearer %s\n' "$(cat "$work/token")" >"$work/header"
curl -fsS -H @"$work/header" -o /dev/null "https://$INSTANCE/api/apps"

echo "5/5 Storing the secrets in the $ENVIRONMENT environment"
gh secret set BOTTLE_API_TOKEN --env "$ENVIRONMENT" -R "$REPO" <"$work/token"
gh secret set BOTTLE_SSH_PRIVATE_KEY --env "$ENVIRONMENT" -R "$REPO" <"$work/identity"
gh secret set BOTTLE_SSH_KNOWN_HOSTS --env "$ENVIRONMENT" -R "$REPO" <"$work/known_hosts"

echo "Done. Token and key are named $LABEL; local copies are deleted."
