"""Azure Functions entrypoint for the Identity agent (Python v2 model).

Thin HTTP wrapper over ``identity_core.dispatch`` — the tool logic + ``aegion-guard`` integration live
there so they're testable without this package. Routes:
  * POST /api/tool/{tool_name}  -> validate with Sentra, run the tool on ALLOW, 403 on DENY
  * GET  /api/health           -> liveness

Packaging (azd): ``aegion_guard`` and ``common/`` are vendored alongside this file; stdlib-only deps
mean no Oryx remote build is needed (best-practices §11). ``AzureWebJobsFeatureFlags=EnableWorkerIndexing``
must be set (v2 model) — see infra.
"""
from __future__ import annotations

import json

import azure.functions as func

from identity_core import dispatch

app = func.FunctionApp()


def _json(status: int, body: dict) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body), status_code=status, mimetype="application/json")


# DEMO-ONLY: ANONYMOUS auth — anyone with the URL can invoke a tool. Safe here (pure tools, no
# datastore writes; the Sentra x-api-key stays server-side), but a real integration MUST add a
# Function key / front-door auth (LLD 22 §10.5, best-practices §11 Azure backlog).
@app.route(route="tool/{tool_name}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def tool_call(req: func.HttpRequest) -> func.HttpResponse:
    status, body = await dispatch(req)
    return _json(status, body)


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json(200, {"status": "ok", "agent": "acme-identity-agent"})
