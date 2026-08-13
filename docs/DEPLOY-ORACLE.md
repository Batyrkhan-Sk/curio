# Deploying Curio to a single always-free VM

The whole stack — Postgres, Meilisearch, the API and the frontend — on one
Oracle Cloud Always Free machine, reached over a Cloudflare Tunnel.

Why this shape rather than the Railway + Vercel split in the README: it costs
nothing per month, and the bot is **always on**. The free tiers of most
platform hosts sleep an idle service and take 30–60 seconds to wake it, which
for a Telegram bot means the first message after a quiet spell appears to go
nowhere. A VM does not sleep.

What it costs you instead is being the sysadmin: OS updates, disk, and
restarts are now yours.

---

## Before you start

**An Oracle Cloud account.** Free, but the signup is the most failure-prone
part of this entire document — see [step 0](#0-the-oracle-account) before you
start clicking.

**A Tailscale account.** Free. This is what gives the bot its public https
address without owning a domain — see [step 3](#3-the-public-entrypoint). If
you do own a domain and would rather use Cloudflare, that path is documented
alongside it.

**The code somewhere the VM can reach it.** A private GitHub repo is easiest.
The repo now has a `.gitignore` that excludes `.env`, so your bot token stays
out of it — verify with `git status` before the first push that `.env` is not
in the list.

---

## 0. The Oracle account

Sign up at [oracle.com/cloud/free](https://www.oracle.com/cloud/free/). Two of
the fields matter far more than the rest.

### Home region — permanent, so get it right

Chosen once at signup and **never changeable**. Always Free resources exist
only in it, so a wrong choice means deleting the account and starting over.

Pick a **large region with three availability domains** — Ashburn, Phoenix,
Frankfurt, London. Free ARM capacity is genuinely scarce, and a three-AD
region gives you three pools to try instead of one. That matters more than
latency here: a Telegram webhook does not care about 80ms, and you will care
enormously about whether an instance can be created at all.

Confirm the region supports **Ampere A1** before choosing. A shape can be
advertised as Always Free while your region has none of it free.

### The card

Identity verification only — roughly $1, held and released, no charge. It
fails for boring reasons:

- **Use a real credit or debit card in your own name.** Virtual, prepaid and
  PayPal-linked cards are commonly auto-rejected. Discover is not supported.
- **The name and address must match the card's billing details exactly.**
- **Turn off any VPN or proxy** and sign up from a residential or mobile
  connection. Datacentre and VPN IPs trip the anti-abuse filter.
- **Do not retry repeatedly.** Several attempts from one IP triggers a
  lockout; wait 24 hours and come back on a different network. Retrying hard
  is what turns a small problem into a banned signup.
- Use a mobile number that can receive SMS.

### After signup

You get $300 of trial credits for 30 days. When they expire the account
**downgrades to Always Free automatically** — it does not close, and the
instance keeps running. Nothing to do; just do not be alarmed by the emails.

> **The capacity workaround.** If `VM.Standard.A1.Flex` refuses to create in
> every AD for days, upgrading to **Pay As You Go** gives priority access to
> hardware, and Always Free resources remain free on a PAYG account. The risk
> is real though: the guard rail is gone, so anything you create beyond the
> Always Free limits bills immediately. If you do it, set a budget alert at $1
> first, and check "Always Free eligible" on every resource.

---

## 1. The machine

### First, the network — separately

Do this *before* creating the instance. Console → **Networking → Virtual Cloud
Networks → Start VCN Wizard → Create VCN with Internet Connectivity**. Name it
`curio-vcn`, accept every default CIDR, create.

Skipping this is the most common way to get stuck. The instance wizard offers
to create a subnet inline, but that path leaves **"Automatically assign public
IPv4 address" permanently greyed out** — it builds no internet gateway, and
OCI will not offer a public IP on a subnet with no route off the machine. The
console hints at this and is easy to miss: *"There are additional options
available when you use the Networking pages in the console."*

The wizard creates the internet gateway, a `0.0.0.0/0` route to it, and a
security list allowing inbound SSH — and nothing else, which is exactly right.
Tailscale needs no inbound port.

### Then the instance

Console → **Compute → Instances → Create instance**.

- **Image:** Ubuntu 22.04 or 24.04 — *not* the Oracle Linux default. Oracle
  Linux ships podman, and `get.docker.com` does not officially support it.
- **Shape:** `VM.Standard.A1.Flex` (Ampere ARM) — **2 OCPU, 12 GB RAM**. It
  defaults to 1 OCPU / 6 GB, which is half the free allowance for nothing.
- **Networking:** *Select existing* → `curio-vcn` → the **Public** subnet, then
  **Automatically assign public IPv4 address = ON**.
- **Boot volume:** 100 GB. The 46.6 GB default works until Docker layer cache,
  images and Postgres fill it. Always Free covers 200 GB.

That 2/12 split is the Always Free ceiling as of June 2026, halved from the
4/24 it used to be. It is still far more than this stack needs.

Save the SSH private key when it offers — it is shown once — then:

```bash
chmod 600 /path/to/key      # ssh silently refuses a world-readable key
ssh -i /path/to/key ubuntu@<public-ip>
```

> Forgot the public IP? It can be added afterwards, provided the subnet has an
> internet gateway: **Instance → Attached VNICs → the VNIC → IPv4 Addresses →
> Edit → Public IP: Ephemeral**.

> **"Out of host capacity."** Expected, not a mistake on your part — free ARM
> capacity is genuinely scarce. In order:
>
> 1. **Change availability domain** and retry. AD-1 → AD-2 → AD-3. This is the
>    entire reason for choosing a three-AD region.
> 2. **Ask for less.** Try 1 OCPU / 6 GB. Small requests fit fragmented
>    capacity far more often, and `A1.Flex` is *flexible* — edit the instance
>    up to 2/12 later, with a reboot. Getting an instance at all is the hard
>    part; its size is not permanent.
> 3. **Retry off-peak**, when others release instances.
> 4. **Automate it** — [`hitrov/oci-arm-host-capacity`](https://github.com/hitrov/oci-arm-host-capacity)
>    retries through the API and creates the instance the moment capacity
>    appears. Worth it before clicking Create by hand for a week.

> **"Estimated cost €3.95/month" on the create screen.** A display artifact.
> The estimator quotes list price and ignores Always Free allowances entirely
> — it shows a figure even for the default boot volume. Block storage up to
> 200 GB is included. Set a budget alert at €1 under *Billing → Budgets* if you
> want certainty rather than reassurance.

## 2. Docker

```bash
sudo apt-get update && sudo apt-get upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
```

Everything is `linux/arm64` here. Both third-party images (`pgvector/pgvector`,
`getmeili/meilisearch`) publish ARM builds and the two app images build from
source, so nothing needs emulation.

## 3. The public entrypoint

Telegram needs a stable `https://` address to deliver updates to. Two ways to
get one, and the compose file carries both — pick with `--profile`.

They work identically in shape: a container dials **out** to a provider, and
inbound traffic rides back down that connection. Nothing ever listens on a
public port on the VM. The only real difference is where the hostname comes
from — Tailscale lends you one of theirs, Cloudflare routes one of yours.

| | `--profile tailscale` | `--profile cloudflare` |
| --- | --- | --- |
| Cost | free | a domain, ~$1–10/yr |
| Hostname | `curio.<tailnet>.ts.net` | anything you own |
| Setup | auth key + ACL attribute | one pasted token |

### Option A — Tailscale Funnel (free, no domain)

Tailscale is normally a private VPN. **Funnel** is its opt-in exception: one
port on one machine, published to the whole internet. Everything else on your
tailnet stays private, and the public visitors are ordinary HTTPS clients, not
VPN members. It works here because Tailscale owns `ts.net` and can therefore
issue a real Let's Encrypt certificate for your machine's name — which is
exactly the thing a domain would otherwise be buying you.

1. Sign in at [login.tailscale.com](https://login.tailscale.com).
2. **DNS** → enable **MagicDNS**, then **HTTPS Certificates**. Note your
   tailnet name (something like `tail1234.ts.net`) — the public hostname is
   built from it.
3. **Access controls** → grant the node the Funnel attribute. Funnel is
   refused without it:

   ```jsonc
   "nodeAttrs": [
     { "target": ["autogroup:member"], "attr": ["funnel"] }
   ]
   ```

4. **Settings → Keys** → *Generate auth key*. Make it **reusable** and leave
   **ephemeral off**. An ephemeral key drops the node when the container
   stops, and it returns as `curio-1`, silently breaking the webhook.

Your public address will be `https://curio.<your-tailnet>.ts.net`.

> Funnel listens on 443, 8443 or 10000 only, and its bandwidth limits are
> undisclosed. Neither constrains a bot; both would matter for serving video.

### Option B — Cloudflare Tunnel (needs a domain)

**Zero Trust → Networks → Tunnels → Create a tunnel** → *Cloudflared* → name it
`curio`. Skip the install snippet — the tunnel runs as a container here. Copy
just the **token**, then add a public hostname:

| Field | Value |
| --- | --- |
| Subdomain | `curio` |
| Domain | your domain |
| Service type | `HTTP` |
| URL | `web:3000` |

`web:3000` is the service name on the compose network, not localhost — the
cloudflared container resolves it internally.

## 4. Configuration

```bash
git clone https://github.com/<you>/curio.git && cd curio
cp .env.example .env
nano .env
```

The values that must change from their defaults:

```bash
# Real secrets, not the dev defaults.
POSTGRES_PASSWORD=<openssl rand -base64 24>
# Production Meilisearch refuses to boot on a key under 16 bytes.
MEILI_MASTER_KEY=<openssl rand -base64 32>

# From step 3 — fill in only the one matching the profile you chose.
TAILSCALE_AUTHKEY=<paste>          # option A
TAILSCALE_HOSTNAME=curio
# CLOUDFLARE_TUNNEL_TOKEN=<paste>  # option B

# Your real public hostname, in all three. No trailing slash.
# Tailscale:  https://curio.<your-tailnet>.ts.net
# Cloudflare: https://curio.yourdomain.com
CORS_ORIGINS=https://curio.tail1234.ts.net
TELEGRAM_WEBAPP_URL=https://curio.tail1234.ts.net
TELEGRAM_PUBLIC_URL=https://curio.tail1234.ts.net

# Carry these over from your laptop's .env.
TELEGRAM_BOT_TOKEN=...
TELEGRAM_BOT_USERNAME=...
GEMINI_API_KEY=...
GROQ_API_KEY=...
```

Leave `TELEGRAM_WEBHOOK_SECRET` as it is if you already have one — reusing it
saves nothing, but changing it means Telegram's stored copy no longer matches
and every update is rejected until you re-run `telegram setup`.

`ADMIN_API_ENABLED` is not read from `.env` in production; the compose file
pins it to `false`, because those endpoints reseed and reindex with no
authentication at all.

## 5. Launch

The profile picks your entrypoint. Without one, the stack comes up with no
public address at all and Telegram cannot reach it.

```bash
docker compose -f docker-compose.prod.yml --profile tailscale up -d --build
```

The first build takes several minutes. First boot then creates the pgvector
and pg_trgm extensions, creates the tables, seeds the 59 curated cards, builds
the graph and indexes into Meilisearch:

```bash
docker compose -f docker-compose.prod.yml logs -f api
```

On the Tailscale path, confirm the tunnel came up before going further — this
prints the machine's full name and whether Funnel is actually serving:

```bash
docker compose -f docker-compose.prod.yml --profile tailscale logs tailscale
docker compose -f docker-compose.prod.yml --profile tailscale exec tailscale tailscale status
```

Wait for the seeding to finish, then open your public URL in a browser. The
first request can take a few seconds while the certificate is issued.

## 6. Point the bot at it

```bash
docker compose -f docker-compose.prod.yml exec api python -m app.cli telegram setup
docker compose -f docker-compose.prod.yml exec api python -m app.cli telegram info
```

`setup` registers the webhook, the command list, the description and the Mini
App menu button. `info` prints Telegram's own view, including the last
delivery error — the first place to look when nothing happens.

**This is the last time you do this.** The hostname is now stable, so unlike
the `trycloudflare.com` quick tunnel it survives restarts, reboots and
redeploys. Message the bot; it should answer, and keep answering with your
laptop shut.

One thing still is not scriptable: for inline mode (`@yourbot wifi` in any
chat), send BotFather `/setinline`.

---

## Running it

**Deploy a change.** The production images have no source bind mounts, so a
pull alone changes nothing — it has to be rebuilt:

```bash
git pull && docker compose -f docker-compose.prod.yml --profile tailscale up -d --build
```

Keep the `--profile` on every `up`. Omitting it on a running stack stops the
tunnel container, and the bot goes quiet while everything else looks healthy.

**Admin commands** replace the disabled HTTP endpoints:

```bash
docker compose -f docker-compose.prod.yml exec api python -m app.cli reindex
docker compose -f docker-compose.prod.yml exec api python -m app.cli ingest
```

**Reach Postgres or Meilisearch.** Both bind to loopback on the VM, so tunnel
in over SSH rather than opening a port:

```bash
ssh -i key -L 5433:localhost:5433 ubuntu@<public-ip>
```

**Back up.** Nothing here is backed up by default, and the free tier gives no
snapshots worth relying on:

```bash
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U curio curio | gzip > curio-$(date +%F).sql.gz
```

Meilisearch needs no backup — its volume is rebuildable, and the API reindexes
from Postgres on every boot.

---

## Things that will bite you

**Oracle reclaims genuinely idle instances.** Always Free compute can be
reclaimed after ~7 days of very low utilisation. A live bot with a tunnel
holding a connection is normally enough to avoid it, but it is the reason not
to keep anything here that exists nowhere else.

**Oracle's Ubuntu images ship restrictive iptables rules** that block
everything but SSH, independently of the console's security lists — the classic
"I opened the port and it still times out." This setup never opens a port, so
it does not arise. It will the moment you try to expose something directly.

**The `-f docker-compose.prod.yml` is not optional.** Without it Compose reads
the dev file, which mounts your source over the image, runs `next dev`, and
publishes Postgres to the world.

**An ephemeral Tailscale auth key renames the node.** The machine is dropped
when the container stops and rejoins as `curio-1`, so the hostname the webhook
points at no longer exists. Use a reusable, non-ephemeral key, and keep the
`tailscale-state` volume.

**Funnel silently does nothing without the ACL attribute.** If the site is
reachable from your own devices but not from a phone on mobile data, the
`nodeAttrs` funnel grant in step 3 is missing. `tailscale funnel status`
inside the container says so.

---

## Switching entrypoint later

Nothing in the app is tied to either provider. To move from Tailscale to a
domain on Cloudflare once you have one:

```bash
# 1. fill CLOUDFLARE_TUNNEL_TOKEN and update the three URLs in .env
docker compose -f docker-compose.prod.yml --profile tailscale down
docker compose -f docker-compose.prod.yml --profile cloudflare up -d
# 2. re-register the webhook at the new hostname
docker compose -f docker-compose.prod.yml exec api python -m app.cli telegram setup
```

The data is untouched — it lives in the `db-data` volume, which neither
profile owns.
