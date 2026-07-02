"""Path + environment bootstrap for the `tests/unit/` suite.

WHY THIS FILE EXISTS
--------------------
`tests/unit/` mixes tests for TWO separate sub-projects that live in different
directories and are never installed onto sys.path:

  * CDK stack tests  ->  `from stacks.api_stack import ApiStack`
                          `from config import Config`
    ...resolve against  <repo>/cdk/

  * Controller tests ->  `from app.services.policy_validator import ...`
    ...resolve against  <repo>/src/security-controller/
    ...and they transitively import `from schemas.policy_schema import ...`
    which resolves against  <repo>/scripts/

There is no pytest.ini / installed package wiring this up, so without this
conftest every collection fails with ModuleNotFoundError.

IMPORTANT NAME COLLISION
------------------------
The controller ships a *package* `app/` (src/security-controller/app) while the
CDK app ships a *module* `app.py` (cdk/app.py). If `cdk/` were placed ahead of
`src/security-controller/` on sys.path, `import app` would resolve to the CDK
script instead of the controller package. The CDK `app.py` is only ever run as
a script (`cdk synth`), never imported by these tests, so we:
    - FRONT-insert  src/security-controller  and  scripts   (controller wins)
    - APPEND        cdk                                       (stacks/config)
This ordering is the one verified to make every import in tests/unit/ resolve.
"""

import os
import sys
from pathlib import Path

# tests/unit/conftest.py -> tests/unit -> tests -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[2]

_CONTROLLER = str(_REPO_ROOT / "src" / "security-controller")
_SCRIPTS = str(_REPO_ROOT / "scripts")
_CDK = str(_REPO_ROOT / "cdk")

# Front-insert the controller + scripts so `import app` = controller package
# (and `from schemas.policy_schema import ...` resolves against scripts/).
for _front in (_SCRIPTS, _CONTROLLER):
    if _front not in sys.path:
        sys.path.insert(0, _front)

# Append cdk LAST so `from stacks... import` / `from config import Config`
# resolve, but the CDK `app.py` module never shadows the controller `app/` pkg.
if _CDK not in sys.path:
    sys.path.append(_CDK)

# ---------------------------------------------------------------------------
# Moto-safe AWS environment defaults.
#
# The CDK `Config` load reads account_id from env, and boto3 resource/client
# construction (both in controller code paths and in CDK synth) must NEVER hit
# real AWS credentials/regions during unit tests. We use setdefault so a caller
# that already exported these (e.g. the documented gate command) wins.
# ---------------------------------------------------------------------------
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_ACCOUNT_ID", "123456789012")
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("ENVIRONMENT", "dev")
