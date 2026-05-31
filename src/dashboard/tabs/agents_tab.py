"""
Agents Tab - Agent management, policies, and tools configuration.

Milestone 5: Integrated with real Security Controller APIs.
Workstream 15 M4: Cross-cloud agent inventory section added at the top.
"""
import streamlit as st
import pandas as pd
from typing import Optional, Dict, List
from components import agent_list, agent_details, agent_policies
from services.security_controller_client import security_controller_client
from services import agent_caller_factory
from utils.cloud_badges import badge_for
import logging
import sys

logger = logging.getLogger(__name__)


@st.cache_data(ttl=5)  # Cache for 5 seconds to reduce API calls and timing issues
def _fetch_agents_from_api():
    """Cached API call to Security Controller."""
    return security_controller_client.get_agents()


def _fetch_agents() -> List[Dict]:
    """
    Fetch agents from Security Controller API (cached).
    Falls back to mock data if API fails.

    Note: Internal agents (visibility='internal') are filtered at API source.
    """
    try:
        logger.info("Fetching agents from Security Controller API (cached)...")
        response = _fetch_agents_from_api()
        logger.info(f"API response: {response}")

        agents = response.get('agents', [])
        logger.info(f"Found {len(agents)} agents in API response")

        if agents:
            # Transform API response to component format.
            # Note: internal agents are filtered at API source (agent_service.py),
            # bedrock is also filtered at the API source. Azure Foundry agents
            # have their own UI now (Agent Type radio) so we filter them here
            # client-side until the controller filter is updated.
            result = []
            for agent in agents:
                if agent.get('platform') == 'azure_foundry':
                    continue
                agent_id = agent.get('agent_id', agent.get('id', 'unknown'))
                logger.info(f"Processing agent: {agent_id}")

                # Map API response fields to component format
                result.append({
                    'id': agent_id,
                    'name': agent.get('name', 'Unknown Agent'),
                    'status': agent.get('status', 'running'),
                    'description': agent.get('description', ''),
                    # Runtime metrics
                    'uptime': agent.get('uptime', agent.get('uptime_seconds', 'N/A')),
                    'trust_score': agent.get('trust_score_avg', agent.get('trust_score', 0)),
                    'requests': agent.get('requests_total', 0),
                    'allow_count': agent.get('requests_allowed', 0),
                    'deny_count': agent.get('requests_denied', 0),
                })

            if result:
                logger.info(f"Returning {len(result)} agents from API")
                return result
            else:
                logger.warning("All agents were filtered out, using mock data")
        else:
            logger.warning("No agents in API response, using mock data")

        # Fallback to mock data
        return agent_list._get_mock_agents()

    except Exception as e:
        logger.error(f"Failed to fetch agents from API: {e}", exc_info=True)
        return agent_list._get_mock_agents()


def render():
    """Render the Agents tab with agent selection and details."""
    try:
        # Initialize session state for selected agent
        if 'selected_agent_id' not in st.session_state:
            st.session_state.selected_agent_id = None

        if 'agent_type_mode' not in st.session_state:
            # Migrate legacy bedrock_agent_mode flag if present
            st.session_state.agent_type_mode = (
                "bedrock" if st.session_state.get("bedrock_agent_mode") else "self_hosted"
            )

        _render_cross_cloud_inventory()
        st.markdown("---")

        # Agent Type Selection (Workstream 15 M4: Azure Foundry added)
        st.markdown("### Agent Type")
        type_labels = {
            "self_hosted": "Self-Hosted (ECS)",
            "bedrock": "🟧 Bedrock Agent",
            "azure_foundry": "🟦 Azure Foundry Agent",
        }
        type_keys = list(type_labels.keys())
        current_idx = type_keys.index(st.session_state.agent_type_mode)
        chosen_label = st.radio(
            "Select agent type:",
            options=[type_labels[k] for k in type_keys],
            index=current_idx,
            horizontal=True,
            help=(
                "Self-Hosted: agents on Sentra ECS · "
                "Bedrock: AWS Bedrock agents validated via the Action Group Lambda · "
                "Azure Foundry: Azure AI Foundry agents validated via the Function tool_interceptor"
            ),
        )
        st.session_state.agent_type_mode = next(k for k, v in type_labels.items() if v == chosen_label)
        st.session_state.bedrock_agent_mode = (st.session_state.agent_type_mode == "bedrock")  # legacy

        st.markdown("---")

        if st.session_state.agent_type_mode == "bedrock":
            _render_bedrock_agent_interface()
        elif st.session_state.agent_type_mode == "azure_foundry":
            _render_azure_agent_interface()
        else:
            _render_self_hosted_agents()

    except Exception as e:
        logger.error(f"Error rendering Agents tab: {e}", exc_info=True)
        st.error(f"❌ Error loading Agents tab: {str(e)}")


def _render_self_hosted_agents():
    """Render interface for self-hosted agents."""
    try:
        # Fetch agents from API (with fallback to mock data)
        agents = _fetch_agents()

        # Create 2-column layout: Agent List (left) + Agent Details (right)
        col1, col2 = st.columns([1, 3])

        with col1:
            # Render agent list and get selected agent ID
            selected_id = agent_list.render(
                agents=agents,
                selected_agent_id=st.session_state.selected_agent_id
            )
            
            # If selection changed, update session state and trigger safe rerun
            if selected_id and selected_id != st.session_state.get("selected_agent_id"):
                st.session_state.selected_agent_id = selected_id
                # Only force rerun if session init completed (prevents SessionInfo race)
                if st.session_state.get("_session_initialized", False):
                    st.rerun()
                else:
                    # Allow normal lifecycle
                    pass

        with col2:
            # Get selected agent data
            selected_agent = _get_agent_by_id(agents, st.session_state.selected_agent_id)

            if selected_agent is None:
                # Show "Select an agent" message
                agent_details.render(None)
            else:
                # Render agent details
                agent_details.render(selected_agent)

                st.markdown("---")

                # Render agent policy configuration (includes allowed tools)
                agent_policies.render(agent_id=selected_agent['id'])

                st.markdown("---")

                # Render action buttons
                _render_agent_actions(selected_agent)
    except Exception as e:
        logger.error(f"Error rendering Agents tab: {e}", exc_info=True)
        st.error(f"❌ Error loading Agents tab: {str(e)}")


@st.cache_data(ttl=30)
def _enriched_agent_metrics() -> Dict[str, Dict]:
    """Map agent_id -> enriched metrics dict (trust_score, requests, status).

    Pulled from the Security Controller's enriched /v1/agents response. Cached
    for 30s so the cross-cloud table doesn't re-fetch on every Streamlit rerun.
    Returns {} on transport failure; the table still renders with just platform
    + region in that case.
    """
    try:
        resp = security_controller_client.get_agents_enriched()
    except Exception as exc:
        logger.warning("Failed to enrich cross-cloud agent table: %s", exc)
        return {}
    out: Dict[str, Dict] = {}
    for a in resp.get("agents", []):
        agent_id = a.get("agent_id") or a.get("id")
        if not agent_id:
            continue
        out[agent_id] = a
    return out


def _render_cross_cloud_inventory():
    """Unified cross-cloud agent inventory with a Cloud column.

    Workstream 15 M4 / Task 4.2: source-of-truth is config/agent_policies.yaml
    via agent_caller_factory.list_platforms(); enriched with runtime stats from
    the controller when available. Shows every agent regardless of platform so
    investors can see AWS + Azure (+ future GCP) governed from one pane.
    """
    st.markdown("### 🌐 Cross-Cloud Agent Inventory")
    st.caption("Every governed agent, every cloud, one table. Source: agent policies + Security Controller.")

    try:
        platform_map = agent_caller_factory.list_platforms()
    except Exception as exc:
        logger.error("agent_caller_factory.list_platforms failed: %s", exc, exc_info=True)
        st.error(f"Could not load agent platform map: {exc}")
        return

    if not platform_map:
        st.info("No agents in `config/agent_policies.yaml`. Run `python scripts/seed_policies.py` after editing.")
        return

    enriched = _enriched_agent_metrics()

    rows = []
    for agent_id, record in sorted(platform_map.items()):
        platform = record.get("platform", "unknown")
        region = record.get("cloud_region", "—") or "—"
        runtime = enriched.get(agent_id, {})
        # Issue #14 (Kiro M4 review): use .get(..., default) not `a or b` so a
        # legitimate trust_score=0 (e.g., quarantined agent) doesn't silently
        # fall through to a stale trust_score_avg.
        trust_raw = runtime.get("trust_score_avg", runtime.get("trust_score"))
        rows.append({
            "Agent": runtime.get("name", agent_id),
            "Agent ID": agent_id,
            "Cloud": badge_for(platform),
            "Region": region,
            "Status": runtime.get("status", "—"),
            "Trust": _format_trust(trust_raw),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _format_trust(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "—"


def _get_agent_by_id(agents: list, agent_id: Optional[str]) -> Optional[Dict]:
    """
    Get agent data by ID.
    
    Args:
        agents: List of agent dictionaries.
        agent_id: Agent ID to find.
    
    Returns:
        Agent dictionary or None if not found.
    """
    if agent_id is None:
        return None
    
    for agent in agents:
        if agent['id'] == agent_id:
            return agent
    
    return None


def _render_agent_actions(agent: Dict):
    """
    Render action buttons for the selected agent.
    
    Args:
        agent: Selected agent dictionary.
    """
    from utils.nav import set_target_tab_in_url
    
    st.markdown("#### Actions")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("💬 Chat with Agent", use_container_width=True, key=f"chat_btn_{agent['id']}"):
            # Set agent for chat and switch to Chats tab
            st.session_state.chat_agent_id = agent['id']
            set_target_tab_in_url("chats")
            st.info(f"Switching to Chats tab for {agent['name']}...")
            return  # Exit to allow clean re-render with Chats tab first

    with col2:
        if st.button("🔒 Quarantine", use_container_width=True, key=f"quarantine_btn_{agent['id']}"):
            st.info("Quarantine functionality coming soon")

    with col3:
        if st.button("📋 View Audit Logs", use_container_width=True, key=f"audit_btn_{agent['id']}"):
            # Set filter and switch to Audit tab
            st.session_state.audit_agent_filter = agent['id']
            set_target_tab_in_url("audit")
            st.info(f"Switching to Audit tab filtered by {agent['name']}...")
            return  # Exit to allow clean re-render with Audit tab first
    
    with col4:
        if st.button("🔄 Restart", use_container_width=True, key=f"restart_btn_{agent['id']}"):
            st.info("Restart functionality coming soon")


def _render_azure_agent_interface():
    """Interact with Azure AI Foundry agents.

    Workstream 15 M4 follow-on: this is the parallel to _render_bedrock_agent_interface
    but routes through AzureConnector → gpt-4o-mini on Azure OpenAI → Azure Function
    tool_interceptor → AWS API Gateway → Sentra controller. Every tool call is
    validated cross-cloud before execution.
    """
    import time

    st.markdown("### 🟦 Azure AI Foundry Agents")
    st.info(
        "Azure agents are validated cross-cloud via the Azure Function `tool_interceptor` → "
        "AWS API Gateway → Sentra Security Controller. Every tool call (`verify_image_authenticity`, "
        "`check_fraud_score`) is security-gated before execution. See [LLD 15 §7](../lld/15-cross-cloud-connectors.md)."
    )

    # The Azure agent inventory comes from agent_caller_factory (YAML-backed),
    # not the Bedrock discovery API. Filter to Azure agents only.
    try:
        platform_map = agent_caller_factory.list_platforms()
    except Exception as exc:
        st.error(f"Could not load agent registry: {exc}")
        return

    azure_agents = [
        {"id": aid, **rec}
        for aid, rec in platform_map.items()
        if rec.get("platform") == "azure_foundry"
    ]
    if not azure_agents:
        st.warning("No Azure Foundry agents registered in `config/agent_policies.yaml`.")
        return

    # Agent picker (currently we only ship one; built for N)
    st.markdown("#### Available Azure Agents")
    cols = st.columns(min(len(azure_agents), 3))
    for idx, agent in enumerate(azure_agents):
        with cols[idx % len(cols)]:
            st.markdown(
                f"""<div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <h4 style="margin: 0 0 8px 0;">{agent['id']}</h4>
                <p style="margin: 0; font-size: 12px; color: #6b7280;">🟦 Azure Foundry · {agent.get('cloud_region','—')}</p>
            </div>""",
                unsafe_allow_html=True,
            )
            if st.button("Select", key=f"select_azure_{agent['id']}", use_container_width=True):
                st.session_state.selected_azure_agent_id = agent['id']
                st.rerun()

    selected_id = st.session_state.get("selected_azure_agent_id")
    if not selected_id:
        st.info("👆 Select an Azure agent above to start testing.")
        return

    st.markdown("---")
    st.markdown(f"### Testing: `{selected_id}`")

    # Session management — same shape as Bedrock for UI consistency.
    if 'azure_session_id' not in st.session_state:
        st.session_state.azure_session_id = f"azure-dash-{int(time.time())}"
    col1, col2 = st.columns([3, 1])
    with col1:
        session_id = st.text_input(
            "Session ID",
            value=st.session_state.azure_session_id,
            help="Session ID for conversation continuity and audit-log correlation.",
            key="azure_session_input",
        )
    with col2:
        if st.button("🔄 New Session", key="azure_new_session"):
            st.session_state.azure_session_id = f"azure-dash-{int(time.time())}"
            st.rerun()

    st.markdown("#### Send Message")
    user_message = st.text_area(
        "Enter your message:",
        value="Verify the photo at https://example.com/photo.jpg of cracked eggs.",
        height=100,
        key="azure_user_message",
    )

    if st.button("📤 Send", use_container_width=False, type="primary", key="azure_send"):
        if not user_message.strip():
            st.error("❌ Please enter a message.")
            return
        with st.spinner(f"Invoking {selected_id} via AzureConnector..."):
            try:
                connector = agent_caller_factory.get_connector(selected_id)
                result = connector.invoke_agent(
                    agent_id=selected_id,
                    session_id=session_id,
                    user_message=user_message,
                )
            except Exception as exc:
                logger.error("Azure agent invocation failed", exc_info=True)
                st.error(f"❌ Invocation failed: {exc}")
                return

        st.markdown("---")
        st.markdown("### Results")
        if result.decision == "ALLOW":
            st.success("✅ **Decision:** ALLOW")
        elif result.decision == "DENY":
            st.error("⛔ **Decision:** DENY")
        else:
            st.warning(f"⚠️ **Decision:** {result.decision}")

        st.markdown("#### Agent Response")
        st.markdown(f"> {result.response or '(no text returned)'}")

        m1, m2, m3 = st.columns(3)
        m1.metric("Latency", f"{result.latency_ms} ms")
        m2.metric("Platform", result.platform.value if hasattr(result.platform, "value") else str(result.platform))
        m3.metric("Region", result.cloud_region or "—")

        if result.validation_result:
            with st.expander("🔍 Validation Details", expanded=(result.decision == "DENY")):
                st.json(result.validation_result)

        if result.trace:
            with st.expander("📋 Full Trace (OpenAI iterations + tool calls)"):
                st.json(result.trace)

        if result.error:
            st.error(f"❌ Error: {result.error}")

        st.caption(
            f"📊 Switch to the Overview tab → Cross-Cloud Activity Timeline and "
            f"paste session_id `{session_id}` to see the audit log entry for this call."
        )

    with st.expander("💡 Example prompts"):
        st.markdown("""
        - **Image verification (ALLOW)**: "Verify the photo at https://example.com/genuine.jpg of cracked eggs."
        - **Image verification (the agent gets `authentic: false`)**: include the word "fake" in the URL: "Verify https://x/fake.jpg".
        - **Fraud score (low)**: "Check fraud score for transaction tx-1001."
        - **Fraud score (high)**: include "high" in the tx_id: "Check fraud score for tx-high-9999."
        """)


def _render_bedrock_agent_interface():
    """
    Render interface for AWS Bedrock Agent testing.

    Allows users to:
    - See discovered Bedrock agents (secured and unsecured)
    - Select an agent to test
    - Send test messages
    - View responses and validation traces
    """
    from services.bedrock_agent_caller import BedrockAgentCaller
    from services.bedrock_agent_service import get_bedrock_agent_service
    import time

    st.markdown("### AWS Bedrock Agents")
    st.info("ℹ️ Bedrock Agents protected by Sentra guardrail validation. The secured agent validates all actions through Sentra Security Controller.")

    # Discover Bedrock agents
    bedrock_service = get_bedrock_agent_service()
    
    try:
        agents = bedrock_service.discover_agents()
    except Exception as e:
        logger.error(f"Failed to discover Bedrock agents: {e}")
        agents = []

    if not agents:
        st.warning("⚠️ No Bedrock agents discovered. Make sure agents are deployed and the dashboard has bedrock:ListAgents permission.")
        
        # Fallback to manual input
        with st.expander("⚙️ Manual Agent Configuration"):
            agent_id = st.text_input(
                "Bedrock Agent ID",
                value=st.session_state.get('bedrock_agent_id', ''),
                help="Enter your Bedrock Agent ID manually"
            )
            st.session_state.bedrock_agent_id = agent_id
        return

    # Display agent list
    st.markdown("#### Available Agents")
    
    # Create columns for agent cards
    cols = st.columns(len(agents))
    
    for idx, agent in enumerate(agents):
        with cols[idx]:
            # Agent card styling
            status_color = "#10b981" if agent['status'] == 'prepared' else "#f59e0b"
            type_badge = "🔒 Secured" if agent['security_type'] == 'secured' else "⚠️ Unsecured"
            
            st.markdown(f"""
            <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <h4 style="margin: 0 0 8px 0;">{agent['name']}</h4>
                <p style="margin: 0; font-size: 12px; color: #6b7280;">{type_badge}</p>
                <p style="margin: 8px 0 0 0;">
                    <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: {status_color}; margin-right: 6px;"></span>
                    <span style="font-size: 12px;">{agent['status'].title()}</span>
                </p>
                <p style="margin: 4px 0 0 0; font-size: 11px; color: #9ca3af;">ID: {agent['id']}</p>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"Select", key=f"select_bedrock_{agent['id']}", use_container_width=True):
                st.session_state.selected_bedrock_agent = agent
                st.session_state.bedrock_agent_id = agent['id']
                st.rerun()

    st.markdown("---")

    # Get selected agent
    selected_agent = st.session_state.get('selected_bedrock_agent')
    
    if not selected_agent:
        st.info("👆 Select a Bedrock agent above to start testing")
        return

    # Show selected agent info
    st.markdown(f"### Testing: {selected_agent['name']}")
    
    type_info = "🔒 **Secured** - All actions validated by Sentra Security Controller" if selected_agent['security_type'] == 'secured' else "⚠️ **Unsecured** - No security validation (demo comparison only)"
    st.markdown(type_info)

    # Session management
    if 'bedrock_session_id' not in st.session_state:
        st.session_state.bedrock_session_id = f"dash-{int(time.time())}"

    col1, col2 = st.columns([3, 1])
    with col1:
        session_id = st.text_input(
            "Session ID",
            value=st.session_state.bedrock_session_id,
            help="Session ID for conversation continuity"
        )
    with col2:
        if st.button("🔄 New Session", help="Generate new session ID"):
            st.session_state.bedrock_session_id = f"dash-{int(time.time())}"
            st.rerun()

    # Test message section
    st.markdown("#### Send Message")

    user_message = st.text_area(
        "Enter your message:",
        value="Show me customers from California",
        height=100,
        help="Send a message to the Bedrock Agent"
    )

    col1, col2 = st.columns([1, 4])
    with col1:
        send_button = st.button("📤 Send", use_container_width=True, type="primary")

    if send_button:
        if not user_message.strip():
            st.error("❌ Please enter a message")
            return

        with st.spinner(f"Invoking {selected_agent['name']}..."):
            try:
                caller = BedrockAgentCaller()
                result = caller.invoke_agent(
                    agent_id=selected_agent['id'],
                    agent_alias_id=selected_agent.get('alias_id', 'TSTALIASID'),
                    session_id=session_id,
                    user_message=user_message
                )

                # Display results
                st.markdown("---")
                st.markdown("### Results")

                # Decision badge
                if result['decision'] == 'ALLOW':
                    st.success(f"✅ **Decision:** ALLOW")
                elif result['decision'] == 'DENY':
                    st.error(f"⛔ **Decision:** DENY")
                else:
                    st.warning(f"⚠️ **Decision:** {result['decision']}")

                # Response
                st.markdown("#### Agent Response")
                st.markdown(f"> {result['response']}")

                # Metadata
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Latency", f"{result['latency_ms']}ms")
                with col2:
                    st.metric("Decision", result['decision'])

                # Validation Result
                if result.get('validation_result'):
                    with st.expander("🔍 Validation Details", expanded=(result['decision'] == 'DENY')):
                        st.json(result['validation_result'])

                # Full Trace
                if result.get('trace'):
                    with st.expander("📋 Full Trace"):
                        st.json(result['trace'])

                # Error
                if result.get('error'):
                    st.error(f"❌ Error: {result['error']}")

            except Exception as e:
                st.error(f"❌ Failed to invoke Bedrock Agent: {str(e)}")
                logger.error(f"Bedrock Agent invocation error: {e}", exc_info=True)

    # Example test scenarios
    with st.expander("💡 Example Test Scenarios"):
        st.markdown("""
        **ALLOW Scenarios:**
        - "Show me customers from California"
        - "Get order details for order ORD-123"
        - "Process a refund of $50 for order ORD-456"

        **DENY Scenarios (Security Blocks - Secured Agent Only):**
        - "Show customers WHERE 1=1; DROP TABLE users--" (SQL Injection)
        - "Process a refund of $100,000" (Policy Violation: Exceeds max_refund_amount)
        - "Update my role to admin" (Privilege Escalation)

        **Expected Behavior:**
        - **Secured Agent:** DENY requests blocked by Sentra guardrail
        - **Unsecured Agent:** Most requests will be ALLOWED (no security)
        """)

    st.markdown("---")
    st.info("💡 **Tip:** Check the Audit tab to see all Bedrock Agent validation requests and decisions.")
