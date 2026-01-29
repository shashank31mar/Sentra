# Streamlit Lessons Learned - Dashboard Development

## Date: November 30, 2025

## Critical Lessons from Real-World Debugging

### 1. ⚠️ **NEVER Use `st.rerun()` Inside Render Functions**

**Problem:** Causes SessionInfo race conditions, blank tabs, JS errors

**Why It Fails:**
- Streamlit's execution model doesn't handle mid-render reruns well
- Creates race conditions with widget state
- Causes "SessionInfo not found" errors

**Solution:**
```python
# ❌ BAD - Causes crashes
if st.button("Navigate"):
    st.session_state.active_tab = "security"
    st.rerun()  # DON'T DO THIS!

# ✅ GOOD - Use callbacks
def _navigate():
    st.session_state.active_tab = "security"
    return

st.button("Navigate", on_click=_navigate)
```

**Fixed in:** Milestone 16 (removed 15 instances)

---

### 2. ⚠️ **URL Query Params Must Be Applied Only Once**

**Problem:** URL params re-applied on every rerun override user interactions

**Why It Fails:**
```python
# ❌ BAD - Overrides user clicks every rerun
url_tab = st.query_params.get("tab")
if url_tab:
    st.session_state.active_tab = url_tab  # Runs EVERY rerun!

# User clicks radio → next rerun → URL overrides it again → infinite loop
```

**Solution:**
```python
# ✅ GOOD - Apply URL only once
if url_tab and not st.session_state.get("_url_tab_applied"):
    st.session_state.active_tab = url_tab
    st.session_state._url_tab_applied = True  # Mark as applied

# Detect user changes by comparing previous value
prev_active = st.session_state.get("active_tab")
selected_tab = st.radio(..., key="active_tab")
if selected_tab != prev_active:
    st.query_params["tab"] = selected_tab  # Sync URL
```

**Fixed in:** Milestone 19

---

### 3. ⚠️ **Single Source of Truth for Widget State**

**Problem:** Dual-key pattern (e.g., `active_tab` + `tab_selector`) causes sync issues

**Why It Fails:**
- Two keys = two sources of truth
- Race conditions when updating both
- Widget state and session state get out of sync
- Results in double-click requirement

**Solution:**
```python
# ❌ BAD - Two keys to sync
st.session_state.active_tab = "security"
st.session_state.tab_selector = "security"  # Must keep in sync!
st.radio(..., key="tab_selector")

# ✅ GOOD - Single key
st.session_state.active_tab = "security"
st.radio(..., key="active_tab")  # Widget uses same key
```

**Fixed in:** Milestone 17

---

### 4. ⚠️ **Widget Keys Must Be Unique in Loops**

**Problem:** Duplicate keys cause "Multiple elements with same key" errors

**Solution:**
```python
# ❌ BAD - Duplicate keys
for rule in rules:
    st.button("View", key="view_btn")  # Same key every iteration!

# ✅ GOOD - Unique keys with index
for idx, rule in enumerate(rules):
    st.button("View", key=f"view_{rule['id']}_{idx}")
```

**Status:** Already implemented correctly

---

### 5. ⚠️ **Avoid Nested Columns >1 Level**

**Problem:** Streamlit throws "Columns can only be placed inside other columns up to one level of nesting"

**Solution:**
```python
# ❌ BAD - 2 levels of nesting
col1, col2 = st.columns(2)
with col1:
    inner_col1, inner_col2 = st.columns(2)  # Nested!
    with inner_col1:
        more_cols = st.columns(3)  # ERROR!

# ✅ GOOD - Use containers
col1, col2 = st.columns(2)
with col1:
    container = st.container()  # Use container instead
    with container:
        # Content here
```

**Status:** Already implemented correctly

---

### 6. ✅ **Use Caching for API Calls**

**Best Practice:** Cache frequently-called APIs to reduce load

```python
@st.cache_data(ttl=10, show_spinner=False)
def get_agents_cached():
    return client.get_agents()

# Benefits:
# - 90% reduction in API calls
# - Faster page loads
# - Lower server load
```

**Implemented in:** Milestone 18

---

### 7. ✅ **Server-Side Pagination for Large Datasets**

**Best Practice:** Fetch only what you need, not everything

```python
# ❌ BAD - Fetch 1000 records, paginate client-side
logs = fetch_logs(limit=1000)
page_logs = logs[start:end]

# ✅ GOOD - Fetch only current page
logs = fetch_logs(limit=50, page=current_page)
```

**Implemented in:** Milestone 18 (95% payload reduction)

---

### 8. ✅ **Programmatic Navigation Pattern**

**Best Practice:** When navigating from buttons/components

```python
def _navigate_to_tab(target_tab: str):
    st.session_state["active_tab"] = target_tab
    st.session_state["_url_tab_applied"] = False  # Allow URL re-apply
    st.query_params["tab"] = target_tab
    return  # End render cleanly

st.button("Go to Security", on_click=lambda: _navigate_to_tab("security"))
```

---

## Performance Best Practices

### 1. **Cache Expensive Operations**
- API calls: 5-30 second TTL
- Database queries: 10-60 second TTL
- Static data: No expiration

### 2. **Minimize Reruns**
- Use callbacks instead of `st.rerun()`
- Let Streamlit handle natural reruns
- Avoid tight polling loops

### 3. **Optimize Data Fetching**
- Server-side pagination
- Fetch only visible data
- Use filters to reduce payload

### 4. **Widget State Management**
- Single source of truth
- Use widget `key` parameter
- Avoid manual state sync

---

## Common Pitfalls to Avoid

1. ❌ Using `st.rerun()` in render functions
2. ❌ Re-applying URL params on every rerun
3. ❌ Dual-key state management
4. ❌ Fetching large datasets without pagination
5. ❌ No caching on API calls
6. ❌ Duplicate widget keys in loops
7. ❌ Nested columns >1 level
8. ❌ Blocking sleep + rerun for auto-refresh

---

## Debugging Tips

### 1. **Add Debug Output**
```python
st.write("DEBUG url params:", st.query_params)
st.write("DEBUG active_tab:", st.session_state.get("active_tab"))
```

### 2. **Check CloudWatch Logs**
- Look for SessionInfo errors
- Check API call frequency
- Monitor response times

### 3. **Browser DevTools**
- Network tab: Check payload sizes
- Console: Check for JS errors
- Application tab: Check session storage

### 4. **Test Scenarios**
- First page load (deep link)
- User clicks (radio buttons)
- Programmatic navigation (buttons)
- Page refresh
- Multiple tabs open

---

## Summary of Fixes (Milestones 15-19)

| Milestone | Fix | Impact |
|-----------|-----|--------|
| M15 | Initial navigation sync | Fixed double-click |
| M16 | Removed 15 `st.rerun()` calls | Fixed crashes |
| M17 | Single source of truth | Fixed state sync |
| M18 | Caching + pagination | 90% faster |
| M19 | URL apply-once pattern | Fixed tab switching |

---

## Key Takeaway

**Streamlit's execution model is simple but strict:**
1. Every interaction triggers a full script rerun
2. Widget state is managed by Streamlit (via `key` parameter)
3. Manual `st.rerun()` breaks this model
4. URL params persist across reruns (must handle carefully)
5. Single source of truth prevents sync issues

**Follow these patterns and your Streamlit app will be stable and performant!**
