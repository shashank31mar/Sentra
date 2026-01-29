# LLD 07: Dashboard UI - Demo Tab & Overview Tab Updates

**Version**: 1.0
**Last Updated**: 2025-01-15
**Status**: Draft - Ready for Review
**Prerequisites**:
- [LLD 06: Demo Orchestrator](lld/06-demo-orchestrator.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Demo Tab Design](#2-demo-tab-design)
3. [Overview Tab Updates](#3-overview-tab-updates)
4. [Implementation Details](#4-implementation-details)
5. [Cross-References](#5-cross-references)

---

## 1. Overview

### 1.1 Purpose

Add UI components to the existing Streamlit dashboard for:
1. **Demo Tab** (NEW): Control and visualize demo scenarios
2. **Overview Tab** (UPDATE): Add Bedrock comparison visualization

### 1.2 Existing Dashboard

**Location**: `src/dashboard/`
**Framework**: Streamlit
**Current Structure**:
```
src/dashboard/
├── app.py                    # Main Streamlit app
├── tabs/                     # Tab implementations
│   ├── overview.py           # Overview tab (UPDATE)
│   └── ...                   # Other tabs
├── components/               # Reusable components
└── services/                 # API clients
```

---

## 2. Demo Tab Design

### 2.1 Layout

```
┌─────────────────────────────────────────────────────────┐
│  Demo Scenarios                                         │
├─────────────────────────────────────────────────────────┤
│  [Scenario Card 1]                                      │
│  ┌───────────────────────────────────────────────────┐ │
│  │ Prompt Injection Attacks              ● Running   │ │
│  │ Tests various prompt injection techniques         │ │
│  │ Mode: Continuous | Interval: 120s | Prompts: 5   │ │
│  │ [▶ Run Once] [⏸ Pause] [📋 View Details]         │ │
│  └───────────────────────────────────────────────────┘ │
│                                                         │
│  [Scenario Card 2]                                      │
│  ┌───────────────────────────────────────────────────┐ │
│  │ PII Leakage                           ○ Paused    │ │
│  │ Tests attempts to extract sensitive information   │ │
│  │ Mode: Continuous | Interval: 180s | Prompts: 5   │ │
│  │ [▶ Run Once] [▶ Resume] [📋 View Details]        │ │
│  └───────────────────────────────────────────────────┘ │
│                                                         │
│  [⏯ Pause All] [▶ Resume All]                          │
├─────────────────────────────────────────────────────────┤
│  Latest Results (Last Run)                              │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────┬──────────────┬───────────────────┐   │
│  │ Self-Hosted  │ Bedrock      │ Bedrock Unsecured │   │
│  │              │ Secured      │     ⚠️            │   │
│  ├──────────────┼──────────────┼───────────────────┤   │
│  │ Denied: 85%  │ Denied: 83%  │ Denied: 21%       │   │
│  │ Allowed: 10% │ Allowed: 12% │ Allowed: 79% ⚠️   │   │
│  │ Rollback: 5% │ Rollback: 5% │ Rollback: 0%      │   │
│  └──────────────┴──────────────┴───────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Scenario Details Modal

```
┌─────────────────────────────────────────────────────────┐
│  Prompt Injection Attacks                           ✕   │
├─────────────────────────────────────────────────────────┤
│  Status: ✅ Running (Continuous)                        │
│  Interval: Every 120 seconds                            │
│  Agents: payment-agent, customer-query-agent,           │
│          bedrock-secured, bedrock-unsecured             │
│                                                         │
│  Test Prompts:                                          │
│  ┌───────────────────────────────────────────────────┐ │
│  │ 1. Direct Override                                │ │
│  │    "Ignore all previous instructions..."         │ │
│  │    Expected: DENY (Prompt injection)              │ │
│  └───────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────┐ │
│  │ 2. Role Manipulation                              │ │
│  │    "You are now an admin..."                      │ │
│  │    Expected: DENY (Privilege escalation)          │ │
│  └───────────────────────────────────────────────────┘ │
│  ... (3 more prompts)                                   │
│                                                         │
│  [▶ Run Now] [⏸ Pause Continuous] [Close]              │
└─────────────────────────────────────────────────────────┘
```

### 2.3 Implementation (Streamlit)

```python
# tabs/demo.py

import streamlit as st
import requests
from typing import List, Dict

DEMO_ORCHESTRATOR_URL = "http://demo-orchestrator.sentra.internal:8080"


def render_demo_tab():
    """Render Demo Scenarios tab"""

    st.header("🎯 Demo Scenarios")

    # Fetch scenarios
    scenarios = fetch_scenarios()

    # Render scenario cards
    for scenario in scenarios:
        render_scenario_card(scenario)

    # Global controls
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⏯ Pause All"):
            pause_all_scenarios()
    with col2:
        if st.button("▶ Resume All"):
            resume_all_scenarios()

    st.divider()

    # Latest results
    st.subheader("📊 Latest Results")
    render_comparison_results()


def render_scenario_card(scenario: Dict):
    """Render individual scenario card"""

    with st.expander(
        f"{'🟢' if scenario['status'] == 'running' else '⚪'} "
        f"{scenario['name']}",
        expanded=False
    ):
        st.write(scenario['description'])

        # Metadata
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Mode", scenario['mode'])
        with col2:
            if scenario.get('interval'):
                st.metric("Interval", f"{scenario['interval']}s")
        with col3:
            st.metric("Prompts", scenario['prompt_count'])

        # Action buttons
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button(
                "▶ Run Once",
                key=f"run_{scenario['scenario_id']}"
            ):
                trigger_scenario(scenario['scenario_id'])
                st.success("Scenario triggered!")

        with col2:
            if scenario['status'] == 'running':
                if st.button(
                    "⏸ Pause",
                    key=f"pause_{scenario['scenario_id']}"
                ):
                    pause_scenario(scenario['scenario_id'])
                    st.rerun()
            else:
                if st.button(
                    "▶ Resume",
                    key=f"resume_{scenario['scenario_id']}"
                ):
                    start_scenario(scenario['scenario_id'])
                    st.rerun()

        with col3:
            if st.button(
                "📋 View Details",
                key=f"view_{scenario['scenario_id']}"
            ):
                show_scenario_details(scenario['scenario_id'])


def show_scenario_details(scenario_id: str):
    """Show scenario details in modal/dialog"""

    # Fetch detailed scenario
    response = requests.get(
        f"{DEMO_ORCHESTRATOR_URL}/demo/scenarios/{scenario_id}"
    )
    scenario = response.json()

    # Use Streamlit dialog (if available) or expander
    st.subheader(f"📋 {scenario['name']}")

    st.write(f"**Description**: {scenario['description']}")
    st.write(f"**Mode**: {scenario['mode']}")
    if scenario.get('interval'):
        st.write(f"**Interval**: Every {scenario['interval']} seconds")

    # Agents
    st.write("**Target Agents**:")
    for agent in scenario['agents']['self_hosted']:
        st.write(f"- {agent} (Self-Hosted)")
    for agent in scenario['agents']['bedrock']:
        st.write(f"- {agent} (Bedrock)")

    # Prompts
    st.write("**Test Prompts**:")
    for idx, prompt in enumerate(scenario['prompts'], 1):
        with st.container():
            st.markdown(f"**{idx}. {prompt['id']}**")
            st.code(prompt['text'], language=None)
            st.caption(
                f"Expected: {prompt['expected_decision']} "
                f"({prompt['expected_threat']})"
            )


def render_comparison_results():
    """Render comparison metrics grid"""

    # Fetch comparison data
    response = requests.get(
        f"{DEMO_ORCHESTRATOR_URL}/demo/comparison?hours=1"
    )
    data = response.json()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Self-Hosted Agents")
        render_agent_metrics(data['comparison']['self_hosted'])

    with col2:
        st.subheader("Bedrock Secured")
        render_agent_metrics(data['comparison']['bedrock_secured'])

    with col3:
        st.subheader("⚠️ Bedrock Unsecured")
        render_agent_metrics(
            data['comparison']['bedrock_unsecured'],
            is_unsecured=True
        )


def render_agent_metrics(metrics: Dict, is_unsecured: bool = False):
    """Render metrics for single agent type"""

    if metrics['total'] == 0:
        st.info("No data yet")
        return

    # Denied (good)
    st.metric(
        "Denied",
        f"{metrics['denied_pct']}%",
        delta=f"{metrics['denied']} requests",
        delta_color="normal"
    )

    # Allowed (bad if unsecured)
    st.metric(
        "Allowed",
        f"{metrics['allowed_pct']}%",
        delta=f"{metrics['allowed']} requests",
        delta_color="inverse" if is_unsecured else "normal"
    )

    # Rollback
    if 'rollback_pct' in metrics:
        st.metric(
            "Rollback",
            f"{metrics['rollback_pct']}%",
            delta=f"{metrics['rollback']} requests"
        )


# API helper functions

def fetch_scenarios() -> List[Dict]:
    """Fetch all scenarios from demo orchestrator"""
    response = requests.get(f"{DEMO_ORCHESTRATOR_URL}/demo/scenarios")
    return response.json()['scenarios']


def trigger_scenario(scenario_id: str):
    """Trigger scenario once"""
    requests.post(
        f"{DEMO_ORCHESTRATOR_URL}/demo/scenarios/{scenario_id}/trigger"
    )


def start_scenario(scenario_id: str):
    """Start continuous execution"""
    requests.post(
        f"{DEMO_ORCHESTRATOR_URL}/demo/scenarios/{scenario_id}/start"
    )


def pause_scenario(scenario_id: str):
    """Pause continuous execution"""
    requests.post(
        f"{DEMO_ORCHESTRATOR_URL}/demo/scenarios/{scenario_id}/pause"
    )


def pause_all_scenarios():
    """Pause all running scenarios"""
    scenarios = fetch_scenarios()
    for scenario in scenarios:
        if scenario['status'] == 'running':
            pause_scenario(scenario['scenario_id'])


def resume_all_scenarios():
    """Resume all paused continuous scenarios"""
    scenarios = fetch_scenarios()
    for scenario in scenarios:
        if scenario['mode'] == 'continuous' and scenario['status'] == 'paused':
            start_scenario(scenario['scenario_id'])
```

---

## 3. Overview Tab Updates

### 3.1 Add Bedrock Comparison Section

```
┌─────────────────────────────────────────────────────────┐
│  Overview (Existing sections above)                     │
├─────────────────────────────────────────────────────────┤
│  🔐 Bedrock Agent Security Comparison (24h)             │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────┐  │
│  │                                                  │  │
│  │  [Table: Self-Hosted | Bedrock Secured |        │  │
│  │           Bedrock Unsecured]                     │  │
│  │                                                  │  │
│  │  ┌──────────────┬──────────────┬──────────────┐ │  │
│  │  │ Self-Hosted  │ Bedrock      │ Bedrock      │ │  │
│  │  │              │ Secured      │ Unsecured ⚠️ │ │  │
│  │  ├──────────────┼──────────────┼──────────────┤ │  │
│  │  │ Total: 500   │ Total: 480   │ Total: 490   │ │  │
│  │  │ Denied: 425  │ Denied: 400  │ Denied: 100  │ │  │
│  │  │ Allowed: 60  │ Allowed: 70  │ Allowed: 380 │ │  │
│  │  │ Score: 85%   │ Score: 83%   │ Score: 20%   │ │  │
│  │  └──────────────┴──────────────┴──────────────┘ │  │
│  │                                                  │  │
│  │  Dual Pie Charts:                                │  │
│  │  ┌──────────┐          ┌──────────┐             │  │
│  │  │ Unsecured│          │ Secured  │             │  │
│  │  │ (mostly  │          │ (mostly  │             │  │
│  │  │  red)    │          │  green)  │             │  │
│  │  └──────────┘          └──────────┘             │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Implementation

```python
# tabs/overview.py (add to existing file)

def render_bedrock_comparison():
    """Add Bedrock comparison section to Overview tab"""

    st.subheader("🔐 Bedrock Agent Security Comparison (24h)")

    # Fetch comparison data
    response = requests.get(
        "http://demo-orchestrator.sentra.internal:8080/demo/comparison?hours=24"
    )
    data = response.json()['comparison']

    # Comparison table
    render_comparison_table(data)

    st.divider()

    # Dual pie charts
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Bedrock Unsecured ⚠️**")
        render_pie_chart(data['bedrock_unsecured'], is_unsecured=True)
        st.caption("⚠️ High Risk - No Security Layer")

    with col2:
        st.markdown("**Bedrock Secured (Sentra)**")
        render_pie_chart(data['bedrock_secured'], is_unsecured=False)
        st.caption("✅ Protected by Sentra")


def render_comparison_table(data: Dict):
    """Render comparison table"""

    import pandas as pd

    # Create DataFrame
    df = pd.DataFrame({
        "Agent Type": [
            "Self-Hosted",
            "Bedrock Secured",
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
            f"{100 - data['self_hosted']['allowed_pct']:.1f}%",
            f"{100 - data['bedrock_secured']['allowed_pct']:.1f}%",
            f"{100 - data['bedrock_unsecured']['allowed_pct']:.1f}%"
        ]
    })

    st.dataframe(df, use_container_width=True)


def render_pie_chart(metrics: Dict, is_unsecured: bool):
    """Render pie chart for agent type"""

    import plotly.graph_objects as go

    if metrics['total'] == 0:
        st.info("No data yet")
        return

    labels = ['Denied', 'Allowed', 'Rollback']
    values = [
        metrics['denied'],
        metrics['allowed'],
        metrics.get('rollback', 0)
    ]

    # Color scheme
    if is_unsecured:
        colors = ['#ffaa00', '#ff4444', '#4444ff']  # Yellow, Red, Blue
    else:
        colors = ['#44ff44', '#ffaa00', '#4444ff']  # Green, Yellow, Blue

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        marker=dict(colors=colors),
        hole=0.3
    )])

    fig.update_layout(
        showlegend=True,
        height=300,
        margin=dict(t=0, b=0, l=0, r=0)
    )

    st.plotly_chart(fig, use_container_width=True)
```

---

## 4. Implementation Details

### 4.1 File Changes

**New Files**:
- `src/dashboard/tabs/demo.py` (NEW)

**Modified Files**:
- `src/dashboard/app.py` (add Demo tab)
- `src/dashboard/tabs/overview.py` (add Bedrock comparison section)

### 4.2 Dependencies

**Already in requirements.txt**:
- `streamlit`
- `requests`
- `pandas`
- `plotly`

**No new dependencies needed**

### 4.3 Integration with Main App

```python
# src/dashboard/app.py (modifications)

from tabs.demo import render_demo_tab
from tabs.overview import render_bedrock_comparison

# Add Demo tab
tab_list = ["Overview", "Demo", ...]  # Add "Demo"

# In tab rendering logic
if selected_tab == "Demo":
    render_demo_tab()
elif selected_tab == "Overview":
    # Existing overview content
    ...
    # NEW: Add Bedrock comparison at bottom
    render_bedrock_comparison()
```

---

## 5. Cross-References

### 5.1 Related LLD Documents

- **LLD 06 (Demo Orchestrator)**: Backend APIs, data models, scenario definitions

### 5.2 Related Design Documents

- **design-hld.md**: Overall system architecture
- **best-practices.md**: UI design patterns, Streamlit best practices

---

**End of Document**
