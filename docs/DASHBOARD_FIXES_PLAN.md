# Dashboard Code Quality Fixes - Action Plan

## Issues Found & Fixes Needed

### 1. ✅ FIXED: Inconsistent Navigation State (High Priority)
**Status:** Already fixed in milestone-15
- **Issue:** Two sources of truth: `active_tab` and `tab_selector`
- **Fix Applied:** Removed `index=` parameter, keeping both in sync
- **No further action needed**

### 2. ⚠️ NEEDS FIX: Excessive `st.rerun()` Usage (High Priority)
**Issue:** 15+ instances of `st.rerun()` in components causing:
- SessionInfo race conditions
- Blank tabs
- JS errors
- Performance issues

**Files Affected:**
- `components/security_metrics.py` - Line 96
- `components/activity_feed.py` - Line 53
- `components/rollback_panel.py` - Lines 71, 109, 140, 202
- `components/recent_threats.py` - Line 95
- `components/audit_log_table.py` - Lines 142, 150, 172
- `components/audit_export.py` - Line 92
- `components/audit_filters.py` - Line 142
- `components/sigma_rules_manager.py` - Lines 138, 142, 162, 167
- `components/chat_interface.py` - Line 274
- `tabs/chats_tab.py` - Lines 69, 97, 164

**Fix Strategy:**
1. **For navigation buttons:** Use `set_target_tab_in_url()` WITHOUT `st.rerun()` - let Streamlit handle it
2. **For pagination:** Use `on_click` callbacks instead of inline `st.rerun()`
3. **For dialogs:** Use `on_click` callbacks to close dialogs
4. **For auto-refresh:** Remove blocking `st.rerun()` in chats_tab.py

### 3. ⚠️ NEEDS CHECK: Duplicate Widget Keys (Medium Priority)
**Issue:** Keys built from IDs that may be missing → duplicate keys

**Files to Check:**
- `components/sigma_rules_manager.py` - Rule iteration
- `components/recent_threats.py` - Threat iteration
- `components/audit_log_table.py` - Log entry iteration
- `components/rollback_panel.py` - Action iteration

**Fix:** Always append stable index: `key=f"view_{rule_id}_{idx}"`

### 4. ⚠️ NEEDS CHECK: Nested Columns (Medium Priority)
**Issue:** Components create columns inside columns (>1 level)

**Files to Check:**
- `tabs/overview_tab.py` - 2-column layout with components that may have columns
- `tabs/security_tab.py` - 2-column layout
- `tabs/agents_tab.py` - 2-column layout

**Fix:** Pass `parent_is_column=True` flag to components, use `st.container()` instead

### 5. ⚠️ NEEDS CHECK: Session State Modification After Widget (Low Priority)
**Issue:** Modifying `st.session_state` after widget instantiation

**Files to Check:**
- `components/chat_interface.py` - chat_input handling
- `tabs/chats_tab.py` - session selection

**Fix:** Initialize keys before widgets or use callbacks

## Recommended Fix Order

### Phase 1: Critical Fixes (Do Now)
1. Fix `st.rerun()` in navigation buttons (security_metrics, activity_feed, rollback_panel, recent_threats, chat_interface)
2. Fix `st.rerun()` in pagination (audit_log_table)
3. Fix `st.rerun()` in dialogs (audit_export, sigma_rules_manager)

### Phase 2: Important Fixes (Do Soon)
4. Fix auto-refresh in chats_tab.py (remove blocking st.rerun)
5. Check and fix duplicate keys in all components
6. Check and fix nested columns issues

### Phase 3: Polish (Do Later)
7. Check session state modification timing
8. Add comprehensive error handling
9. Performance optimization

## Testing After Fixes
1. Test tab navigation (all tabs)
2. Test pagination in Audit tab
3. Test dialog open/close (export, add rule, import rules)
4. Test rollback confirmation flow
5. Test chat auto-refresh
6. Check browser console for errors
7. Check CloudWatch logs for SessionInfo errors

## Files That Need Changes

### High Priority (Phase 1)
- [ ] `components/security_metrics.py`
- [ ] `components/activity_feed.py`
- [ ] `components/rollback_panel.py`
- [ ] `components/recent_threats.py`
- [ ] `components/audit_log_table.py`
- [ ] `components/audit_export.py`
- [ ] `components/sigma_rules_manager.py`
- [ ] `components/chat_interface.py`

### Medium Priority (Phase 2)
- [ ] `tabs/chats_tab.py`
- [ ] All components with iteration (check keys)
- [ ] All tabs with 2-column layouts

### Low Priority (Phase 3)
- [ ] Review all session state usage
- [ ] Add error boundaries
- [ ] Performance profiling


---

## Phase 2: Medium Priority Performance & Reliability Issues

### 1. ⚠️ Blocking Calls & Frequent Polling
**Issue:** `time.sleep()` + `st.rerun()` causes blocking render and high CPU
**Impact:** Slow UI, ECS task CPU spikes, increased latency
**Status:** ✅ Partially fixed (removed from chats_tab.py in milestone-16)
**Remaining Work:**
- Add `@st.cache_data(ttl=...)` for API fetches
- Replace tight polling with longer intervals + manual refresh button
- Consider background worker pattern

**Example Fix:**
```python
@st.cache_data(ttl=10)
def fetch_agents():
    return security_controller_client.get_agents()
```

### 2. ⚠️ Large Unbounded Fetch Limits
**Issue:** `_fetch_audit_logs` fetches up to 1000 logs, renders all client-side
**Impact:** Slow network, memory issues, long render times
**Files:** `components/audit_log_table.py`
**Fix:** 
- Implement server-side pagination (offset/limit)
- Fetch only current page data (e.g., 50 records)
- Add "Load More" button instead of fetching all

### 3. ⚠️ Excessive `unsafe_allow_html=True` / Custom CSS
**Issue:** `load_custom_css()` and many unsafe HTML snippets
**Impact:** Fragile DOM, potential to break Streamlit internals, security risk
**Files:** `app.py`, multiple components
**Fix:**
- Minimize global CSS
- Scope selectors carefully
- Avoid hiding Streamlit core classes
- Test removing CSS when debugging

### 4. ⚠️ Widgets Without Explicit Keys
**Issue:** Many components rely on implicit keys or duplicate names
**Impact:** "Multiple elements with same key" errors
**Fix:** Adopt namespacing convention: `key=f"{component}_{id}_{widget}"`

**Example:**
```python
# Bad
for rule in rules:
    st.button("View", key="view_btn")  # duplicate!

# Good
for idx, rule in enumerate(rules):
    st.button("View", key=f"sigma_rule_view_{rule['id']}_{idx}")
```

### 5. ⚠️ Mixing stdout/stderr Prints and Logger
**Issue:** Components use `print(..., file=sys.stderr)` inconsistently
**Impact:** Noisy logs, hard to filter
**Fix:** Use `logging.logger.info/debug/error` consistently

### 6. ✅ Using `st.toggle` (Experimental)
**Status:** Already fixed - using `st.checkbox` instead
**No action needed**

---

## Summary of Recommendations

### Do Now (Critical)
- ✅ Fixed in milestone-15, 16, 17

### Do Soon (High Value)
1. Add caching to API calls (`@st.cache_data`)
2. Fix audit log pagination (server-side)
3. Add explicit keys to all widgets in loops

### Do Later (Nice to Have)
4. Minimize custom CSS usage
5. Standardize logging (remove print statements)
6. Performance profiling

### Don't Do (Already Fixed)
- ✅ Navigation state sync
- ✅ Removed blocking st.rerun() calls
- ✅ Using st.checkbox instead of st.toggle
