"""Local Sigma rules loader for benchmark harness (LLD 41 / Local E2E).

Loads prompt-signature rules from local YAML files into memory, compiling
their matchers and condition ASTs so they can be injected into SigmaEngine's
rules_cache without requiring DynamoDB metadata or S3 rule storage.
"""

import logging
from pathlib import Path
from typing import List, Optional
import yaml

from app.validators.sigma_engine import SigmaRule, get_sigma_engine, DialectError

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_SIGMA_DIR = Path("sample-artifacts/sigma_rules/llm")


def load_local_sigma_rules(directory: Optional[Path] = None) -> List[SigmaRule]:
    """Read and parse all .yaml / .yml files in directory into compiled SigmaRules."""
    rule_dir = directory or DEFAULT_LOCAL_SIGMA_DIR
    if not rule_dir.is_dir():
        logger.warning(f"Local sigma rules directory does not exist: {rule_dir}")
        return []

    engine = get_sigma_engine()
    rules: List[SigmaRule] = []

    for path in sorted(rule_dir.glob("*.yaml")) + sorted(rule_dir.glob("*.yml")):
        # avoid duplicate if .yaml and .yml glob overlapping
        try:
            content = path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if not isinstance(data, dict) or "detection" not in data:
                continue
            rule = engine._parse_sigma_rule(data)
            rules.append(rule)
            logger.debug(f"Loaded local sigma rule: {rule.title} ({rule.id})")
        except DialectError as e:
            logger.warning(f"Skipping dialect-invalid sigma rule in {path.name}: {e}")
        except Exception as e:
            logger.warning(f"Failed to parse local sigma rule in {path.name}: {e}")

    logger.info(f"Loaded {len(rules)} local sigma rules from {rule_dir}")
    return rules
