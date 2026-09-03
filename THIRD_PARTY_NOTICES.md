# Third-party components

The root MIT license applies to AIMEC-authored source and documentation in this
export. It does not replace licenses for model weights, container images, their
transitive dependencies, or the browser used to access the application.

| Component | Use | Upstream terms |
| --- | --- | --- |
| Ollama | Local model server, downloaded as a container image | [MIT](https://github.com/ollama/ollama/blob/main/LICENSE) |
| Qwen3-1.7B / Ollama `qwen3:1.7b` | Model used by both specialist roles; fetched separately | [Apache License 2.0](https://huggingface.co/Qwen/Qwen3-1.7B/blob/main/LICENSE); verify the exact artifact's license when changing model/tag |
| Python | Standard-library application runtime in `python:3.12-slim` | [Python licensing](https://docs.python.org/3/license.html), plus base-image component terms |
| Caddy | Optional HTTPS reverse proxy | [Apache License 2.0](https://github.com/caddyserver/caddy/blob/master/LICENSE) |
| Alpine Linux | Volume initialization container | [Package-specific license information](https://pkgs.alpinelinux.org/packages) |

The repository references these components; it does not bundle model weights or
container images. Retain upstream licenses/notices if you redistribute them.
The Qwen publisher and Ollama are not sponsors or endorsers of this project.

WebMCP is a browser API. No third-party WebMCP SDK is vendored here. Browser software
is installed separately under its own terms.
