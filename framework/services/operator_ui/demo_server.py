"""Restricted AIMEC WebMCP business-agent demo surface."""
from __future__ import annotations
import json, os, re
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen
from aimec_http import ExecutionEventStore
from aimec_task_store import CapabilityTaskStore, TaskLimit
from capability_jobs import CapabilityJobs
from webmcp import AlphaWebMcpAdapter, WebMcpError
PUBLIC=Path(__file__).parent/"public"
ASSETS={"/":("demo.html","text/html; charset=utf-8"),"/assets/demo.css":("demo.css","text/css; charset=utf-8"),"/assets/demo.js":("demo.js","application/javascript; charset=utf-8"),"/assets/webmcp.js":("webmcp.js","application/javascript; charset=utf-8")}
def build_identity(expected_commit="unrecorded",*,https=False,path=None):
    if path is None:
        path=Path(__file__).with_name("build-identity.json")
        if not path.exists(): path=Path(__file__).resolve().parents[2]/"deploy/bc092/build-identity.json"
    identity=json.loads(Path(path).read_text()); verified=identity.get("verified_git_source") is True and re.fullmatch(r"[0-9a-f]{40}",str(identity.get("source_commit",""))) and re.fullmatch(r"[0-9a-f]{64}",str(identity.get("source_digest","")))
    if (https and not verified) or (expected_commit!="unrecorded" and (not verified or expected_commit!=identity.get("source_commit"))): raise ValueError("verified build identity required; prepare the exact Git release before HTTPS launch")
    return {"source_commit":identity.get("source_commit","unrecorded"),"source_digest":identity.get("source_digest","unrecorded"),"source_verified":bool(verified)}
class DemoHandler(BaseHTTPRequestHandler):
    adapter:AlphaWebMcpAdapter; jobs:CapabilityJobs; public_origin=""; source_identity={"source_commit":"unrecorded","source_digest":"unrecorded","source_verified":False}
    def setup(self): super().setup(); self.connection.settimeout(10); self.new_session=None
    def owner(self):
        cookie=SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie","")); supplied=cookie.get("aimec_demo"); owner,self.new_session=self.jobs.store.session(supplied.value if supplied else None); return owner
        except TaskLimit as exc: raise WebMcpError(429,str(exc)) from exc
    def send(self,status,body,content_type="application/json; charset=utf-8"):
        if isinstance(body,dict): body=json.dumps(body,allow_nan=False,separators=(",",":")).encode()
        self.send_response(status); self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control","no-store"); self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Referrer-Policy","no-referrer"); self.send_header("X-Frame-Options","DENY"); self.send_header("Content-Security-Policy","default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if self.new_session:
            secure="; Secure" if self.public_origin.startswith("https://") else ""; self.send_header("Set-Cookie","aimec_demo="+self.new_session+"; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400"+secure)
        self.end_headers(); self.wfile.write(body)
    def verify_origin(self,*,mutation=False):
        if self.public_origin and self.headers.get("Host")!=urlsplit(self.public_origin).netloc: raise WebMcpError(403,"host_not_allowed")
        if mutation:
            host=self.headers.get("Host",""); origin=self.headers.get("Origin"); allowed={self.public_origin} if self.public_origin else {"http://"+host,"https://"+host}
            if (origin is not None and origin not in allowed) or self.headers.get("Sec-Fetch-Site")=="cross-site": raise WebMcpError(403,"cross_origin_request_denied")
            if self.headers.get_content_type()!="application/json": raise WebMcpError(415,"json_content_type_required")
    def do_GET(self):
        route=urlsplit(self.path).path
        try:
            if route=="/health": self.send(200,{"status":"healthy","service":"alpha-demo"}); return
            self.verify_origin()
            if route in ASSETS:
                name,content_type=ASSETS[route]; self.send(200,(PUBLIC/name).read_bytes(),content_type); return
            if route.startswith("/api/webmcp/") and self.headers.get("Sec-Fetch-Site")=="cross-site": raise WebMcpError(403,"cross_origin_request_denied")
            if route=="/api/webmcp/config": self.owner(); self.send(200,{"mode":"business_agent_capability_jobs",**self.source_identity,"business_logic_mocked":False,"local_model_required":True,"model":os.getenv("AIMEC_LLM_MODEL","qwen3:4b"),"public_or_synthetic_inputs_only":True,"session_retention_hours":24,"business_tool_operations":5,"specialist_agents":2}); return
            owner=self.owner() if route.startswith("/api/webmcp/") else None
            if route=="/api/webmcp/tools": result=self.adapter.get_available_tools()
            elif route=="/api/webmcp/agents": result=self.adapter.get_available_agents()
            elif route.startswith("/api/webmcp/tasks/"):
                parts=route.split("/"); methods={"status":self.adapter.get_task_status,"result":self.adapter.get_task_result,"evidence":self.adapter.get_execution_evidence}
                if len(parts)!=6 or parts[-1] not in methods: raise WebMcpError(404,"not_found")
                result=methods[parts[-1]](unquote(parts[4]),owner=owner)
            else: raise WebMcpError(404,"not_found")
            self.send(200,result)
        except WebMcpError as exc: self.send(exc.status,{"error":exc.code})
        except Exception: self.send(503,{"error":"demo_service_unavailable"})
    def do_POST(self):
        route=urlsplit(self.path).path
        try:
            if route not in {"/api/webmcp/tools/run","/api/webmcp/tasks/delegate"}: raise WebMcpError(404,"not_found")
            self.verify_origin(mutation=True); length=int(self.headers.get("Content-Length","0"))
            if not 0<length<=65536: raise WebMcpError(413,"request_body_limit")
            payload=json.loads(self.rfile.read(length))
            if not isinstance(payload,dict): raise WebMcpError(400,"invalid_request_body")
            owner=self.owner()
            if route.endswith("/run"): result=self.adapter.run_tool(payload,owner=owner); status=200
            else: result=self.adapter.delegate_task(payload,owner=owner); status=202
            self.send(status,result)
        except WebMcpError as exc: self.send(exc.status,{"error":exc.code})
        except (ValueError,TypeError): self.send(400,{"error":"invalid_request_body"})
        except Exception: self.send(503,{"error":"demo_service_unavailable"})
    def log_message(self,*_): pass
def main():
    origin=os.getenv("AIMEC_DEMO_PUBLIC_ORIGIN","").rstrip("/")
    if origin:
        parsed=urlsplit(origin)
        if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment: raise ValueError("AIMEC_DEMO_PUBLIC_ORIGIN must be an origin without credentials")
    DemoHandler.public_origin=origin; DemoHandler.source_identity=build_identity(os.getenv("AIMEC_DEMO_SOURCE_COMMIT","unrecorded"),https=origin.startswith("https://")); store=CapabilityTaskStore(os.getenv("AIMEC_WEBMCP_JOB_DB","/var/lib/aimec/webmcp-jobs.sqlite3")); store.recover_interrupted(); jobs=CapabilityJobs(os.environ["AIMEC_CAPABILITY_REGISTRY_URL"],store,ExecutionEventStore(),opener=urlopen); DemoHandler.jobs=jobs; DemoHandler.adapter=AlphaWebMcpAdapter(os.environ["AIMEC_CAPABILITY_REGISTRY_URL"],agent_directory=lambda:{"nodes":[]},coordinator=None,execution_jobs=jobs); server=ThreadingHTTPServer((os.getenv("AIMEC_HOST","0.0.0.0"),int(os.getenv("AIMEC_PORT","8020"))),DemoHandler)
    try: server.serve_forever()
    finally: server.server_close(); jobs.close()
if __name__=="__main__": main()
