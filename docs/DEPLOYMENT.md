# Deployment notes

## Local reproduction

Use `bash scripts/demo.sh start` from the README. This exposes only a loopback UI
port, with an explicitly unverified local build identity. It does not alter the
existing live demo. Never expose a development instance publicly by simply changing
its port binding or omitting the public-origin setting.

## A new, dedicated HTTPS host

This route is for a new deployment, not an in-place migration of an existing VPS.
Use a Docker-capable host, point a DNS hostname at it, and allow inbound TCP 80/443.
Keep SSH access restricted appropriately. Ports 80 and 443 must be free.

Clone this public repository onto the host. Then, from the checkout:

```bash
python3 scripts/prepare_https.py --hostname your-demo.example.com
```

Replace the example with the hostname you own. The script reads runtime files from
the exact committed Git HEAD, rejects modified tracked files, computes a source
digest, and creates a separate `.releases/` build directory with a verified identity.
It prints the exact Docker Compose command to start that release. It does not
start containers or make hosting/account changes itself.

Run the printed command only on your approved dedicated host. Caddy obtains the
certificate. Alpha is configured with the exact HTTPS origin, a verified commit
identity, and Secure/HttpOnly/SameSite cookies. Registry and Ollama remain private.

Verify `https://YOUR_HOST/api/webmcp/config`: the expected business-agent mode,
source commit, `source_verified: true`, model and two specialists should be present.
Use the native WebMCP check after running the UI example. Test from a separate
browser/device as well as from the server.

Retain the release directory: Docker uses files from it. Keep job/event/model and
certificate volumes. Reuse the printed command's `--project-directory`, `--env-file`
and both `-f` files when managing that release. Do not replace it with the local
development helper, which intentionally uses an unverified local identity.

The source digest covers committed application inputs, not model weights or base
images. Capture runtime image/model digests separately if strict repeatability is needed.

## Existing live demo

Do not run the generic deployment command on a server already using ports 80/443.
The live competition site uses a separately verified cutover with retained rollback
containers and certificate volumes. Its server-specific migration details and
credentials are intentionally not part of this public source export.

## Operations

CPU-only inference can take minutes, especially on the first request. Avoid repeated
submissions while a job is queued/running. Use its existing job ID to read status.
A model listed by `ollama show` is installed, not necessarily inference-tested.

Back up persistent volumes before changing storage or migrating versions. This demo
does not provide a complete production multi-tenant security, billing or observability setup.
