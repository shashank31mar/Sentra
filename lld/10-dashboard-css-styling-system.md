# LLD 10: Dashboard CSS Styling System

## 1. Overview

### 1.1 Purpose
This document describes the CSS styling system implemented for the Sentra dashboard using a **Hybrid CSS approach** that balances visual polish with Streamlit reliability.

### 1.2 Scope
- CSS architecture and design system
- Component styling patterns
- Streamlit integration approach
- Implementation guidelines
- Maintenance and extensibility

### 1.3 Implementation Date
November 30, 2025

### 1.4 Related Documents
- LLD 04: Dashboard V2 (functional architecture)
- LLD 08: Authentication and ALB Architecture

---

## 2. Architecture

### 2.1 Hybrid Approach

**Core Principle:** Separate visual styling (CSS) from interactivity (Streamlit widgets)

```
┌─────────────────────────────────────────┐
│         Dashboard Component             │
├─────────────────────────────────────────┤
│  ┌───────────────────────────────────┐  │
│  │   CSS Layer (Visual Only)         │  │
│  │   - Layout (cards, grids)         │  │
│  │   - Colors & typography           │  │
│  │   - Spacing & shadows             │  │
│  │   - Hover effects                 │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │   Streamlit Layer (Interactive)   │  │
│  │   - Buttons & forms               │  │
│  │   - State management              │  │
│  │   - Callbacks & events            │  │
│  │   - Session handling              │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### 2.2 Design Principles

1. **CSS for visuals only** - Layout, colors, spacing, cards, badges
2. **Streamlit for interactivity** - All buttons, inputs, forms remain native
3. **HTML wrappers** - Use `st.markdown(..., unsafe_allow_html=True)` for structure only
4. **No JavaScript** - Avoid custom event handlers that break Streamlit lifecycle
5. **Unique widget keys** - Prevent duplicate key errors with consistent naming

### 2.3 File Structure

```
src/dashboard/
├── static/
│   └── styles.css              # Main CSS file (498 lines)
├── .streamlit/
│   └── config.toml             # Streamlit theme config
├── app.py                      # Loads CSS via load_custom_css()
└── components/
    ├── agent_list.py           # Uses .card, .agent-item
    ├── agent_details.py        # Uses .card, .status-badge
    ├── security_metrics.py     # Uses .card, .metrics-row
    └── ...                     # Other components
```

---

## 3. Design System

### 3.1 Color Palette

```css
:root {
  --bg: #f5f7fb;          /* Light blue-gray background */
  --panel: #ffffff;       /* White cards */
  --text: #1f2933;        /* Dark gray text */
  --muted: #7b8794;       /* Muted text */
  --accent: #5b4dff;      /* Purple primary */
  --accent-2: #00c2b8;    /* Teal secondary */
  --danger: #ff6b6b;      /* Red */
  --success: #14b8a6;     /* Green */
  --warning: #f59e0b;     /* Yellow */
}
```

**Usage:**
- Background: Light blue-gray for reduced eye strain
- Cards: White with subtle shadows for depth
- Accent: Purple for primary actions and branding
- Status colors: Semantic (green=success, red=danger, yellow=warning)

### 3.2 Typography

**Font Family:** Inter (Google Fonts)
- Modern, professional sans-serif
- Weights: 300, 400, 600, 700, 800
- Antialiased rendering

**Hierarchy:**
- H1: 34px, weight 800 (page titles)
- H2: 24px, weight 700 (section headers)
- H3: 18px, weight 600 (component titles)
- H4: 16px, weight 600 (subsections)
- Body: 14px, weight 400
- Muted: 13px, color var(--muted)

### 3.3 Spacing System

**Base Unit:** 16px (`--space`)

**Utility Classes:**
- `.gap-sm`: 8px
- `.gap-md`: 12px
- `.gap-lg`: 16px
- `.mb-sm`, `.mb-md`, `.mb-lg`: Margin bottom
- `.mt-sm`, `.mt-md`, `.mt-lg`: Margin top

**Container Padding:**
- Desktop: 48px
- Mobile: 12px (responsive)

### 3.4 Shadows & Depth

```css
--card-shadow: 0 10px 30px rgba(17,24,39,0.06);
```

**Elevation Levels:**
- Level 0: No shadow (background)
- Level 1: Card shadow (panels)
- Level 2: Hover shadow (interactive elements)

---

## 4. Component Patterns

### 4.1 Card Pattern

**Purpose:** Container for related content with visual grouping

**CSS Classes:**
- `.card` - Main card (18px padding)
- `.card-compact` - Smaller card (12px padding)

**Implementation:**
```python
st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("Component Title")

# Streamlit widgets here
st.metric("Metric", "Value")
if st.button("Action"):
    handle_action()

st.markdown('</div>', unsafe_allow_html=True)
```

**Visual Properties:**
- Background: White
- Border radius: 12px
- Shadow: Subtle (0 10px 30px rgba)
- Border: 1px solid rgba(17,24,39,0.03)

### 4.2 Status Badge Pattern

**Purpose:** Visual indicators for status, severity, or categories

**CSS Classes:**
- `.status-badge` - Base badge
- `.status-badge.success` - Green (active, running, allowed)
- `.status-badge.danger` - Red (critical, error, denied)
- `.status-badge.warning` - Yellow (warning, pending)
- `.status-badge.info` - Blue (info, disabled)

**Implementation:**
```python
st.markdown('<span class="status-badge success">Active</span>', unsafe_allow_html=True)
```

**Visual Properties:**
- Padding: 4px 10px
- Border radius: 12px
- Font size: 12px
- Font weight: 600

### 4.3 Agent List Pattern

**Purpose:** Selectable list of agents with status indicators

**CSS Classes:**
- `.agent-list` - Container
- `.agent-item` - Individual item
- `.agent-item.selected` - Selected state
- `.agent-name` - Agent name text
- `.agent-desc` - Description text

**Implementation:**
```python
st.markdown('<div class="agent-list">', unsafe_allow_html=True)

for agent in agents:
    selected_class = "selected" if is_selected else ""
    st.markdown(f'''
        <div class="agent-item {selected_class}">
            <div class="dot" style="background:{dot_color}"></div>
            <div style="flex:1">
                <div class="agent-name">{agent_name}</div>
                <div class="agent-desc">{description}</div>
            </div>
        </div>
    ''', unsafe_allow_html=True)
    
    # Streamlit button for interaction
    if st.button(f"Select {agent_name}", key=f"agent_{agent_id}"):
        handle_selection(agent_id)

st.markdown('</div>', unsafe_allow_html=True)
```

**Visual Properties:**
- Hover: translateY(-3px) with enhanced shadow
- Selected: Purple border and gradient background
- Status dot: 12px circle with color

### 4.4 Activity Feed Pattern

**Purpose:** Time-ordered list of events with color coding

**CSS Classes:**
- `.feed-row` - Base feed item
- `.feed-allow` - Green gradient (allowed actions)
- `.feed-deny` - Red gradient (denied actions)
- `.feed-warning` - Yellow gradient (warnings)

**Implementation:**
```python
st.markdown(f'''
    <div class="feed-row feed-allow">
        <div style="display: flex; justify-content: space-between;">
            <span style="font-weight: 600;">✅ {timestamp}</span>
            <span class="status-badge success">ALLOW</span>
        </div>
        <div class="muted">
            <strong>Tool:</strong> {tool_name}<br>
            <strong>Agent:</strong> {agent_id}
        </div>
    </div>
''', unsafe_allow_html=True)
```

**Visual Properties:**
- Allow: Green gradient background
- Deny: Red gradient background
- Padding: 14px
- Border radius: 10px
- Margin bottom: 10px

### 4.5 Tool/Policy Row Pattern

**Purpose:** List items with badges and action buttons

**CSS Classes:**
- `.tool-row` - Container
- `.tool-left` - Content area
- `.tool-badge` - Tool name badge

**Implementation:**
```python
st.markdown(f'''
    <div class="tool-row">
        <div class="tool-left">
            <div class="tool-badge success">✅ {tool_name}</div>
            <span class="status-badge success">READ</span>
        </div>
    </div>
''', unsafe_allow_html=True)
st.markdown(f'<div class="muted">{description}</div>', unsafe_allow_html=True)

# Streamlit buttons for actions
col1, col2 = st.columns([1, 1])
with col1:
    if st.button("Configure", key=f"cfg_{idx}"):
        handle_configure()
with col2:
    if st.button("Remove", key=f"rm_{idx}"):
        handle_remove()
```

### 4.6 Sigma Rule Pattern

**Purpose:** Rule cards with multiple status indicators

**CSS Classes:**
- `.sigma-rule` - Rule card
- `.sigma-left` - Content area

**Implementation:**
```python
st.markdown(f'''
    <div class="sigma-rule card-compact">
        <div class="sigma-left">
            <div style="display: flex; gap: 8px; align-items: center;">
                <strong>📋 {rule_name}</strong>
                <span class="status-badge success">Active</span>
                <span class="status-badge danger">HIGH</span>
            </div>
            <div class="muted">{description}</div>
            <div class="muted" style="font-size: 12px;">
                Matches: {match_count} | Patterns: {pattern_count}
            </div>
        </div>
    </div>
''', unsafe_allow_html=True)

# Action buttons
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("View", key=f"view_{idx}"):
        handle_view()
# ... more buttons
```

---

## 5. CSS Class Reference

### 5.1 Layout Classes

| Class | Purpose | Properties |
|-------|---------|------------|
| `.card` | Main container | White bg, shadow, 18px padding |
| `.card-compact` | Smaller container | White bg, shadow, 12px padding |
| `.metrics-row` | Flex row for metrics | Display flex, gap 24px |
| `.flex` | Flexbox container | Display flex |
| `.flex-col` | Column flex | Flex-direction column |

### 5.2 Component Classes

| Class | Purpose | Properties |
|-------|---------|------------|
| `.agent-list` | Agent container | Flex column, gap 10px |
| `.agent-item` | Agent card | Gradient bg, hover effect |
| `.agent-item.selected` | Selected agent | Purple border, gradient |
| `.feed-row` | Feed item | Padding 14px, rounded |
| `.feed-allow` | Allowed action | Green gradient |
| `.feed-deny` | Denied action | Red gradient |
| `.tool-row` | Tool/policy row | Flex, space-between |
| `.sigma-rule` | Sigma rule card | Compact card style |

### 5.3 Status Classes

| Class | Purpose | Color |
|-------|---------|-------|
| `.status-badge` | Base badge | - |
| `.status-badge.success` | Success state | Green (#14b8a6) |
| `.status-badge.danger` | Error/critical | Red (#ff6b6b) |
| `.status-badge.warning` | Warning state | Yellow (#f59e0b) |
| `.status-badge.info` | Info state | Blue (#3b82f6) |

### 5.4 Utility Classes

| Class | Purpose | Value |
|-------|---------|-------|
| `.muted` | Muted text | Color: #7b8794 |
| `.gap-sm` | Small gap | 8px |
| `.gap-md` | Medium gap | 12px |
| `.gap-lg` | Large gap | 16px |
| `.mb-sm` | Margin bottom small | 8px |
| `.mb-md` | Margin bottom medium | 12px |
| `.mb-lg` | Margin bottom large | 16px |
| `.mt-sm` | Margin top small | 8px |
| `.mt-md` | Margin top medium | 12px |
| `.mt-lg` | Margin top large | 16px |

---

## 6. Streamlit Integration

### 6.1 CSS Loading

**Location:** `app.py`

```python
def load_custom_css():
    """Load custom CSS styles."""
    try:
        with open("static/styles.css") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        pass  # Continue without custom styles

def main():
    st.set_page_config(...)
    initialize_session_state()
    load_custom_css()  # Load CSS early
    # ... rest of app
```

### 6.2 Theme Configuration

**Location:** `.streamlit/config.toml`

```toml
[theme]
primaryColor = "#5b4dff"
backgroundColor = "#f5f7fb"
secondaryBackgroundColor = "#ffffff"
textColor = "#1f2933"
font = "sans serif"

[server]
headless = true
port = 8501
enableCORS = false
enableXsrfProtection = true
```

### 6.3 Widget Key Patterns

**Consistent Naming Convention:**
```python
# Pattern: {prefix}_{identifier}_{index}
key=f"agent_{agent_id}"
key=f"view_{rule_id}_{idx}"
key=f"cfg_{tool_id}"
```

**Rules:**
1. Use descriptive prefixes (agent, view, edit, delete)
2. Include unique identifier (ID, index)
3. Add index suffix if rendering in loops
4. Never reuse keys across different widgets

### 6.4 Safe HTML Usage

**DO:**
- Use for structural wrappers (divs, spans)
- Use for visual badges and indicators
- Use for layout containers
- Close all HTML tags properly

**DON'T:**
- Use for interactive elements (buttons, inputs)
- Add JavaScript event handlers
- Target Streamlit internal classes
- Create deeply nested structures

---

## 7. Component Implementation

### 7.1 Components Updated

| Component | File | Changes |
|-----------|------|---------|
| Agent List | `agent_list.py` | Card wrapper, agent items with dots |
| Agent Details | `agent_details.py` | Card wrapper, status badges |
| Agent Status | `agent_status.py` | Card wrapper, progress bars |
| Agent Tools | `agent_tools.py` | Tool rows with badges |
| Agent Policies | `agent_policies.py` | Policy rows with badges |
| Security Metrics | `security_metrics.py` | Card wrapper |
| Activity Feed | `activity_feed.py` | Feed rows with colors |
| Sigma Rules | `sigma_rules_manager.py` | Rule cards |
| Rollback Panel | `rollback_panel.py` | Card wrapper |

### 7.2 Example: Agent List Component

**Before:**
```python
def render(agents):
    st.subheader("Agents")
    for agent in agents:
        if st.button(f"🟢 {agent['name']}", key=f"agent_{agent['id']}"):
            return agent['id']
```

**After:**
```python
def render(agents):
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Agents")
    
    st.markdown('<div class="agent-list">', unsafe_allow_html=True)
    for agent in agents:
        selected_class = "selected" if is_selected else ""
        st.markdown(f'''
            <div class="agent-item {selected_class}">
                <div class="dot" style="background:{dot_color}"></div>
                <div style="flex:1">
                    <div class="agent-name">{agent['name']}</div>
                    <div class="agent-desc">{agent['description'][:60]}</div>
                </div>
            </div>
        ''', unsafe_allow_html=True)
        
        if st.button(f"Select {agent['name']}", 
                    key=f"agent_{agent['id']}", 
                    label_visibility="collapsed"):
            return agent['id']
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
```

---

## 8. Responsive Design

### 8.1 Breakpoints

```css
@media (max-width: 980px) {
  .metrics-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
  
  .block-container {
    padding: 12px !important;
  }
  
  .tool-row {
    flex-direction: column;
    align-items: flex-start;
  }
}
```

### 8.2 Mobile Optimizations

- Reduced padding (48px → 12px)
- Stacked metrics (row → column)
- Full-width buttons
- Larger touch targets
- Simplified layouts

### 8.3 Testing Targets

- Desktop: 1920x1080
- Tablet: 768x1024
- Mobile: 375x667

---

## 9. Performance

### 9.1 Metrics

**File Sizes:**
- CSS: ~10KB (498 lines, minified ~7KB)
- No JavaScript added
- Minimal overhead

**Load Times:**
- CSS loads once and caches
- No impact on Streamlit performance
- Smooth transitions (0.2s)

### 9.2 Optimization Techniques

1. **CSS Variables** - Reduce repetition
2. **Minimal Selectors** - Avoid complex nesting
3. **No Images** - Pure CSS styling
4. **Caching** - Browser caches CSS file
5. **Lazy Loading** - Components render on demand

---

## 10. Maintenance

### 10.1 Adding New Components

**Steps:**
1. Wrap component in `.card` div
2. Use existing CSS classes where possible
3. Add new classes to `styles.css` if needed
4. Keep Streamlit widgets for interactivity
5. Test on desktop, tablet, mobile
6. Document new patterns

**Example:**
```python
def render_new_component():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("New Component")
    
    # Use existing classes
    st.markdown('<span class="status-badge success">Active</span>', 
                unsafe_allow_html=True)
    
    # Streamlit widgets
    if st.button("Action"):
        handle_action()
    
    st.markdown('</div>', unsafe_allow_html=True)
```

### 10.2 Modifying Styles

**Safe Changes:**
- Adjust colors in `:root` variables
- Modify spacing values
- Change border radius
- Update shadows

**Risky Changes:**
- Targeting Streamlit internal classes (`.css-xxxxx`)
- Adding JavaScript
- Complex nested selectors
- Breaking responsive layouts

### 10.3 Testing Checklist

- [ ] Visual appearance correct
- [ ] All buttons clickable
- [ ] No duplicate key errors
- [ ] No console errors
- [ ] Responsive on mobile
- [ ] Works behind ALB
- [ ] No SessionInfo errors

---

## 11. Troubleshooting

### 11.1 Common Issues

**Issue: CSS Not Loading**
- Check file path: `static/styles.css`
- Verify `load_custom_css()` is called
- Check Docker image includes static folder

**Issue: Styles Not Applied**
- Clear browser cache
- Check CSS syntax errors
- Verify class names match

**Issue: Widget Key Conflicts**
- Ensure unique keys with index suffix
- Check for duplicate key patterns
- Use consistent naming convention

**Issue: Layout Breaks on Mobile**
- Test responsive breakpoints
- Check flex-direction changes
- Verify padding adjustments

### 11.2 Debugging Tools

**Browser DevTools:**
- Inspect element to see applied styles
- Check Network tab for CSS loading
- Console for JavaScript errors

**Streamlit:**
- Check logs for widget key errors
- Use `st.write()` for debugging
- Test with `use_real_data=False`

---

## 12. Future Enhancements

### 12.1 Phase 2 Features

**Dark Mode:**
- Add dark theme CSS variables
- Toggle in user settings
- Persist preference in session

**Animations:**
- Skeleton loaders for async data
- Micro-animations for state changes
- Page transition effects

**Additional Utilities:**
- More spacing classes
- Grid system
- Print stylesheet

### 12.2 Extensibility

**Design Tokens:**
```css
:root {
  /* Spacing scale */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;
  --space-xl: 24px;
  
  /* Font scale */
  --font-xs: 12px;
  --font-sm: 14px;
  --font-md: 16px;
  --font-lg: 18px;
  --font-xl: 24px;
}
```

---

## 13. References

### 13.1 Documentation
- Streamlit Theming: https://docs.streamlit.io/library/advanced-features/theming
- CSS Variables: https://developer.mozilla.org/en-US/docs/Web/CSS/Using_CSS_custom_properties
- Flexbox Guide: https://css-tricks.com/snippets/css/a-guide-to-flexbox/

### 13.2 Related Files
- `docs/CSS_QUICK_REFERENCE.md` - Quick snippets
- `docs/CSS_DEPLOYMENT_CHECKLIST.md` - Deploy guide
- `src/dashboard/static/styles.css` - Full CSS

### 13.3 Design Inspiration
- ChatGPT Hybrid Approach Recommendation
- Modern dashboard design patterns
- Material Design principles

---

## Appendix A: Quick Reference

### Common Patterns

**Card Wrapper:**
```python
st.markdown('<div class="card">', unsafe_allow_html=True)
# Content
st.markdown('</div>', unsafe_allow_html=True)
```

**Status Badge:**
```python
st.markdown('<span class="status-badge success">Active</span>', unsafe_allow_html=True)
```

**Feed Row:**
```python
st.markdown(f'<div class="feed-row feed-allow">...</div>', unsafe_allow_html=True)
```

**Tool Row:**
```python
st.markdown(f'<div class="tool-row"><div class="tool-left">...</div></div>', unsafe_allow_html=True)
```

### CSS Variables

```python
# Use in inline styles
style="color: var(--accent)"
style="background: var(--panel)"
style="padding: var(--space)"
```

---

**Document Version:** 1.0  
**Last Updated:** November 30, 2025  
**Status:** Implemented and Ready for Deployment
