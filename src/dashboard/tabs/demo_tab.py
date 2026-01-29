"""
Demo Tab - Scenario management and comparison visualization
Sentra MVP - Workstream 14

Best Practices Applied:
- @st.cache_data for API calls with TTL
- Unique namespaced widget keys (demo_tab_{action}_{id})
- Error handling with graceful degradation
- No st.rerun() during render (only after user actions)
- Manual refresh button (avoids auto-refresh complexity)
"""
import streamlit as st
import logging
import requests
from services.demo_orchestrator_client import get_demo_client

logger = logging.getLogger(__name__)


def render():
    """Render Demo Scenarios tab"""
    st.header("🎯 Demo Scenarios")
    st.caption("Control and monitor demo scenarios that test security across different agent types")
    
    # Manual refresh button - namespaced key
    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("🔄 Refresh", key="demo_tab_refresh", help="Refresh scenario and comparison data"):
            _fetch_scenarios_cached.clear()
            _fetch_comparison_cached.clear()
            # Also clear server-side cache for fresh data
            try:
                client = get_demo_client()
                client.refresh_comparison_cache()
            except Exception:
                pass  # Ignore errors, local cache is cleared anyway
            st.rerun()
    
    # Fetch scenarios with loading indicator
    with st.spinner("Loading scenarios..."):
        scenarios = _fetch_scenarios_cached()
    
    if not scenarios:
        st.info("📭 No scenarios available. Check demo orchestrator connection.")
    else:
        st.caption(f"Showing {len(scenarios)} scenario(s)")
        for scenario in scenarios:
            _render_scenario_card(scenario)
        
        st.markdown("---")
        _render_global_controls()
    
    st.markdown("---")
    
    # Comparison results with loading indicator
    st.subheader("📊 Latest Results (Last 1 Hour)")
    with st.spinner("Loading comparison data..."):
        _render_comparison_results()


@st.cache_data(ttl=30)
def _fetch_scenarios_cached():
    """Fetch scenarios with caching (30s TTL)"""
    try:
        client = get_demo_client()
        return client.fetch_scenarios()
    except requests.Timeout:
        logger.error("Timeout fetching scenarios")
        return []
    except requests.RequestException as e:
        logger.warning(f"Demo orchestrator unavailable: {e}")
        return []
    except Exception as e:
        logger.error(f"Failed to fetch scenarios: {e}")
        return []


def _render_scenario_card(scenario: dict):
    """Render individual scenario card with controls"""
    scenario_id = scenario["scenario_id"]
    # Status can be a dict {"status": "running"} or a string
    status_raw = scenario.get("status", "stopped")
    status = status_raw.get("status", "stopped") if isinstance(status_raw, dict) else status_raw
    status_icon = "🟢" if status == "running" else "⚪"
    
    with st.expander(
        f"{status_icon} {scenario['name']} - {status.upper()}",
        expanded=False
    ):
        # Description
        st.write(scenario.get("description", ""))
        
        # Metadata in columns
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Mode", scenario.get("mode", "manual").capitalize())
        with col2:
            interval = scenario.get("interval")
            st.metric("Interval", f"{interval}s" if interval else "Manual")
        with col3:
            st.metric("Prompts", scenario.get("prompt_count", 0))
        
        # Action buttons - namespaced keys: demo_tab_{action}_{scenario_id}
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button(
                "▶ Run Once",
                key=f"demo_tab_run_{scenario_id}",
                help="Execute scenario immediately"
            ):
                _trigger_scenario(scenario_id)
        
        with col2:
            if status == "running":
                if st.button(
                    "⏸ Pause",
                    key=f"demo_tab_pause_{scenario_id}",
                    help="Pause continuous execution"
                ):
                    _pause_scenario(scenario_id)
            else:
                if st.button(
                    "▶ Resume",
                    key=f"demo_tab_resume_{scenario_id}",
                    help="Resume continuous execution"
                ):
                    _start_scenario(scenario_id)
        
        with col3:
            if st.button(
                "📋 Details",
                key=f"demo_tab_details_{scenario_id}",
                help="View scenario prompts"
            ):
                st.session_state[f"demo_tab_show_details_{scenario_id}"] = True
        
        # Show details if requested
        if st.session_state.get(f"demo_tab_show_details_{scenario_id}", False):
            _show_scenario_details(scenario_id)


def _show_scenario_details(scenario_id: str):
    """Show scenario details with prompts (not cached - user triggered)"""
    try:
        client = get_demo_client()
        scenario = client.get_scenario_details(scenario_id)
        
        st.markdown("---")
        st.markdown(f"### 📋 {scenario['name']} - Details")
        
        # Metadata
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Mode:** {scenario.get('mode', 'manual')}")
            interval = scenario.get("interval")
            if interval:
                st.write(f"**Interval:** Every {interval} seconds")
        with col2:
            prompts = scenario.get("prompts", [])
            st.write(f"**Prompts:** {len(prompts)}")
        
        # Target agents
        agents = scenario.get("agents", {})
        st.write("**Target Agents:**")
        for agent in agents.get("self_hosted", []):
            st.write(f"- {agent} (Self-Hosted)")
        for agent in agents.get("bedrock", []):
            st.write(f"- {agent} (Bedrock)")
        
        # Prompts
        st.write("**Test Prompts:**")
        for idx, prompt in enumerate(scenario.get("prompts", []), 1):
            with st.container():
                st.markdown(f"**{idx}. {prompt.get('id', f'prompt-{idx}')}**")
                st.code(prompt.get("text", ""), language=None)
                st.caption(
                    f"Expected: **{prompt.get('expected_decision', 'N/A')}** "
                    f"({prompt.get('expected_threat', 'N/A')})"
                )
        
        # Close button - namespaced key
        if st.button("Close Details", key=f"demo_tab_close_details_{scenario_id}"):
            st.session_state[f"demo_tab_show_details_{scenario_id}"] = False
            st.rerun()
    
    except Exception as e:
        st.error(f"Failed to load scenario details: {e}")


def _trigger_scenario(scenario_id: str):
    """Trigger scenario once"""
    try:
        client = get_demo_client()
        result = client.trigger_scenario(scenario_id)
        run_id = result.get("run_id", "unknown")
        summary = result.get("summary", {})
        match_rate = summary.get("match_rate", 0)
        st.success(f"✅ Scenario triggered! Run ID: {run_id} | Match rate: {match_rate}%")
    except Exception as e:
        st.error(f"❌ Failed to trigger scenario: {e}")


def _start_scenario(scenario_id: str):
    """Start continuous execution"""
    try:
        client = get_demo_client()
        client.start_scenario(scenario_id)
        st.success("✅ Scenario started (continuous)")
        st.rerun()
    except Exception as e:
        st.error(f"❌ Failed to start scenario: {e}")


def _pause_scenario(scenario_id: str):
    """Pause continuous execution"""
    try:
        client = get_demo_client()
        client.pause_scenario(scenario_id)
        st.success("✅ Scenario paused")
        st.rerun()
    except Exception as e:
        st.error(f"❌ Failed to pause scenario: {e}")


def _render_global_controls():
    """Render global pause/resume controls"""
    st.subheader("🎮 Global Controls")
    st.caption("Manage all scenarios at once")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("⏸ Pause All", key="demo_tab_pause_all", help="Pause all running scenarios", use_container_width=True):
            _pause_all_scenarios()
    
    with col2:
        if st.button("▶ Resume All", key="demo_tab_resume_all", help="Resume all continuous scenarios", use_container_width=True):
            _resume_all_scenarios()


def _pause_all_scenarios():
    """Pause all running scenarios"""
    try:
        client = get_demo_client()
        result = client.pause_all()
        paused = result.get("paused_count", 0)
        st.success(f"✅ Paused {paused} scenario(s)")
        st.rerun()
    except Exception as e:
        st.error(f"❌ Failed to pause scenarios: {e}")


def _resume_all_scenarios():
    """Resume all continuous scenarios"""
    try:
        client = get_demo_client()
        result = client.start_all_continuous()
        started = result.get("started_count", 0)
        st.success(f"✅ Started {started} scenario(s)")
        st.rerun()
    except Exception as e:
        st.error(f"❌ Failed to start scenarios: {e}")


def _render_comparison_results():
    """Render comparison metrics grid with per-agent breakdown"""
    comparison = _fetch_comparison_cached()

    if comparison is None:
        st.warning("⚠️ Could not load comparison data. Demo orchestrator may be unavailable.")
        return

    # Extract all agents from all categories and DEDUPLICATE by agent_id
    agents_dict = {}  # Key: agent_id, Value: agent data
    for category, data in comparison.items():
        if isinstance(data, dict) and "agents" in data:
            for agent_id, agent_data in data["agents"].items():
                # Only add if not already present (prevents duplicates)
                if agent_id not in agents_dict:
                    agents_dict[agent_id] = {
                        "agent_id": agent_id,
                        "platform": agent_data.get("platform", "unknown"),
                        "security_type": agent_data.get("security_type", "unknown"),
                        "total": agent_data.get("total", 0),
                        "allowed": agent_data.get("allowed", 0),
                        "denied": agent_data.get("denied", 0),
                        "allowed_pct": agent_data.get("allowed_pct", 0),
                        "denied_pct": agent_data.get("denied_pct", 0)
                    }

    all_agents = list(agents_dict.values())

    if not all_agents:
        st.info("📊 No demo data yet. Run scenarios to generate comparison data.")
        return

    total_requests = sum(agent["total"] for agent in all_agents)
    st.caption(f"Total requests analyzed: {total_requests}")

    # Group agents: self-hosted secured, bedrock secured, bedrock unsecured
    self_hosted = [a for a in all_agents if a["platform"] == "sentra" and a["security_type"] == "secured"]
    bedrock_secured = [a for a in all_agents if a["platform"] == "bedrock" and a["security_type"] == "secured"]
    bedrock_unsecured = [a for a in all_agents if a["platform"] == "bedrock" and a["security_type"] == "unsecured"]

    # Render in columns
    num_cols = len(self_hosted) + len(bedrock_secured) + len(bedrock_unsecured)
    if num_cols == 0:
        st.info("📊 No agents with data yet.")
        return

    cols = st.columns(min(num_cols, 4))  # Max 4 columns
    col_idx = 0

    # Render all agents using their metadata
    for agent in self_hosted + bedrock_secured + bedrock_unsecured:
        with cols[col_idx % len(cols)]:
            # Get platform and security info from agent metadata
            platform = agent["platform"].title()
            security_type = agent["security_type"].title()

            # Clean up agent name
            agent_name = (agent["agent_id"]
                         .replace("sentra-mvp-", "")
                         .replace("-agent", "")
                         .replace("-unsecured", "")
                         .replace("-", " ")
                         .title())

            # Determine icon and caption based on metadata
            if agent["platform"] == "sentra":
                icon = "🔒"
                caption_text = f"{icon} {platform} ({security_type})"
            elif agent["security_type"] == "secured":
                icon = "✅"
                caption_text = f"{icon} {platform} ({security_type})"
            else:
                icon = "⚠️"
                caption_text = f"{icon} {platform} ({security_type})"

            st.markdown(f"**{agent_name}**")
            st.caption(caption_text)
            _render_agent_metrics(agent, is_unsecured=(agent["security_type"] == "unsecured"))
        col_idx += 1


@st.cache_data(ttl=30)
def _fetch_comparison_cached():
    """Fetch comparison data with per-agent breakdown (30s TTL)"""
    try:
        client = get_demo_client()
        data = client.get_comparison(hours=1, include_prompts=True)  # Get per-agent breakdown
        return data.get("comparison", {})
    except requests.Timeout:
        logger.warning("Comparison data request timed out")
        return None
    except Exception as e:
        logger.warning(f"Could not load comparison data: {e}")
        return None


def _render_agent_metrics(metrics: dict, is_unsecured: bool = False):
    """Render metrics for single agent type"""
    total = metrics.get("total", 0)
    
    if total == 0:
        st.info("No data yet")
        return
    
    denied_pct = metrics.get("denied_pct", 0)
    allowed_pct = metrics.get("allowed_pct", 0)
    denied = metrics.get("denied", 0)
    allowed = metrics.get("allowed", 0)
    
    # Denied metric
    st.metric(
        "Denied",
        f"{denied_pct}%",
        delta=f"{denied} requests",
        delta_color="normal"
    )
    
    # Allowed metric
    if is_unsecured:
        st.metric(
            "Allowed ⚠️",
            f"{allowed_pct}%",
            delta=f"{allowed} requests",
            delta_color="off"
        )
    else:
        st.metric(
            "Allowed",
            f"{allowed_pct}%",
            delta=f"{allowed} requests",
            delta_color="inverse"
        )
    
    # Security score (100 - allowed_pct)
    score = 100 - allowed_pct
    if score > 80:
        st.success(f"Security Score: {score:.1f}%")
    elif score > 50:
        st.warning(f"Security Score: {score:.1f}%")
    else:
        st.error(f"Security Score: {score:.1f}%")
