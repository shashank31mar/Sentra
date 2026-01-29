"""
Navigation utilities for programmatic tab switching.
Uses URL query params to enable deep-linking and tab switching.
"""
import streamlit as st


def get_target_tab_from_url(default: str = None) -> str:
    """
    Read ?tab=... from URL query params (case-insensitive).

    Args:
        default: Default tab slug if not specified in URL (can be None)

    Returns:
        Tab slug (e.g., "agents", "overview", "chats") or None if not in URL
    """
    params = st.query_params
    tab = params.get("tab", default)
    return tab.lower() if tab else None


def set_target_tab_in_url(target_tab: str):
    """
    Set ?tab=target_tab in URL (no rerun).
    
    Args:
        target_tab: Tab slug to navigate to
        
    Note:
        Do NOT call st.rerun() after this. Return from render function
        to allow clean re-render with new tab order.
    """
    st.query_params["tab"] = target_tab
    # Do NOT call st.rerun() here. Return to allow a clean re-render.
