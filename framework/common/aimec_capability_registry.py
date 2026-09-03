from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


class CapabilityError(ValueError):
    """A sanitized, fail-closed capability registration error."""


_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{2,79}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_NAME = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+$")
_ENV = re.compile(r"^[A-Z][A-Z0-9_]{2,79}$")
_SENSITIVE = re.compile(
    r"(?:^|[_-])(api[_-]?key|authorization|credential|password|private[_-]?key|secret|token|value)(?:$|[_-])",
    re.I,
)
_TOP_LEVEL = {
    "schema_version",
    "kind",
    "identity",
    "version",
    "provenance",
    "capabilities",
    "transport",
    "operations",
    "permissions",
    "risk",
    "credentials",
    "data_policy",
    "health",
    "delegation",
    "evaluation",
    "approval",
    "commercial",
}
_REQUIRED = _TOP_LEVEL - {"commercial"}
_ACTION_PERMISSIONS = {
    "invoke": frozenset({"read", "analyze", "write", "execute", "publish", "spend"}),
    "delegate": frozenset({"delegate"}),
}


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapabilityError(f"{label} must be an object")
    return value


def _unique_strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise CapabilityError(f"{label} must be a non-empty string list")
    if len(set(value)) != len(value):
        raise CapabilityError(f"{label} must be unique")
    return list(value)


def _reject_secret_material(value: Any, path: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if _SENSITIVE.search(str(key)) and key not in {"credentials"}:
                raise CapabilityError(f"{path}.{key} may describe a secret, not contain one")
            _reject_secret_material(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secret_material(nested, f"{path}[{index}]")


def validate_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the executable v0.1 subset without accepting package-owned approval."""

    manifest = _object(payload, "manifest")
    missing = sorted(_REQUIRED - set(manifest))
    unknown = sorted(set(manifest) - _TOP_LEVEL)
    if missing or unknown:
        raise CapabilityError("capability manifest fields are incomplete or unknown")
    if manifest.get("schema_version") != "0.1" or manifest.get("kind") not in {"tool", "agent"}:
        raise CapabilityError("unsupported capability manifest version or kind")

    identity = _object(manifest["identity"], "identity")
    if set(identity) != {"id", "display_name", "description"}:
        raise CapabilityError("identity fields are invalid")
    if not _ID.fullmatch(str(identity["id"])):
        raise CapabilityError("capability id is invalid")
    if not str(identity["display_name"]).strip() or not str(identity["description"]).strip():
        raise CapabilityError("capability identity text is required")
    if not _VERSION.fullmatch(str(manifest["version"])):
        raise CapabilityError("capability version must be semantic")

    provenance = _object(manifest["provenance"], "provenance")
    if set(provenance) != {"repository", "commit", "publisher"}:
        raise CapabilityError("provenance fields are invalid")
    if not str(provenance["repository"]).startswith("https://github.com/"):
        raise CapabilityError("provenance repository must be a GitHub URL")
    if not _COMMIT.fullmatch(str(provenance["commit"])):
        raise CapabilityError("provenance must pin an exact commit")

    capabilities = _unique_strings(manifest["capabilities"], "capabilities")
    if any(not _NAME.fullmatch(item) for item in capabilities):
        raise CapabilityError("capability names must be namespaced")

    transport = _object(manifest["transport"], "transport")
    if set(transport) != {"protocol", "endpoint_env", "health_path"}:
        raise CapabilityError("transport fields are invalid")
    if transport["protocol"] not in {"local", "http", "mcp", "a2a"}:
        raise CapabilityError("transport protocol is unsupported")
    endpoint_env = transport["endpoint_env"]
    if endpoint_env is not None and not _ENV.fullmatch(str(endpoint_env)):
        raise CapabilityError("transport endpoint must be a runtime environment reference")
    if transport["protocol"] != "local" and not endpoint_env:
        raise CapabilityError("remote transport requires an endpoint environment reference")
    health_path = transport["health_path"]
    if health_path is not None and not str(health_path).startswith("/"):
        raise CapabilityError("health path must be absolute")

    operations = manifest["operations"]
    if not isinstance(operations, list) or not operations:
        raise CapabilityError("at least one operation is required")
    operation_ids: set[str] = set()
    for operation in operations:
        item = _object(operation, "operation")
        required = {"id", "action", "capability", "input_schema", "output_schema", "timeout_seconds"}
        if set(item) != required or not _NAME.fullmatch(str(item["id"])):
            raise CapabilityError("operation fields or id are invalid")
        if item["id"] in operation_ids:
            raise CapabilityError("operation ids must be unique")
        operation_ids.add(item["id"])
        if item["action"] not in {"invoke", "delegate"}:
            raise CapabilityError("operation action is unsupported")
        if item["capability"] not in capabilities:
            raise CapabilityError("operation references an undeclared capability")
        if not isinstance(item["input_schema"], dict) or not isinstance(item["output_schema"], dict):
            raise CapabilityError("operation schemas must be objects")
        timeout = item["timeout_seconds"]
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 900:
            raise CapabilityError("operation timeout is outside the safe bound")
        if manifest["kind"] == "tool" and item["action"] != "invoke":
            raise CapabilityError("tools may expose invoke operations only")
        if manifest["kind"] == "agent" and item["action"] != "delegate":
            raise CapabilityError("agents may expose delegate operations only")

    permissions = _object(manifest["permissions"], "permissions")
    if set(permissions) != {"network", "filesystem", "actions"}:
        raise CapabilityError("permission fields are invalid")
    if permissions["network"] not in {"none", "restricted"}:
        raise CapabilityError("unrestricted network permission is forbidden")
    if permissions["filesystem"] not in {"none", "read", "write"}:
        raise CapabilityError("filesystem permission is invalid")
    actions = _unique_strings(permissions["actions"], "permission actions")
    allowed_actions = {"read", "analyze", "write", "execute", "delegate", "publish", "spend"}
    if not set(actions).issubset(allowed_actions):
        raise CapabilityError("permission action is unsupported")
    for operation in operations:
        if not set(actions).intersection(_ACTION_PERMISSIONS[operation["action"]]):
            raise CapabilityError("operation is not covered by declared permissions")

    risk = _object(manifest["risk"], "risk")
    if set(risk) != {"level", "human_gate", "irreversible"}:
        raise CapabilityError("risk fields are invalid")
    if risk["level"] not in {"low", "medium", "high", "critical"}:
        raise CapabilityError("risk level is invalid")
    if risk["human_gate"] not in {"none", "review", "approval"}:
        raise CapabilityError("human gate is invalid")
    if risk["irreversible"] and risk["human_gate"] != "approval":
        raise CapabilityError("irreversible capability requires human approval")
    if {"publish", "spend"}.intersection(actions) and risk["human_gate"] != "approval":
        raise CapabilityError("publish and spend permissions require human approval")

    credentials = _object(manifest["credentials"], "credentials")
    if set(credentials) != {"required", "env_refs"}:
        raise CapabilityError("credential fields are invalid")
    env_refs = credentials["env_refs"]
    if not isinstance(env_refs, list) or len(set(env_refs)) != len(env_refs):
        raise CapabilityError("credential environment references are invalid")
    if any(not _ENV.fullmatch(str(item)) for item in env_refs):
        raise CapabilityError("credentials must use environment references")
    if bool(credentials["required"]) != bool(env_refs):
        raise CapabilityError("credential requirement and environment references disagree")

    data_policy = _object(manifest["data_policy"], "data policy")
    if set(data_policy) != {"input_classes", "output_classes", "retention", "crosses_node_boundary"}:
        raise CapabilityError("data policy fields are invalid")
    classes = {"public", "local", "private", "client"}
    for field_name in ("input_classes", "output_classes"):
        values = data_policy[field_name]
        if not isinstance(values, list) or len(set(values)) != len(values) or not set(values).issubset(classes):
            raise CapabilityError("data policy classes are invalid")
    if data_policy["retention"] not in {"ephemeral", "local", "provider"}:
        raise CapabilityError("data retention is invalid")
    if data_policy["crosses_node_boundary"] and {"private", "client"}.intersection(data_policy["input_classes"]):
        raise CapabilityError("private or client data cannot cross a node boundary by default")

    health = _object(manifest["health"], "health")
    if set(health) != {"mode", "interval_seconds"} or health["mode"] not in {"none", "transport"}:
        raise CapabilityError("health contract is invalid")
    if not isinstance(health["interval_seconds"], int) or not 5 <= health["interval_seconds"] <= 3600:
        raise CapabilityError("health interval is outside the safe bound")

    delegation = _object(manifest["delegation"], "delegation")
    if set(delegation) != {"accepts_tasks", "can_delegate", "max_hops"}:
        raise CapabilityError("delegation fields are invalid")
    if not isinstance(delegation["max_hops"], int) or not 0 <= delegation["max_hops"] <= 3:
        raise CapabilityError("delegation hop limit is invalid")
    if manifest["kind"] == "tool" and (delegation["accepts_tasks"] or delegation["can_delegate"]):
        raise CapabilityError("tool manifests cannot claim agent delegation")
    if manifest["kind"] == "agent" and not delegation["accepts_tasks"]:
        raise CapabilityError("agent manifests must accept delegated tasks")

    evaluation = _object(manifest["evaluation"], "evaluation")
    if set(evaluation) != {"suite", "passed", "evidence"}:
        raise CapabilityError("evaluation fields are invalid")
    evidence = _unique_strings(evaluation["evidence"], "evaluation evidence")
    if not evaluation["passed"] or any(
        not (item.startswith("urn:") or item.startswith("https://github.com/")) for item in evidence
    ):
        raise CapabilityError("passing evaluation evidence is required")
    if _object(manifest["approval"], "approval") != {"state": "submitted"}:
        raise CapabilityError("package approval state must be submitted")
    if "commercial" in manifest and not isinstance(manifest["commercial"], dict):
        raise CapabilityError("commercial extension must be an object")

    _reject_secret_material(manifest)
    return copy.deepcopy(manifest)


@dataclass(slots=True)
class CapabilityRecord:
    manifest: dict[str, Any]
    digest: str
    status: str = "pending_review"
    reviewer: str | None = None
    granted_permissions: tuple[str, ...] = ()
    events: list[dict[str, Any]] = field(default_factory=list)


class CapabilityRegistry:
    """In-memory reference registry with administrator-owned approval and discovery."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))
        self.records: dict[str, CapabilityRecord] = {}

    def _event(self, record: CapabilityRecord, event: str, **metadata: Any) -> None:
        record.events.append(
            {
                "event": event,
                "timestamp": self.clock().isoformat(),
                **metadata,
            }
        )

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        manifest = validate_manifest(payload)
        capability_id = manifest["identity"]["id"]
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        existing = self.records.get(capability_id)
        if existing:
            if existing.digest == digest:
                return self.public_record(existing)
            raise CapabilityError("capability id already has a different submitted manifest")
        record = CapabilityRecord(manifest=manifest, digest=digest)
        self.records[capability_id] = record
        self._event(record, "capability.submitted", status=record.status)
        return self.public_record(record)

    def decide(
        self,
        capability_id: str,
        *,
        reviewer: str,
        approved: bool,
        granted_permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        record = self._record(capability_id)
        if record.status != "pending_review":
            raise CapabilityError("capability approval has already been decided")
        if not reviewer.strip():
            raise CapabilityError("administrator reviewer is required")
        requested = set(record.manifest["permissions"]["actions"])
        granted = set(granted_permissions or requested)
        if not granted.issubset(requested):
            raise CapabilityError("approval cannot grant undeclared permissions")
        record.status = "approved" if approved else "rejected"
        record.reviewer = reviewer
        record.granted_permissions = tuple(sorted(granted)) if approved else ()
        self._event(
            record,
            "capability.approved" if approved else "capability.rejected",
            reviewer=reviewer,
            granted_permissions=list(record.granted_permissions),
        )
        return self.public_record(record)

    def discover(self, *, kind: str | None = None, capability: str | None = None) -> list[dict[str, Any]]:
        items = []
        for record in self.records.values():
            manifest = record.manifest
            if record.status != "approved":
                continue
            if kind and manifest["kind"] != kind:
                continue
            if capability and capability not in manifest["capabilities"]:
                continue
            items.append(self.public_record(record))
        return sorted(items, key=lambda item: item["id"])

    def pending(self) -> list[dict[str, Any]]:
        return sorted(
            (self.public_record(record) for record in self.records.values() if record.status == "pending_review"),
            key=lambda item: item["id"],
        )

    def plan(
        self,
        capability_id: str,
        operation_id: str,
        *,
        action: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        record = self._record(capability_id)
        if record.status != "approved":
            raise CapabilityError("capability is not approved for discovery or execution")
        if not correlation_id.strip() or not idempotency_key.strip():
            raise CapabilityError("correlation_id and idempotency_key are required")
        operation = next(
            (item for item in record.manifest["operations"] if item["id"] == operation_id),
            None,
        )
        if operation is None or operation["action"] != action:
            raise CapabilityError("operation is not available for the requested action")
        if not set(record.granted_permissions).intersection(_ACTION_PERMISSIONS[action]):
            raise CapabilityError("approved permissions do not authorize this operation")
        self._event(
            record,
            "capability.dispatch_planned",
            operation_id=operation_id,
            action=action,
            correlation_id=correlation_id,
        )
        plan = {
            "capability_id": capability_id,
            "kind": record.manifest["kind"],
            "operation_id": operation_id,
            "action": action,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "transport": copy.deepcopy(record.manifest["transport"]),
            "input_schema": copy.deepcopy(operation["input_schema"]),
            "output_schema": copy.deepcopy(operation["output_schema"]),
            "risk": copy.deepcopy(record.manifest["risk"]),
            "timeout_seconds": operation["timeout_seconds"],
        }
        if record.manifest["credentials"]["required"]:
            plan["credentials_required"] = True
            plan["credential_env_refs"] = list(record.manifest["credentials"]["env_refs"])
        return plan

    def public_record(self, record: CapabilityRecord) -> dict[str, Any]:
        manifest = record.manifest
        return {
            "id": manifest["identity"]["id"],
            "display_name": manifest["identity"]["display_name"],
            "kind": manifest["kind"],
            "version": manifest["version"],
            "capabilities": list(manifest["capabilities"]),
            "operations": [
                {
                    "id": item["id"], "action": item["action"], "capability": item["capability"],
                    **({
                        "input_schema": copy.deepcopy(item["input_schema"]),
                        "output_schema": copy.deepcopy(item["output_schema"]),
                        "timeout_seconds": item["timeout_seconds"],
                    } if record.status == "approved" else {}),
                }
                for item in manifest["operations"]
            ],
            "status": record.status,
            "digest": record.digest,
            "risk": copy.deepcopy(manifest["risk"]),
            "granted_permissions": list(record.granted_permissions),
        }

    def _record(self, capability_id: str) -> CapabilityRecord:
        try:
            return self.records[capability_id]
        except KeyError as error:
            raise CapabilityError("capability is not registered") from error


class PersistentCapabilityRegistry(CapabilityRegistry):
    """Atomic JSON persistence for the reference registry.

    The store contains manifests, decisions and metadata-only audit events. It never
    persists credential values or execution payloads.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(clock=clock)
        self.path = Path(path)
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CapabilityError("capability registry store is unreadable") from error
        if payload.get("schema_version") != "0.1" or not isinstance(payload.get("records"), list):
            raise CapabilityError("capability registry store is invalid")
        for item in payload["records"]:
            if not isinstance(item, dict):
                raise CapabilityError("capability registry record is invalid")
            manifest = validate_manifest(item.get("manifest"))
            canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            digest = hashlib.sha256(canonical).hexdigest()
            status = item.get("status")
            if item.get("digest") != digest or status not in {"pending_review", "approved", "rejected"}:
                raise CapabilityError("capability registry record integrity check failed")
            reviewer = item.get("reviewer")
            granted = item.get("granted_permissions") or []
            events = item.get("events") or []
            if reviewer is not None and not isinstance(reviewer, str):
                raise CapabilityError("capability registry reviewer is invalid")
            if not isinstance(granted, list) or not all(isinstance(value, str) for value in granted):
                raise CapabilityError("capability registry permissions are invalid")
            if not isinstance(events, list) or not all(isinstance(value, dict) for value in events):
                raise CapabilityError("capability registry events are invalid")
            record = CapabilityRecord(
                manifest=manifest,
                digest=digest,
                status=status,
                reviewer=reviewer,
                granted_permissions=tuple(sorted(granted)),
                events=copy.deepcopy(events),
            )
            if status == "approved" and not set(record.granted_permissions).issubset(
                set(manifest["permissions"]["actions"])
            ):
                raise CapabilityError("stored approval exceeds declared permissions")
            capability_id = manifest["identity"]["id"]
            if capability_id in self.records:
                raise CapabilityError("capability registry contains duplicate identities")
            self.records[capability_id] = record

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "0.1",
            "records": [
                {
                    "manifest": record.manifest,
                    "digest": record.digest,
                    "status": record.status,
                    "reviewer": record.reviewer,
                    "granted_permissions": list(record.granted_permissions),
                    "events": record.events,
                }
                for _, record in sorted(self.records.items())
            ],
        }
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise CapabilityError("capability registry store could not be persisted") from error

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            before = len(self.records)
            result = super().submit(payload)
            if len(self.records) != before:
                self._save()
            return result

    def decide(
        self,
        capability_id: str,
        *,
        reviewer: str,
        approved: bool,
        granted_permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            result = super().decide(
                capability_id,
                reviewer=reviewer,
                approved=approved,
                granted_permissions=granted_permissions,
            )
            self._save()
            return result

    def plan(
        self,
        capability_id: str,
        operation_id: str,
        *,
        action: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with self._lock:
            result = super().plan(
                capability_id,
                operation_id,
                action=action,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
            self._save()
            return result


def _validate_payload(value: Any, schema: dict[str, Any], label: str) -> None:
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise CapabilityError(f"{label} must be an object")
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        if not required.issubset(value):
            raise CapabilityError(f"{label} is missing required fields")
        if schema.get("additionalProperties") is False and not set(value).issubset(properties):
            raise CapabilityError(f"{label} contains unknown fields")
        for key, nested in value.items():
            if key in properties:
                _validate_payload(nested, properties[key], f"{label}.{key}")
    elif expected == "array":
        if not isinstance(value, list):
            raise CapabilityError(f"{label} must be an array")
        if len(value) > int(schema.get("maxItems", len(value))):
            raise CapabilityError(f"{label} exceeds the item limit")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, nested in enumerate(value):
                _validate_payload(nested, item_schema, f"{label}[{index}]")
    elif expected == "string":
        if not isinstance(value, str):
            raise CapabilityError(f"{label} must be a string")
        if len(value) > int(schema.get("maxLength", len(value))):
            raise CapabilityError(f"{label} exceeds the length limit")
    elif expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise CapabilityError(f"{label} must be an integer")
    elif expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise CapabilityError(f"{label} must be a number")
    elif expected == "boolean" and not isinstance(value, bool):
        raise CapabilityError(f"{label} must be a boolean")


class CapabilityExecutor:
    """Execute an approved generic plan over a bounded MCP or A2A HTTP transport."""

    def __init__(
        self,
        *,
        environ: dict[str, str] | None = None,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.environ = dict(os.environ if environ is None else environ)
        self.opener = opener

    def _endpoint(self, transport: dict[str, Any]) -> str:
        endpoint = self.environ.get(str(transport.get("endpoint_env")), "").strip().rstrip("/")
        parsed = urlsplit(endpoint)
        if not endpoint or parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise CapabilityError("capability endpoint is unavailable")
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"} or "." not in parsed.hostname
        if parsed.scheme != "https" and not local:
            raise CapabilityError("remote capability endpoints require HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CapabilityError("capability endpoint may not contain credentials or query controls")
        return endpoint

    def healthy(self, manifest: dict[str, Any]) -> bool:
        """Probe only a runtime-owned endpoint for an already approved manifest."""
        path = manifest["transport"].get("health_path")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            return False
        if urlsplit(path).query or urlsplit(path).fragment or len(path) > 160:
            return False
        try:
            endpoint = self._endpoint(manifest["transport"])
            request = Request(urljoin(endpoint + "/", path), headers={"Accept": "application/json"})
            with self.opener(request, timeout=2) as response:
                raw = response.read(4097)
            if len(raw) > 4096:
                return False
            result = json.loads(raw)
            return isinstance(result, dict) and result.get("status") in {"healthy", "ok"}
        except (CapabilityError, HTTPError, URLError, TimeoutError, OSError, ValueError):
            return False

    def execute(self, plan: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        _reject_secret_material(payload, "input")
        _validate_payload(payload, plan["input_schema"], "input")
        transport = plan["transport"]
        protocol = transport["protocol"]
        if protocol not in {"mcp", "a2a"}:
            raise CapabilityError("live executor supports MCP and A2A transports only")
        if plan.get("credentials_required"):
            raise CapabilityError("credentialed capabilities require a governed transport adapter")
        endpoint = self._endpoint(transport)

        if protocol == "mcp":
            request_payload = {
                "jsonrpc": "2.0",
                "id": plan["idempotency_key"],
                "method": "tools/call",
                "params": {"name": plan["operation_id"], "arguments": payload},
            }
        else:
            request_payload = {
                "taskId": plan["idempotency_key"],
                "correlationId": plan["correlation_id"],
                "operation": plan["operation_id"],
                "input": payload,
            }
        request = Request(
            urljoin(endpoint + "/", "v1/capabilities/execute"),
            data=json.dumps(request_payload, separators=(",", ":")).encode(),
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": plan["idempotency_key"],
                "X-AIMEC-Correlation-ID": plan["correlation_id"],
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=int(plan["timeout_seconds"])) as response:
                raw = response.read(2_000_001)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise CapabilityError("capability transport request failed") from error
        if len(raw) > 2_000_000:
            raise CapabilityError("capability response exceeds 2 MB")
        try:
            response_payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise CapabilityError("capability response is not valid JSON") from error
        result = response_payload.get("result") if protocol == "mcp" else response_payload.get("result", response_payload)
        _validate_payload(result, plan["output_schema"], "output")
        return {
            "capability_id": plan["capability_id"],
            "operation_id": plan["operation_id"],
            "action": plan["action"],
            "correlation_id": plan["correlation_id"],
            "transport": protocol,
            "result": result,
        }
