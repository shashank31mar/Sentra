"""Integration test for manifest schema and multi-writer blocks contract."""

from benchmarks.core.manifest import Manifest


REQUIRED_BLOCKS = {
    "benchmark",
    "engine",
    "model",
    "policy",
    "isolation",
    "corpus",
    "results",
    "errors",
    "disclosures",
    "accounting",
    "schema_version",
    "exit",
}


def test_manifest_all_writers(tmp_path):
    m = Manifest.collect(adapter_name="agentdojo", allow_dirty=True)
    
    # Simulate sibling writers contributing blocks
    m.data["engine"]["detector_readiness"] = {"d1": "scored", "d2": "scored"}
    m.data["policy"]["synthesized"] = True
    m.data["results"]["mode_a"] = {"d1": {"recall": 0.95}}
    m.data["results"]["mode_b"] = {"asr_reduction_pp": 25.0}

    path = m.write(tmp_path, exit_status="complete")
    assert path.exists()

    top_keys = set(m.data.keys())
    assert top_keys == REQUIRED_BLOCKS
