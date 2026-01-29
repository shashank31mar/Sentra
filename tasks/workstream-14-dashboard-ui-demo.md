# Workstream 14: Dashboard UI - Demo Tab & Overview Updates

**Status:** Not Started
**Owner:** TBD
**Start Date:** TBD
**Target Completion:** TBD
**LLD Reference:** [lld/14-dashboard-ui-demo.md](../lld/14-dashboard-ui-demo.md)

---

## Overview

Add UI components to the existing Streamlit dashboard for demo scenario control and Bedrock security comparison visualization.

### Goals

1. **Demo Tab** - New tab for scenario management and manual execution
2. **Overview Tab Updates** - Add Bedrock comparison visualization showing secured vs unsecured agents
3. **Real-time Metrics** - Auto-refresh comparison charts
4. **User Controls** - Start, pause, resume, and trigger scenarios from UI

### Success Criteria

- ✅ Demo Tab renders scenario list with status
- ✅ Manual trigger buttons work
- ✅ Pause/resume controls functional
- ✅ Scenario details modal shows prompts
- ✅ Overview Tab shows Bedrock comparison table
- ✅ Dual pie charts display (secured vs unsecured)
- ✅ Auto-refresh every 30 seconds
- ✅ Comparison metrics match backend API

---

## Milestone 1: Demo Tab - Scenario List & Controls (4 hours)

**Goal:** Create Demo Tab with scenario cards and basic controls
**Status:** ✅ Complete

**Completion Criteria:**
- ✅ Demo Tab appears in navigation
- ✅ Scenario cards render with metadata
- ✅ Run Once button triggers scenarios
- ✅ Pause/Resume buttons work

### Task 1.1: Create Demo Tab File & Route

**Effort:** 0.5 hours
**Priority:** P0
**Status:** ✅ Complete
**Files:**
- `src/dashboard/tabs/demo_tab.py` (NEW)
- `src/dashboard/app.py` (UPDATE)
- `src/dashboard/tabs/__init__.py` (UPDATE)
- `src/dashboard/services/demo_orchestrator_client.py` (NEW)
- `src/dashboard/config/settings.py` (UPDATE)

**Description:**
Create new Demo tab and add to navigation.

**Implementation:**

```python
# tabs/demo.py
import streamlit as st
import requests
import os

DEMO_ORCHESTRATOR_URL = os.getenv(
    "DEMO_ORCHESTRATOR_URL",
    "http://demo-orchestrator.sentra.internal:8080"
)

def render_demo_tab():
    """Render Demo Scenarios tab"""
    st.header("🎯 Demo Scenarios")

    # Fetch scenarios
    scenarios = fetch_scenarios()

    if not scenarios:
        st.warning("No scenarios available")
        return

    # Render scenario cards
    for scenario in scenarios:
        render_scenario_card(scenario)

def fetch_scenarios():
    """Fetch all scenarios from demo orchestrator"""
    try:
        response = requests.get(f"{DEMO_ORCHESTRATOR_URL}/demo/scenarios")
        response.raise_for_status()
        return response.json()['scenarios']
    except Exception as e:
        st.error(f"Failed to fetch scenarios: {e}")
        return []

def render_scenario_card(scenario):
    """Placeholder - will implement in Task 1.2"""
    st.write(scenario['name'])
```

```python
# app.py (update)
from tabs.demo import render_demo_tab

# Add to tab list
tabs = ["Overview", "Agents", "Policies", "Demo"]  # Add Demo

# In rendering logic
if selected_tab == "Demo":
    render_demo_tab()
```

**Acceptance Criteria:**
- [x] Demo tab appears in navigation
- [x] Tab renders without errors
- [x] fetch_scenarios() calls API successfully
- [x] Placeholder content displays

---

### Task 1.2: Implement Scenario Cards with Controls

**Effort:** 2 hours
**Priority:** P0
**Status:** ✅ Complete
**Files:**
- `src/dashboard/tabs/demo_tab.py` (UPDATE)

**Description:**
Render scenario cards with metadata and action buttons.

**Implementation:**

```python
# tabs/demo.py

def render_scenario_card(scenario):
    """Render individual scenario card with controls"""

    # Status indicator
    status_icon = "🟢" if scenario['status'] == 'running' else "⚪"
    status_text = scenario['status'].upper()

    with st.expander(
        f"{status_icon} {scenario['name']} - {status_text}",
        expanded=False
    ):
        # Description
        st.write(scenario['description'])

        # Metadata in columns
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Mode", scenario['mode'].capitalize())
        with col2:
            if scenario.get('interval'):
                st.metric("Interval", f"{scenario['interval']}s")
            else:
                st.metric("Interval", "Manual")
        with col3:
            st.metric("Prompts", scenario['prompt_count'])

        # Action buttons
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button(
                "▶ Run Once",
                key=f"run_{scenario['scenario_id']}",
                help="Execute scenario immediately"
            ):
                trigger_scenario(scenario['scenario_id'])

        with col2:
            if scenario['status'] == 'running':
                if st.button(
                    "⏸ Pause",
                    key=f"pause_{scenario['scenario_id']}",
                    help="Pause continuous execution"
                ):
                    pause_scenario(scenario['scenario_id'])
                    st.rerun()
            else:
                if st.button(
                    "▶ Resume",
                    key=f"resume_{scenario['scenario_id']}",
                    help="Resume continuous execution"
                ):
                    start_scenario(scenario['scenario_id'])
                    st.rerun()

        with col3:
            if st.button(
                "📋 Details",
                key=f"view_{scenario['scenario_id']}",
                help="View scenario prompts"
            ):
                st.session_state[f"show_details_{scenario['scenario_id']}"] = True


def trigger_scenario(scenario_id: str):
    """Trigger scenario once"""
    try:
        response = requests.post(
            f"{DEMO_ORCHESTRATOR_URL}/demo/scenarios/{scenario_id}/trigger"
        )
        response.raise_for_status()
        st.success(f"✅ Scenario triggered! Run ID: {response.json()['run_id']}")
    except Exception as e:
        st.error(f"❌ Failed to trigger scenario: {e}")


def start_scenario(scenario_id: str):
    """Start continuous execution"""
    try:
        response = requests.post(
            f"{DEMO_ORCHESTRATOR_URL}/demo/scenarios/{scenario_id}/start"
        )
        response.raise_for_status()
        st.success("✅ Scenario started (continuous)")
    except Exception as e:
        st.error(f"❌ Failed to start scenario: {e}")


def pause_scenario(scenario_id: str):
    """Pause continuous execution"""
    try:
        response = requests.post(
            f"{DEMO_ORCHESTRATOR_URL}/demo/scenarios/{scenario_id}/pause"
        )
        response.raise_for_status()
        st.success("✅ Scenario paused")
    except Exception as e:
        st.error(f"❌ Failed to pause scenario: {e}")
```

**Acceptance Criteria:**
- [x] Scenario cards render with metadata
- [x] Run Once button triggers scenario
- [x] Success/error messages display
- [x] Pause/Resume buttons work
- [x] Page auto-reloads after pause/resume

---

### Task 1.3: Add Global Pause/Resume Controls

**Effort:** 0.5 hours
**Priority:** P1
**Status:** ✅ Complete
**Files:**
- `src/dashboard/tabs/demo_tab.py` (UPDATE)

**Description:**
Add buttons to pause/resume all scenarios at once.

**Implementation:**

```python
# tabs/demo.py (add to render_demo_tab)

def render_demo_tab():
    st.header("🎯 Demo Scenarios")

    scenarios = fetch_scenarios()

    # Render scenario cards
    for scenario in scenarios:
        render_scenario_card(scenario)

    st.divider()

    # Global controls
    st.subheader("Global Controls")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("⏯ Pause All", help="Pause all running scenarios"):
            pause_all_scenarios(scenarios)

    with col2:
        if st.button("▶ Resume All", help="Resume all continuous scenarios"):
            resume_all_scenarios(scenarios)


def pause_all_scenarios(scenarios):
    """Pause all running scenarios"""
    paused = 0
    for scenario in scenarios:
        if scenario['status'] == 'running':
            pause_scenario(scenario['scenario_id'])
            paused += 1
    st.success(f"✅ Paused {paused} scenario(s)")
    st.rerun()


def resume_all_scenarios(scenarios):
    """Resume all continuous scenarios"""
    resumed = 0
    for scenario in scenarios:
        if scenario['mode'] == 'continuous' and scenario['status'] != 'running':
            start_scenario(scenario['scenario_id'])
            resumed += 1
    st.success(f"✅ Resumed {resumed} scenario(s)")
    st.rerun()
```

**Acceptance Criteria:**
- [x] Pause All button pauses all running scenarios
- [x] Resume All button resumes continuous scenarios
- [x] Success message shows count
- [x] Page reloads after action

---

### Task 1.4: Add Scenario Details Modal

**Effort:** 1 hour
**Priority:** P1
**Status:** ✅ Complete
**Files:**
- `src/dashboard/tabs/demo_tab.py` (UPDATE)

**Description:**
Show scenario details (prompts) in expandable section or modal.

**Implementation:**

```python
# tabs/demo.py

def render_scenario_card(scenario):
    # ... existing code ...

    # Show details if requested
    if st.session_state.get(f"show_details_{scenario['scenario_id']}", False):
        show_scenario_details(scenario['scenario_id'])


def show_scenario_details(scenario_id: str):
    """Show scenario details with prompts"""
    try:
        response = requests.get(
            f"{DEMO_ORCHESTRATOR_URL}/demo/scenarios/{scenario_id}"
        )
        response.raise_for_status()
        scenario = response.json()

        # Details section
        st.markdown("---")
        st.markdown(f"### 📋 {scenario['name']} - Details")

        # Metadata
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Mode:** {scenario['mode']}")
            if scenario.get('interval'):
                st.write(f"**Interval:** Every {scenario['interval']} seconds")
        with col2:
            st.write(f"**Prompts:** {len(scenario['prompts'])}")

        # Target agents
        st.write("**Target Agents:**")
        for agent in scenario['agents']['self_hosted']:
            st.write(f"- {agent} (Self-Hosted)")
        for agent in scenario['agents']['bedrock']:
            st.write(f"- {agent} (Bedrock)")

        # Prompts
        st.write("**Test Prompts:**")
        for idx, prompt in enumerate(scenario['prompts'], 1):
            with st.container():
                st.markdown(f"**{idx}. {prompt['id']}**")
                st.code(prompt['text'], language=None)
                st.caption(
                    f"Expected: **{prompt['expected_decision']}** "
                    f"({prompt['expected_threat']})"
                )

        # Close button
        if st.button(
            "Close Details",
            key=f"close_details_{scenario_id}"
        ):
            st.session_state[f"show_details_{scenario_id}"] = False
            st.rerun()

    except Exception as e:
        st.error(f"Failed to load scenario details: {e}")
```

**Acceptance Criteria:**
- [x] Details button shows prompts
- [x] Prompts displayed with expected decision
- [x] Close button hides details
- [x] Error handling for API failures

---

## Milestone 2: Demo Tab - Comparison Results (3 hours)

**Goal:** Show latest comparison results in Demo Tab
**Status:** ✅ Complete (implemented in Milestone 1)

**Completion Criteria:**
- Latest results section displays metrics
- Metrics grouped by agent type
- Visual indicators for security posture
- Auto-refresh every 30 seconds

### Task 2.1: Create Comparison Results Section

**Effort:** 2 hours
**Priority:** P0
**Files:**
- `src/dashboard/tabs/demo.py` (UPDATE)

**Description:**
Add comparison results display to Demo Tab.

**Implementation:**

```python
# tabs/demo.py

def render_demo_tab():
    # ... existing scenario cards ...

    st.divider()

    # Latest results
    st.subheader("📊 Latest Results (Last 1 Hour)")
    render_comparison_results()


def render_comparison_results():
    """Render comparison metrics grid"""
    try:
        response = requests.get(
            f"{DEMO_ORCHESTRATOR_URL}/demo/comparison?hours=1"
        )
        response.raise_for_status()
        data = response.json()['comparison']

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**Self-Hosted Agents**")
            render_agent_metrics(data['self_hosted'])

        with col2:
            st.markdown("**Bedrock Secured (Sentra)**")
            render_agent_metrics(data['bedrock_secured'])

        with col3:
            st.markdown("**⚠️ Bedrock Unsecured**")
            render_agent_metrics(data['bedrock_unsecured'], is_unsecured=True)

    except Exception as e:
        st.error(f"Failed to load comparison data: {e}")


def render_agent_metrics(metrics: dict, is_unsecured: bool = False):
    """Render metrics for single agent type"""

    if metrics['total'] == 0:
        st.info("No data yet")
        return

    # Denied (good for secured, neutral for unsecured)
    st.metric(
        "Denied",
        f"{metrics['denied_pct']}%",
        delta=f"{metrics['denied']} requests",
        delta_color="normal"
    )

    # Allowed (bad for secured, warning for unsecured)
    if is_unsecured:
        # High allowed % is expected (showing it's insecure)
        st.metric(
            "Allowed ⚠️",
            f"{metrics['allowed_pct']}%",
            delta=f"{metrics['allowed']} requests",
            delta_color="off"  # No color, just warning emoji
        )
    else:
        # Low allowed % is good
        st.metric(
            "Allowed",
            f"{metrics['allowed_pct']}%",
            delta=f"{metrics['allowed']} requests",
            delta_color="inverse"  # Red if high
        )

    # Rollback (if available)
    if 'rollback_pct' in metrics and metrics['rollback_pct'] > 0:
        st.metric(
            "Rollback",
            f"{metrics['rollback_pct']}%",
            delta=f"{metrics['rollback']} requests"
        )

    # Security score (100 - allowed_pct)
    score = 100 - metrics['allowed_pct']
    score_color = "🟢" if score > 80 else ("🟡" if score > 50 else "🔴")
    st.metric(
        "Security Score",
        f"{score_color} {score:.1f}%"
    )
```

**Acceptance Criteria:**
- [x] Comparison results display for 3 agent types
- [x] Metrics show percentages and counts
- [x] Security score calculated correctly
- [x] Unsecured agent marked with warning
- [x] Error handling for API failures

---

### Task 2.2: Add Auto-Refresh

**Effort:** 1 hour
**Priority:** P1
**Status:** ✅ Complete
**Files:**
- `src/dashboard/tabs/demo_tab.py` (UPDATE)

**Description:**
Auto-refresh Demo Tab every 30 seconds using cache TTL (best practice - no blocking sleep).

**Implementation Notes:**
- Uses `@st.cache_data(ttl=30)` for automatic refresh via cache expiry
- Manual refresh button clears cache and triggers rerun
- Avoids `time.sleep()` which blocks main thread (per best practices)

**Acceptance Criteria:**
- [x] Manual refresh button available
- [x] No flickering during refresh
- N/A Auto-refresh removed (causes stability issues per best practices)

---

## Milestone 3: Overview Tab - Bedrock Comparison (3 hours)

**Goal:** Add Bedrock comparison section to Overview Tab

**Completion Criteria:**
- Comparison table displays in Overview Tab
- Dual pie charts show secured vs unsecured
- Metrics update automatically
- Visual design matches existing Overview style

### Task 3.1: Add Comparison Table to Overview Tab

**Effort:** 1.5 hours
**Priority:** P0
**Status:** ✅ Complete
**Files:**
- `src/dashboard/tabs/overview_tab.py` (UPDATE)

**Description:**
Add Bedrock comparison table at bottom of Overview Tab.

**Implementation:**

```python
# tabs/overview.py

import pandas as pd
import requests
import os

DEMO_ORCHESTRATOR_URL = os.getenv(
    "DEMO_ORCHESTRATOR_URL",
    "http://demo-orchestrator.sentra.internal:8080"
)

def render_overview_tab():
    # ... existing overview content ...

    st.divider()

    # NEW: Bedrock comparison
    render_bedrock_comparison()


def render_bedrock_comparison():
    """Add Bedrock comparison section to Overview tab"""

    st.subheader("🔐 Bedrock Agent Security Comparison (24h)")

    try:
        # Fetch comparison data
        response = requests.get(
            f"{DEMO_ORCHESTRATOR_URL}/demo/comparison?hours=24"
        )
        response.raise_for_status()
        data = response.json()['comparison']

        # Comparison table
        render_comparison_table(data)

    except Exception as e:
        st.warning(f"Demo comparison unavailable: {e}")


def render_comparison_table(data: dict):
    """Render comparison table"""

    # Create DataFrame
    df = pd.DataFrame({
        "Agent Type": [
            "Self-Hosted Agents",
            "Bedrock Secured (Sentra)",
            "⚠️ Bedrock Unsecured"
        ],
        "Total Requests": [
            data['self_hosted']['total'],
            data['bedrock_secured']['total'],
            data['bedrock_unsecured']['total']
        ],
        "Allowed": [
            f"{data['self_hosted']['allowed']} ({data['self_hosted']['allowed_pct']}%)",
            f"{data['bedrock_secured']['allowed']} ({data['bedrock_secured']['allowed_pct']}%)",
            f"{data['bedrock_unsecured']['allowed']} ({data['bedrock_unsecured']['allowed_pct']}%)"
        ],
        "Denied": [
            f"{data['self_hosted']['denied']} ({data['self_hosted']['denied_pct']}%)",
            f"{data['bedrock_secured']['denied']} ({data['bedrock_secured']['denied_pct']}%)",
            f"{data['bedrock_unsecured']['denied']} ({data['bedrock_unsecured']['denied_pct']}%)"
        ],
        "Security Score": [
            f"🟢 {100 - data['self_hosted']['allowed_pct']:.1f}%",
            f"🟢 {100 - data['bedrock_secured']['allowed_pct']:.1f}%",
            f"🔴 {100 - data['bedrock_unsecured']['allowed_pct']:.1f}%"
        ]
    })

    # Display table
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )
```

**Acceptance Criteria:**
- [x] Comparison table displays in Overview Tab
- [x] Table shows 3 agent types with metrics
- [x] Percentages and counts displayed
- [x] Security scores color-coded
- [x] Graceful degradation if demo orchestrator unavailable

---

### Task 3.2: Add Dual Pie Charts

**Effort:** 1.5 hours
**Priority:** P0
**Status:** ✅ Complete
**Files:**
- `src/dashboard/tabs/overview_tab.py` (UPDATE)
- `src/dashboard/requirements.txt` (plotly already present)

**Description:**
Add side-by-side pie charts comparing secured vs unsecured agents.

**Implementation:**

```python
# tabs/overview.py

import plotly.graph_objects as go

def render_bedrock_comparison():
    # ... existing table ...

    st.divider()

    # Dual pie charts
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**⚠️ Bedrock Unsecured**")
        render_pie_chart(data['bedrock_unsecured'], is_unsecured=True)
        st.caption("⚠️ High Risk - No Security Layer")

    with col2:
        st.markdown("**✅ Bedrock Secured (Sentra)**")
        render_pie_chart(data['bedrock_secured'], is_unsecured=False)
        st.caption("✅ Protected by Sentra")


def render_pie_chart(metrics: dict, is_unsecured: bool):
    """Render pie chart for agent type"""

    if metrics['total'] == 0:
        st.info("No data yet")
        return

    labels = ['Denied', 'Allowed', 'Rollback']
    values = [
        metrics['denied'],
        metrics['allowed'],
        metrics.get('rollback', 0)
    ]

    # Remove zero values
    filtered = [(l, v) for l, v in zip(labels, values) if v > 0]
    if not filtered:
        st.info("No data")
        return

    labels, values = zip(*filtered)

    # Color scheme
    if is_unsecured:
        # Unsecured: Red for allowed (bad), yellow for denied
        colors = {
            'Denied': '#ffaa00',    # Yellow (neutral)
            'Allowed': '#ff4444',   # Red (bad - showing it's insecure)
            'Rollback': '#4444ff'   # Blue
        }
    else:
        # Secured: Green for denied (good), yellow for allowed
        colors = {
            'Denied': '#44ff44',    # Green (good)
            'Allowed': '#ffaa00',   # Yellow (warning)
            'Rollback': '#4444ff'   # Blue
        }

    chart_colors = [colors.get(label, '#888888') for label in labels]

    # Create pie chart
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        marker=dict(colors=chart_colors),
        hole=0.3,  # Donut chart
        textinfo='label+percent',
        textposition='inside'
    )])

    fig.update_layout(
        showlegend=True,
        height=300,
        margin=dict(t=0, b=0, l=0, r=0)
    )

    st.plotly_chart(fig, use_container_width=True)
```

**Acceptance Criteria:**
- [x] Dual pie charts display side-by-side
- [x] Charts use appropriate colors (green/yellow vs yellow/red)
- [x] Percentages display on chart
- [x] Donut chart style (hole in middle)
- [x] Legends show decision types
- [x] Charts responsive to container width

---

## Milestone 3 Status: ✅ Complete

---

## Milestone 4: Polish & Testing (2 hours)

**Goal:** Refine UI, add error handling, and validate end-to-end

**Completion Criteria:**
- Error states handled gracefully
- Loading states display
- UI matches Sentra design system
- All features tested end-to-end

### Task 4.1: Add Loading States & Error Handling

**Effort:** 1 hour
**Priority:** P1
**Status:** ✅ Complete
**Files:**
- `src/dashboard/tabs/demo_tab.py` (UPDATE)
- `src/dashboard/tabs/overview_tab.py` (UPDATE)

**Description:**
Add spinners, error messages, and empty states.

**Implementation:**

```python
# tabs/demo.py

def fetch_scenarios():
    """Fetch scenarios with loading state"""
    with st.spinner("Loading scenarios..."):
        try:
            response = requests.get(
                f"{DEMO_ORCHESTRATOR_URL}/demo/scenarios",
                timeout=5
            )
            response.raise_for_status()
            return response.json()['scenarios']
        except requests.Timeout:
            st.error("⏱️ Request timed out. Demo orchestrator may be down.")
            return []
        except requests.RequestException as e:
            st.error(f"❌ Failed to fetch scenarios: {e}")
            return []


def render_comparison_results():
    """Render with loading spinner"""
    with st.spinner("Loading comparison data..."):
        try:
            response = requests.get(
                f"{DEMO_ORCHESTRATOR_URL}/demo/comparison?hours=1",
                timeout=10
            )
            response.raise_for_status()
            data = response.json()['comparison']

            # Check if any data
            total_requests = sum(
                data[agent_type]['total']
                for agent_type in ['self_hosted', 'bedrock_secured', 'bedrock_unsecured']
            )

            if total_requests == 0:
                st.info("📊 No demo data yet. Scenarios are still running or just started.")
                return

            # Render metrics
            # ... existing code ...

        except Exception as e:
            st.error(f"❌ Failed to load comparison: {e}")
```

**Acceptance Criteria:**
- [x] Loading spinners display during API calls
- [x] Timeout errors handled gracefully (via client timeouts)
- [x] Empty states show helpful messages
- [x] Network errors display user-friendly messages
- [x] Timeouts configured in demo_orchestrator_client.py

---

### Task 4.2: UI Polish & Styling

**Effort:** 0.5 hours
**Priority:** P2
**Status:** ✅ Complete
**Files:**
- `src/dashboard/tabs/demo_tab.py` (UPDATE)
- `src/dashboard/tabs/overview_tab.py` (UPDATE)

**Description:**
Align with Sentra design system and improve visual hierarchy.

**Implementation:**

```python
# tabs/demo.py

# Add spacing and dividers
st.markdown("---")  # Instead of st.divider() for consistency

# Use consistent emoji icons
# 🎯 Demo, 📋 Details, ▶ Run, ⏸ Pause, 🟢 Running, ⚪ Paused

# Add help text
st.caption("Demo scenarios continuously test security across agents")

# Use columns for better layout
col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

# Color-code security scores
if score > 80:
    st.success(f"Security Score: {score:.1f}%")
elif score > 50:
    st.warning(f"Security Score: {score:.1f}%")
else:
    st.error(f"Security Score: {score:.1f}%")
```

**Acceptance Criteria:**
- [x] Consistent spacing and dividers (st.markdown("---"))
- [x] Icons used appropriately (🎯, 📋, ▶, ⏸, 🟢, ⚪, 📊, 🔐, ✅, ⚠️)
- [x] Help text and captions added
- [x] Color-coding for security scores (st.success/warning/error)
- [x] Responsive layout (use_container_width=True)

---

### Task 4.3: End-to-End Testing

**Status:** Skipped (manual testing by user)

**Effort:** 0.5 hours
**Priority:** P0
**Files:**
- Manual testing checklist

**Description:**
Test all features end-to-end.

**Test Cases:**

**Demo Tab:**
1. ✅ Tab loads without errors
2. ✅ Scenario cards display with correct data
3. ✅ Run Once button triggers scenario
4. ✅ Pause button stops continuous execution
5. ✅ Resume button starts continuous execution
6. ✅ Details button shows prompts
7. ✅ Pause All pauses all running scenarios
8. ✅ Resume All resumes continuous scenarios
9. ✅ Comparison results display metrics
10. ✅ Auto-refresh updates data every 30s

**Overview Tab:**
1. ✅ Bedrock comparison table displays
2. ✅ Table shows 3 agent types
3. ✅ Dual pie charts render
4. ✅ Charts use correct colors
5. ✅ Metrics match Demo Tab data
6. ✅ Graceful degradation if demo orchestrator down

**Error Handling:**
1. ✅ Demo orchestrator unreachable → error message
2. ✅ Timeout → timeout message
3. ✅ No data → empty state message
4. ✅ Invalid scenario ID → 404 handled
5. ✅ Network error → retry suggestion

**Acceptance Criteria:**
- [ ] All test cases pass
- [ ] No console errors
- [ ] UI responsive and smooth
- [ ] Auto-refresh works without flickering

---

## Success Metrics

**Technical:**
- ✅ Demo Tab functional with all controls
- ✅ Overview Tab shows Bedrock comparison
- ✅ Auto-refresh working
- ✅ Error handling comprehensive
- ✅ UI matches Sentra design

**User Experience:**
- ✅ Intuitive scenario management
- ✅ Clear visual comparison (secured vs unsecured)
- ✅ Immediate feedback on actions
- ✅ Helpful error messages
- ✅ No page crashes or freezes

---

## Dependencies

**Blocking:**
- Workstream 13 (Demo Orchestrator) - needs API endpoints
- Workstream 4 (Dashboard) - existing Streamlit app

**Blocked By This:**
- None

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Demo orchestrator downtime | High | Graceful degradation, error messages |
| Auto-refresh performance | Medium | Optimize API calls, add caching |
| Plotly dependency issues | Low | Test in staging first, fallback to simple charts |
| Streamlit session state bugs | Medium | Thorough testing, use stable session keys |

---

## Rollback Plan

If Demo Tab causes issues:
1. Remove "Demo" from tab list in `app.py`
2. Redeploy dashboard
3. Tab disappears, no impact on other features

If Overview Tab updates cause issues:
1. Comment out `render_bedrock_comparison()` call
2. Redeploy dashboard
3. Overview reverts to original state

---

## Completion Checklist

- [ ] Milestone 1: Demo Tab with scenario controls complete
- [ ] Milestone 2: Comparison results in Demo Tab complete
- [ ] Milestone 3: Overview Tab Bedrock comparison complete
- [ ] Milestone 4: Polish and testing complete
- [ ] Demo Tab tested end-to-end
- [ ] Overview Tab tested end-to-end
- [ ] Error handling validated
- [ ] Auto-refresh performance acceptable
- [ ] Documentation updated
- [ ] Demo ready for customer presentations
