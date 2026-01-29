"""
Audit Export Component - Export audit logs to CSV/JSON.

Reference: LLD 04 Section 2.5
Milestone 8: Task 8.3
"""
import streamlit as st
import pandas as pd
import json
from typing import List, Dict
from datetime import datetime
import io


def render(logs: List[Dict]) -> None:
    """
    Render export options and handle export generation.

    Args:
        logs: List of log entries to export
    """
    st.markdown("### 📥 Export Options")

    # Check if export dialog should be shown
    if st.session_state.get('show_export_dialog', False):
        _render_export_dialog(logs)
    else:
        _render_export_summary()


def _render_export_dialog(logs: List[Dict]) -> None:
    """
    Render export generation dialog.

    Args:
        logs: List of log entries to export
    """
    export_format = st.session_state.get('export_format', 'CSV')

    st.markdown(f"#### Generate {export_format} Export")

    col1, col2 = st.columns(2)

    with col1:
        format_option = st.selectbox(
            "Export Format",
            options=['CSV', 'JSON', 'Excel'],
            index=['CSV', 'JSON', 'Excel'].index(export_format) if export_format in ['CSV', 'JSON', 'Excel'] else 0,
            key='export_format_select',
        )

    with col2:
        field_option = st.selectbox(
            "Fields",
            options=['Essential', 'All'],
            index=0,
            key='export_fields',
        )

    # Preview
    st.markdown("**Preview** (first 5 entries)")
    if logs:
        preview_logs = logs[:5]
        if field_option == 'Essential':
            preview_df = pd.DataFrame([
                {
                    'Timestamp': log.get('timestamp', 'N/A'),
                    'Decision': log.get('decision', 'N/A'),
                    'Agent': log.get('agent_id', 'N/A'),
                    'Tool': log.get('tool_name', 'N/A'),
                    'Request ID': log.get('request_id', 'N/A'),
                }
                for log in preview_logs
            ])
        else:
            preview_df = pd.DataFrame(preview_logs)

        st.dataframe(preview_df, use_container_width=True)
    else:
        st.info("No logs to export")

    # Action buttons
    col_btn1, col_btn2, col_spacer = st.columns([1, 1, 3])

    with col_btn1:
        if st.button("📥 Generate Export", use_container_width=True, type="primary"):
            _generate_export(logs, format_option, field_option)

    with col_btn2:
        def _close_export_dialog():
            st.session_state.show_export_dialog = False
        
        st.button(
            "❌ Cancel",
            use_container_width=True,
            on_click=_close_export_dialog,
            key="export_cancel_btn"
        )


def _generate_export(logs: List[Dict], format_option: str, field_option: str) -> None:
    """
    Generate export file and provide download.

    Args:
        logs: List of log entries
        format_option: Export format (CSV, JSON, Excel)
        field_option: Field selection (Essential, All)
    """
    if not logs:
        st.warning("No logs to export")
        return

    # Prepare data
    if field_option == 'Essential':
        export_data = [
            {
                'Timestamp': log.get('timestamp', 'N/A'),
                'Decision': log.get('decision', 'N/A'),
                'Agent': log.get('agent_id', 'N/A'),
                'Tool': log.get('tool_name', 'N/A'),
                'Request ID': log.get('request_id', 'N/A'),
                'Session ID': log.get('session_id', ''),
                'Threat Type': log.get('threat_type', ''),
                'Reason': log.get('reason', ''),
            }
            for log in logs
        ]
    else:
        export_data = logs

    # Generate filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"audit-log-{timestamp}"

    # Generate export based on format
    if format_option == 'CSV':
        df = pd.DataFrame(export_data)
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_data = csv_buffer.getvalue()

        st.download_button(
            label="⬇️ Download CSV",
            data=csv_data,
            file_name=f"{filename}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.success(f"✓ CSV export generated: {filename}.csv")

    elif format_option == 'JSON':
        json_data = json.dumps(export_data, indent=2)

        st.download_button(
            label="⬇️ Download JSON",
            data=json_data,
            file_name=f"{filename}.json",
            mime="application/json",
            use_container_width=True,
        )
        st.success(f"✓ JSON export generated: {filename}.json")

    elif format_option == 'Excel':
        df = pd.DataFrame(export_data)
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Audit Log')
        excel_data = excel_buffer.getvalue()

        st.download_button(
            label="⬇️ Download Excel",
            data=excel_data,
            file_name=f"{filename}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        st.success(f"✓ Excel export generated: {filename}.xlsx")

    # Add to recent exports
    if 'recent_exports' not in st.session_state:
        st.session_state.recent_exports = []

    st.session_state.recent_exports.insert(0, {
        'filename': f"{filename}.{format_option.lower()}",
        'format': format_option,
        'timestamp': datetime.now().isoformat(),
        'size': len(export_data),
    })

    # Keep only last 5 exports
    st.session_state.recent_exports = st.session_state.recent_exports[:5]


def _render_export_summary() -> None:
    """Render recent exports summary."""
    if 'recent_exports' not in st.session_state or not st.session_state.recent_exports:
        st.info("No recent exports. Use the 'Export CSV' or 'Export JSON' buttons above to generate exports.")
        return

    st.markdown("**Recent Exports:**")

    for export in st.session_state.recent_exports:
        filename = export.get('filename', 'N/A')
        format_type = export.get('format', 'N/A')
        timestamp = export.get('timestamp', 'N/A')
        size = export.get('size', 0)

        try:
            dt = datetime.fromisoformat(timestamp)
            time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            time_str = timestamp

        st.markdown(f"• `{filename}` ({format_type}, {size} entries) - {time_str}")
