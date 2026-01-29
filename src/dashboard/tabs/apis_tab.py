"""
APIs Tab - Test all Security Controller APIs with live results.
"""
import streamlit as st
import json
from datetime import datetime
from services.security_controller_client import security_controller_client
import sys
import logging

logger = logging.getLogger(__name__)

def debug_log(msg):
    """Log to stdout with flush (avoid stderr)."""
    print(f"APIS_TAB: {msg}", file=sys.stdout, flush=True)
    logger.debug(f"APIS_TAB: {msg}")


def render():
    """Render the APIs testing tab."""
    debug_log("=" * 50)
    debug_log("RENDER FUNCTION CALLED")
    debug_log("=" * 50)
    
    # Initialize session state for this tab (defensive programming)
    if 'api_test_results' not in st.session_state:
        st.session_state.api_test_results = []
        debug_log("Initialized api_test_results in session state")
    
    # Debug info (only in logs, not UI to avoid overwhelming Streamlit)
    debug_log("UI: APIs tab rendering...")

    st.title("🔧 API Testing Interface")
    st.markdown("Test all Security Controller APIs and view responses in real-time.")
    st.markdown("---")
    
    debug_log("Rendering Core APIs section...")

    # Section 1: Core APIs
    st.header("1. Core APIs")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🏥 GET /v1/health", use_container_width=True, key="apis_tab_btn_health"):
            test_api("Health Check", lambda: security_controller_client.get_health())

    with col2:
        if st.button("📊 GET /v1/metrics", use_container_width=True, key="apis_tab_btn_metrics"):
            test_api("Metrics", lambda: security_controller_client.get_metrics())

    st.markdown("---")
    
    debug_log("Rendering Agent Management APIs section...")

    # Section 2: Agent Management APIs
    st.header("2. Agent Management APIs")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🤖 GET /v1/agents", use_container_width=True, key="apis_tab_btn_list_agents"):
            test_api("List Agents", lambda: security_controller_client.get_agents())

    with col2:
        agent_id = st.text_input("Agent ID", value="customer-query-agent", key="apis_tab_agent_id_detail")
        if st.button("📝 GET /v1/agents/{id}", use_container_width=True, key="apis_tab_btn_agent_detail"):
            test_api(f"Get Agent Details: {agent_id}",
                    lambda: security_controller_client.get_agent_details(agent_id))

    with col3:
        agent_id_tools = st.text_input("Agent ID", value="customer-query-agent", key="apis_tab_agent_id_tools")
        if st.button("🔧 GET /v1/agents/{id}/tools", use_container_width=True, key="apis_tab_btn_agent_tools"):
            test_api(f"Get Agent Tools: {agent_id_tools}",
                    lambda: security_controller_client.get_agent_tools(agent_id_tools))

    st.markdown("---")
    
    debug_log("Rendering Audit & Logs APIs section...")

    # Section 3: Audit & Logs APIs
    st.header("3. Audit & Logs APIs")

    col1, col2, col3 = st.columns(3)

    with col1:
        limit = st.number_input("Limit", min_value=1, max_value=100, value=5, key="apis_tab_logs_limit")
        if st.button("📋 GET /v1/logs", use_container_width=True, key="apis_tab_btn_logs"):
            test_api(f"Get Logs (limit={limit})",
                    lambda: security_controller_client.get_logs(limit=limit))

    with col2:
        session_limit = st.number_input("Limit", min_value=1, max_value=50, value=5, key="apis_tab_sessions_limit")
        if st.button("💬 GET /v1/sessions", use_container_width=True, key="apis_tab_btn_sessions"):
            test_api(f"Get Sessions (limit={session_limit})",
                    lambda: security_controller_client.get_sessions(limit=session_limit))

    with col3:
        if st.button("🔍 GET /v1/logs (filtered)", use_container_width=True, key="apis_tab_btn_logs_filtered"):
            test_api("Get Logs (ALLOW only)",
                    lambda: security_controller_client.get_logs(limit=10, decision="ALLOW"))

    st.markdown("---")
    
    debug_log("Rendering Policy APIs section...")

    # Section 4: Policy APIs
    st.header("4. Policy APIs")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("📜 GET /v1/policies", use_container_width=True, key="apis_tab_btn_policies_all"):
            test_api("List All Policies",
                    lambda: security_controller_client.get_policies())

    with col2:
        agent_id_policies = st.text_input("Agent ID", value="customer-query-agent", key="apis_tab_agent_id_policies")
        if st.button("📜 GET /v1/policies?agent_id={id}", use_container_width=True, key="apis_tab_btn_policies_agent"):
            test_api(f"Get Policies for {agent_id_policies}",
                    lambda: security_controller_client.get_policies(agent_id=agent_id_policies))

    st.markdown("---")
    
    debug_log("Rendering Security APIs section...")

    # Section 5: Security APIs
    st.header("5. Security APIs")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🛡️ GET /v1/sigma-rules", use_container_width=True, key="apis_tab_btn_sigma_rules"):
            test_api("List Sigma Rules",
                    lambda: security_controller_client.get_sigma_rules())

    with col2:
        if st.button("🏥 GET /v1/health?agent_id=payment-agent", use_container_width=True, key="apis_tab_btn_health_payment"):
            test_api("Agent Health: payment-agent",
                    lambda: security_controller_client.get_health(agent_id="payment-agent"))

    st.markdown("---")
    
    debug_log("Rendering Results section...")

    # Results area at bottom
    if 'api_test_results' in st.session_state and st.session_state.api_test_results:
        debug_log(f"Found {len(st.session_state.api_test_results)} test results")
        st.header("📊 Latest Test Result")
        result = st.session_state.api_test_results[-1]

        # Show test info
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.markdown(f"**API:** {result['name']}")
        with col2:
            st.markdown(f"**Time:** {result['timestamp']}")
        with col3:
            if result['success']:
                st.success("✅ SUCCESS")
            else:
                st.error("❌ FAILED")

        # Show response/error
        if result['success']:
            st.subheader("Response:")
            st.json(result['response'])
        else:
            st.subheader("Error:")
            st.error(result['error'])
            if result.get('traceback'):
                with st.expander("📋 Show Traceback"):
                    st.code(result['traceback'])
    
    debug_log("APIs tab render complete!")


def test_api(name: str, api_call):
    """
    Test an API call and display results.

    Args:
        name: Display name for the API test
        api_call: Lambda function that calls the API
    """
    debug_log(f"Testing API: {name}")

    # Session state already initialized in render()
    try:
        with st.spinner(f"Calling {name}..."):
            debug_log(f"Calling {name}...")
            response = api_call()
            debug_log(f"Success! Response: {response}")

            # Store result
            result = {
                'name': name,
                'timestamp': datetime.now().strftime("%H:%M:%S"),
                'success': True,
                'response': response,
                'error': None,
                'traceback': None
            }
            st.session_state.api_test_results.append(result)

            # Show success message
            st.success(f"✅ {name} - Success!")
            # REMOVED st.rerun() - results will display on next render

    except Exception as e:
        debug_log(f"Error in {name}: {str(e)}")
        import traceback
        tb = traceback.format_exc()
        debug_log(f"Traceback:\n{tb}")

        # Store error result
        result = {
            'name': name,
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'success': False,
            'response': None,
            'error': str(e),
            'traceback': tb
        }
        st.session_state.api_test_results.append(result)

        # Show error message
        st.error(f"❌ {name} - Failed: {str(e)}")
        # REMOVED st.rerun() - results will display on next render
