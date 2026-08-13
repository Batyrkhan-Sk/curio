#!/usr/bin/env bash
# Retry launching an Always Free ARM instance until capacity appears.
#
# Free A1 capacity is released in seconds when someone else deletes an
# instance, so this is a race the console cannot win by hand. Run it in Oracle
# Cloud Shell (the >_ icon in the console), where the OCI CLI is already
# authenticated as you — no API keys to configure.
#
#   bash oci-retry-launch.sh
#
# Leave it running. It cycles the availability domains, and stops the moment
# one accepts. Ctrl-C to give up.

set -uo pipefail

# ── Tunables ────────────────────────────────────────────────────────────────
# Start at 1/6. It fits fragmented capacity far more often than 2/12, and the
# shape is *flexible* — resize the instance to 2/12 later with a reboot. An
# instance you can grow beats a request that never succeeds.
OCPUS="${OCPUS:-1}"
MEMORY_GB="${MEMORY_GB:-6}"
BOOT_GB="${BOOT_GB:-100}"
DISPLAY_NAME="${DISPLAY_NAME:-curio}"
# Per *attempt*, not per cycle. The launch call itself takes ~100s to return a
# capacity error, so 120 here gives roughly 16 attempts an hour. Faster than
# that earns a 429: ~32/hour is measured to trip Oracle's throttle, and being
# rate limited buys nothing — capacity appears at random, not on demand.
SLEEP_SECONDS="${SLEEP_SECONDS:-120}"
MAX_BACKOFF="${MAX_BACKOFF:-1800}"
SSH_PUBLIC_KEY_FILE="${SSH_PUBLIC_KEY_FILE:-$HOME/.ssh/id_rsa.pub}"

# ── Discovery ───────────────────────────────────────────────────────────────
command -v jq >/dev/null || { echo "jq is required (present in Cloud Shell by default)." >&2; exit 1; }

C="${OCI_TENANCY:-}"
if [[ -z "$C" ]]; then
  echo "OCI_TENANCY is not set — are you running this in Cloud Shell?" >&2
  echo "Otherwise export OCI_TENANCY=<your tenancy OCID> first." >&2
  exit 1
fi

if [[ ! -f "$SSH_PUBLIC_KEY_FILE" ]]; then
  echo "No SSH public key at $SSH_PUBLIC_KEY_FILE."
  echo "Generating one now — the matching private key stays in Cloud Shell,"
  echo "so download ~/.ssh/id_rsa afterwards or you cannot log in."
  ssh-keygen -t rsa -b 4096 -N "" -f "${SSH_PUBLIC_KEY_FILE%.pub}"
fi
SSH_KEY="$(cat "$SSH_PUBLIC_KEY_FILE")"

echo "Finding the newest Ubuntu 24.04 ARM image..."
IMAGE_ID=$(oci compute image list \
  --compartment-id "$C" \
  --operating-system "Canonical Ubuntu" \
  --operating-system-version "24.04" \
  --shape "VM.Standard.A1.Flex" \
  --sort-by TIMECREATED --sort-order DESC \
  --query 'data[0].id' --raw-output 2>/dev/null)
[[ -z "${IMAGE_ID:-}" || "$IMAGE_ID" == "null" ]] && { echo "No Ubuntu 24.04 ARM image found." >&2; exit 1; }

echo "Finding a public subnet..."
SUBNET_ID=$(oci network subnet list \
  --compartment-id "$C" \
  --query "data[?\"prohibit-public-ip-on-vnic\"==\`false\`].id | [0]" \
  --raw-output 2>/dev/null)
[[ -z "${SUBNET_ID:-}" || "$SUBNET_ID" == "null" ]] && { echo "No public subnet found — run the VCN Wizard first." >&2; exit 1; }

# jq, not `tr`-ing the JSON punctuation off: --raw-output leaves a pretty
# printed array when the result is a list, so stripping [ " , still leaves the
# indentation, and the AD name goes to the API with leading spaces.
mapfile -t ADS < <(oci iam availability-domain list --compartment-id "$C" --query 'data[].name' | jq -r '.[]')
[[ ${#ADS[@]} -eq 0 ]] && { echo "No availability domains returned." >&2; exit 1; }

cat <<EOF

  shape    VM.Standard.A1.Flex — ${OCPUS} OCPU / ${MEMORY_GB} GB
  boot     ${BOOT_GB} GB
  image    ${IMAGE_ID:0:40}...
  subnet   ${SUBNET_ID:0:40}...
  domains  ${ADS[*]}

Retrying every ${SLEEP_SECONDS}s. Ctrl-C to stop.

EOF

# ── Request bodies ──────────────────────────────────────────────────────────
# Built with jq into files rather than interpolated into the command line. An
# SSH key is a long string of base64 and shell metacharacters; hand-quoting it
# into JSON is what produces CannotParseRequest, and the CLI reads file:// for
# exactly this reason.
jq -n --arg k "$SSH_KEY" '{ssh_authorized_keys: $k}' > /tmp/metadata.json
jq -n --argjson o "$OCPUS" --argjson m "$MEMORY_GB" \
  '{ocpus: $o, memoryInGBs: $m}' > /tmp/shape.json

# ── The loop ────────────────────────────────────────────────────────────────
ATTEMPT=0
BACKOFF=$SLEEP_SECONDS
while true; do
  for AD in "${ADS[@]}"; do
    ATTEMPT=$((ATTEMPT + 1))
    printf '[%s] attempt %d in %s ... ' "$(date +%H:%M:%S)" "$ATTEMPT" "$AD"

    OUT=$(oci compute instance launch \
      --compartment-id "$C" \
      --availability-domain "$AD" \
      --shape "VM.Standard.A1.Flex" \
      --shape-config file:///tmp/shape.json \
      --image-id "$IMAGE_ID" \
      --subnet-id "$SUBNET_ID" \
      --assign-public-ip true \
      --boot-volume-size-in-gbs "$BOOT_GB" \
      --display-name "$DISPLAY_NAME" \
      --metadata file:///tmp/metadata.json \
      2>&1)

    if [[ $? -eq 0 ]]; then
      echo "SUCCESS"
      echo
      echo "Instance launching. Find its public IP with:"
      echo "  oci compute instance list-vnics --instance-id \$(oci compute instance list -c \"$C\" --display-name $DISPLAY_NAME --query 'data[0].id' --raw-output) --query 'data[0].\"public-ip\"' --raw-output"
      exit 0
    fi

    # Three outcomes worth telling apart. "Out of host capacity" is the
    # expected miss. A 429 means we are polling faster than Oracle allows —
    # transient, so back off rather than quit. Anything else is a real problem
    # and stopping beats hammering.
    if grep -qi "out of host capacity\|out of capacity" <<<"$OUT"; then
      echo "no capacity"
      BACKOFF=$SLEEP_SECONDS          # a clean miss resets the penalty
      sleep "$SLEEP_SECONDS"
    elif grep -qi "TooManyRequests\|\"status\": 429" <<<"$OUT"; then
      echo "rate limited — waiting ${BACKOFF}s"
      sleep "$BACKOFF"
      BACKOFF=$((BACKOFF * 2))
      (( BACKOFF > MAX_BACKOFF )) && BACKOFF=$MAX_BACKOFF
    elif grep -qi "InternalError\|ServiceUnavailable\|\"status\": 5[0-9][0-9]\|timed out" <<<"$OUT"; then
      # Oracle's control plane throws these under load, which is exactly when
      # capacity is churning. Killing a run that has been going for six hours
      # over a transient 500 loses the race for no reason.
      echo "transient service error — retrying"
      sleep "$SLEEP_SECONDS"
    elif grep -qi "LimitExceeded\|QuotaExceeded" <<<"$OUT"; then
      echo "LIMIT REACHED"
      echo >&2
      echo "Not a capacity problem: the tenancy is already at its Always Free" >&2
      echo "allowance. Check for a stopped instance or an unattached boot" >&2
      echo "volume still holding the quota — both count." >&2
      echo "$OUT" >&2
      exit 1
    else
      echo "FAILED"
      echo "$OUT" >&2
      exit 1
    fi
  done
done
