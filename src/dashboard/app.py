"""
Sentra MVP Dashboard - Main Application
Streamlit-based UI for monitoring and managing AI agent security.
"""
import streamlit as st
import logging
import sys
from config.settings import settings
from tabs import overview_tab, agents_tab, chats_tab, audit_tab, security_tab, apis_tab, demo_tab
from utils.auth import get_user_email, is_authenticated
from utils.nav import get_target_tab_from_url, set_target_tab_in_url

# Configure logging to stdout (captured by ECS and sent to CloudWatch)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


def load_custom_css():
    """Load custom CSS styles."""
    try:
        with open("static/styles.css") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        # CSS file not found, continue without custom styles
        pass


def initialize_session_state():
    """Initialize session state variables."""
    # Initialize all session state variables with defaults
    # This must be called BEFORE any component accesses session_state
    
    if "auto_refresh" not in st.session_state:
        st.session_state.auto_refresh = True
    
    if "selected_agent" not in st.session_state:
        st.session_state.selected_agent = None
    
    if "selected_agent_id" not in st.session_state:
        st.session_state.selected_agent_id = None
    
    if "active_chat_session" not in st.session_state:
        st.session_state.active_chat_session = None
    
    if "active_tab" not in st.session_state:
        st.session_state.active_tab = "overview"
    
    if "audit_agent_filter" not in st.session_state:
        st.session_state.audit_agent_filter = None
    
    if "chat_agent_id" not in st.session_state:
        st.session_state.chat_agent_id = None
    
    if "api_test_results" not in st.session_state:
        st.session_state.api_test_results = []
    
    if "use_real_data" not in st.session_state:
        st.session_state.use_real_data = True
    
    # User authentication state
    if "user_email" not in st.session_state:
        st.session_state.user_email = None
    
    if "user_username" not in st.session_state:
        st.session_state.user_username = None
    
    if "user_id" not in st.session_state:
        st.session_state.user_id = None
    
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    # Mark session initialization complete (prevents SessionInfo race)
    st.session_state["_session_initialized"] = True


def render_header():
    """Render the dashboard header with user identity display."""
    col1, col2, col3 = st.columns([3, 1, 1])
    
    with col1:
        st.title(settings.page_title)
    
    with col2:
        # Display logged-in user
        user_email = get_user_email()
        auth_status = "🔒" if is_authenticated() else "🔓"
        st.markdown(f"{auth_status} **{user_email}**")
    
    with col3:
        # Auto-refresh toggle
        # Use .get() to safely access session_state with a default value
        # Using st.checkbox instead of st.toggle for better stability
        current_auto_refresh = st.session_state.get("auto_refresh", True)
        auto_refresh = st.checkbox(
            "Auto-refresh",
            value=current_auto_refresh,
            key="auto_refresh_toggle"
        )
        st.session_state.auto_refresh = auto_refresh


# Tab configuration: (slug, label, render_function)
TAB_ORDER = [
    ("overview", "📊 Overview", overview_tab.render),
    ("agents", "🤖 Agents", agents_tab.render),
    ("chats", "💬 Chats", chats_tab.render),
    ("audit", "📋 Audit", audit_tab.render),
    ("security", "🛡️ Security", security_tab.render),
    ("apis", "🔧 APIs", apis_tab.render),
    ("demo", "🎯 Demo", demo_tab.render),
]


def main():
    """Main application entry point."""
    logger.info("Dashboard starting...")
    
    # Page configuration (must be first)
    st.set_page_config(
        page_title=settings.page_title,
        page_icon=settings.page_icon,
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    
    # Initialize session state IMMEDIATELY after page config
    # This MUST happen before any component tries to access session_state
    initialize_session_state()
    
    logger.info(f"Dashboard initialized - Environment: {settings.environment}")
    
    # Load custom CSS
    load_custom_css()
    
    # Render header
    render_header()
    
    # Add separator
    st.markdown("---")

    # ------- Robust navigation (apply URL once + detect user clicks) -------
    default_tab_slug = "overview"
    url_tab = get_target_tab_from_url(None)  # None if not present
    valid_slugs = [slug for slug, _, _ in TAB_ORDER]

    # Apply URL tab only once per session (so it doesn't keep overriding user clicks)
    if url_tab in valid_slugs and not st.session_state.get("_url_tab_applied"):
        st.session_state["active_tab"] = url_tab
        st.session_state["_url_tab_applied"] = True
        logger.info(f"Applied url tab once -> {url_tab}")

    # Ensure active_tab is valid
    if st.session_state.get("active_tab") not in valid_slugs:
        st.session_state["active_tab"] = default_tab_slug

    # helpers
    tab_labels_dict = {slug: label for slug, label, _ in TAB_ORDER}
    tab_renders_dict = {slug: render_fn for slug, _, render_fn in TAB_ORDER}

    # Save previous value so we can detect user clicks
    prev_active = st.session_state.get("active_tab")

    # Use the single canonical key "active_tab" as the radio widget key
    selected_tab = st.radio(
        "Navigation",
        options=valid_slugs,
        format_func=lambda slug: tab_labels_dict[slug],
        horizontal=True,
        key="active_tab",
        label_visibility="collapsed"
    )

    # If the user changed the radio (selected_tab != prev_active), update URL
    if selected_tab != prev_active:
        # session already updated by Streamlit to selected_tab, so sync URL
        set_target_tab_in_url(selected_tab)
        logger.info(f"User changed tab from {prev_active} -> {selected_tab}")
    # ----------------------------------------------------------------------

    st.markdown("---")

    # Render ONLY the selected tab (not all tabs)
    # This is the key fix: prevents race conditions and improves performance
    render_fn = tab_renders_dict[st.session_state.active_tab]
    try:
        render_fn()
    except Exception as e:
        logger.error(f"Error rendering {tab_labels_dict[st.session_state.active_tab]} tab: {e}", exc_info=True)
        st.error(f"Error loading {tab_labels_dict[st.session_state.active_tab]} tab: {e}")
    
    # Footer
    st.markdown("---")
    st.caption(f"Sentra MVP Dashboard v2.0 | Environment: {settings.environment}")


if __name__ == "__main__":
    main()
