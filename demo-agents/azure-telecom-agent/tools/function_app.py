"""Azure Functions entrypoint for the Telecom agent (Python v2 model).

Thin HTTP wrapper over ``telecom_core.dispatch``. Routes:
  * POST /api/tool/{tool_name}  -> validate with Sentra, run the tool on ALLOW, 403 on DENY
  * GET  /api/health
Packaging mirrors the identity agent (SDK + common vendored; stdlib-only, EnableWorkerIndexing).
"""
from __future__ import annotations

import json

import azure.functions as func

from telecom_core import dispatch

app = func.FunctionApp()


def _json(status: int, body: dict) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body), status_code=status, mimetype="application/json")


# DEMO-ONLY: ANONYMOUS auth — see identity function_app.py. A real integration MUST add a Function
# key / front-door auth (LLD 22 §10.5, best-practices §11 Azure backlog).
@app.route(route="tool/{tool_name}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def tool_call(req: func.HttpRequest) -> func.HttpResponse:
    status, body = await dispatch(req)
    return _json(status, body)


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json(200, {"status": "ok", "agent": "acme-telecom-agent"})
