"""
Authentication utilities for extracting user identity from Cognito headers.

When running behind ALB with Cognito authentication, ALB adds OIDC headers
containing user information. This module extracts that information for
display in the dashboard and audit logging.

Reference: LLD 08 Section 5.1 (Cognito Configuration)
"""

import streamlit as st
import base64
import json
import logging
import os
from typing import Optional, Dict

logger = logging.getLogger(__name__)


def get_cognito_user_info() -> Dict[str, str]:
    """
    Extract user information from Cognito OIDC headers added by ALB.

    ALB adds x-amzn-oidc-data header containing JWT with user claims.
    
    Returns:
        Dictionary with user info
    """
    try:
        # Check if user info is already in session state (cached)
        if 'user_email' in st.session_state and st.session_state.user_email:
            # Only return cached if it's not the default local-dev
            if st.session_state.user_email != 'local-dev@sentra.local':
                return {
                    'email': st.session_state.user_email,
                    'username': st.session_state.get('user_username', 'Unknown'),
                    'user_id': st.session_state.get('user_id', 'unknown'),
                    'authenticated': st.session_state.get('authenticated', False)
                }

        # Try multiple methods to extract user info
        user_info = _extract_from_headers()
        if user_info and user_info.get('authenticated'):
            _cache_user_info(user_info)
            return user_info

        # Check environment variable for testing/override
        env_user = os.environ.get('DASHBOARD_USER_EMAIL')
        if env_user:
            user_info = {
                'email': env_user,
                'username': env_user.split('@')[0],
                'user_id': 'env-override',
                'authenticated': True
            }
            _cache_user_info(user_info)
            return user_info

        # Check if we're behind ALB (Public ALB DNS in URL)
        # If so, assume authenticated but can't extract email
        # This is a workaround for Streamlit's header access limitations
        if _is_behind_alb():
            user_info = {
                'email': 'Authenticated User',
                'username': 'authenticated',
                'user_id': 'cognito-user',
                'authenticated': True
            }
            _cache_user_info(user_info)
            return user_info

        # Default for local development (no Cognito)
        return {
            'email': 'local-dev@sentra.local',
            'username': 'local-dev',
            'user_id': 'local',
            'authenticated': False
        }

    except Exception as e:
        logger.error(f"Error extracting Cognito user info: {e}")
        return {
            'email': 'Unknown User',
            'username': 'unknown',
            'user_id': 'unknown',
            'authenticated': False
        }


def _is_behind_alb() -> bool:
    """Check if we're running behind ALB by checking environment or URL."""
    # Check if SECURITY_CONTROLLER_URL points to Private ALB (indicates production)
    security_controller_url = os.environ.get('SECURITY_CONTROLLER_URL', '')
    if 'elb.amazonaws.com' in security_controller_url:
        return True
    
    # Check if we're not on localhost
    try:
        import socket
        hostname = socket.gethostname()
        if 'fargate' in hostname.lower() or 'ecs' in hostname.lower():
            return True
    except:
        pass
    
    return False


def _cache_user_info(user_info: Dict[str, str]):
    """Cache user info in session state."""
    st.session_state.user_email = user_info['email']
    st.session_state.user_username = user_info['username']
    st.session_state.user_id = user_info['user_id']
    st.session_state.authenticated = user_info['authenticated']


def _extract_from_headers() -> Optional[Dict[str, str]]:
    """
    Attempt to extract user info from ALB OIDC headers.
    
    Tries multiple methods since Streamlit header access varies by version.
    """
    # Method 1: Try st.context.headers (Streamlit 1.31+)
    try:
        if hasattr(st, 'context') and hasattr(st.context, 'headers'):
            headers = st.context.headers
            result = _parse_oidc_header(headers.get('x-amzn-oidc-data'))
            if result:
                return result
    except Exception as e:
        logger.debug(f"st.context.headers not available: {e}")

    # Method 2: Try accessing via Streamlit's internal request
    try:
        from streamlit.web.server.websocket_headers import _get_websocket_headers
        headers = _get_websocket_headers()
        if headers:
            result = _parse_oidc_header(headers.get('X-Amzn-Oidc-Data'))
            if result:
                return result
    except Exception as e:
        logger.debug(f"Websocket headers not available: {e}")

    # Method 3: Try st.runtime.scriptrunner
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        if ctx and hasattr(ctx, 'session_state'):
            # Check if headers were passed via session
            pass
    except Exception as e:
        logger.debug(f"Script run context not available: {e}")

    return None


def _parse_oidc_header(oidc_data: Optional[str]) -> Optional[Dict[str, str]]:
    """Parse the x-amzn-oidc-data JWT header."""
    if not oidc_data:
        return None
    
    try:
        # JWT format: header.payload.signature
        parts = oidc_data.split('.')
        if len(parts) >= 2:
            payload = parts[1]
            # Add padding if needed
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            
            decoded = base64.urlsafe_b64decode(payload)
            claims = json.loads(decoded)
            
            email = claims.get('email', 'Unknown')
            return {
                'email': email,
                'username': claims.get('cognito:username', email),
                'user_id': claims.get('sub', 'unknown'),
                'authenticated': True
            }
    except Exception as e:
        logger.debug(f"Failed to parse OIDC header: {e}")
    
    return None


def get_user_email() -> str:
    """Get logged-in user's email address."""
    user_info = get_cognito_user_info()
    return user_info.get('email', 'Unknown User')


def get_username() -> str:
    """Get logged-in user's username."""
    user_info = get_cognito_user_info()
    return user_info.get('username', 'Unknown')


def get_user_id() -> str:
    """Get logged-in user's unique ID (Cognito sub)."""
    user_info = get_cognito_user_info()
    return user_info.get('user_id', 'unknown')


def is_authenticated() -> bool:
    """Check if user is authenticated via Cognito."""
    user_info = get_cognito_user_info()
    return user_info.get('authenticated', False)


def clear_user_session():
    """Clear cached user information from session state."""
    keys_to_clear = ['user_email', 'user_username', 'user_id', 'authenticated']
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
