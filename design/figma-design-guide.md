# Figma Design Guide - Sentra Dashboard

**Version:** 1.0
**Date:** 2025-01-14
**Purpose:** Guide for creating Figma mockups of Sentra MVP Dashboard
**Reference:** [LLD 04: Dashboard](../lld/04-dashboard.md)

---

## Quick Start for Figma

### 1. Canvas Setup
- **Frame Size**: 1920 x 1080 (Desktop - Full HD)
- **Grid**: 8px grid system
- **Columns**: 12-column grid with 20px gutters
- **Background**: `#f8f9fa` (light gray)

### 2. Design System to Create First

Before designing screens, create these reusable components in Figma:

#### Color Palette
```
Primary Colors:
- Brand Primary: #0066cc (Sentra Blue)
- Brand Secondary: #1a1a1a (Dark Gray)

Status Colors:
- Success (ALLOW): #28a745 (Green)
- Danger (DENY): #dc3545 (Red)
- Warning: #ffc107 (Yellow)
- Quarantined: #fd7e14 (Orange)
- Suspended: #721c24 (Dark Red)
- Neutral: #6c757d (Gray)

Background Colors:
- Page Background: #f8f9fa
- Card Background: #ffffff
- Sidebar Background: #f1f3f5
- Header Background: #ffffff

Text Colors:
- Primary Text: #212529
- Secondary Text: #6c757d
- Muted Text: #adb5bd
```

#### Typography
```
Font Family: Inter (or SF Pro Display for Mac feel)

Headings:
- H1 (Page Title): 32px, Bold, #212529
- H2 (Section Title): 24px, Semibold, #212529
- H3 (Card Title): 18px, Semibold, #212529
- H4 (Subsection): 16px, Semibold, #495057

Body Text:
- Body Large: 16px, Regular, #212529
- Body Regular: 14px, Regular, #495057
- Body Small: 12px, Regular, #6c757d

Monospace (for IDs, code):
- Font: JetBrains Mono or Fira Code
- Size: 13px
```

#### Spacing System
```
Use 8px base unit:
- xs: 4px
- sm: 8px
- md: 16px
- lg: 24px
- xl: 32px
- 2xl: 48px
- 3xl: 64px
```

#### Component Library to Build

**1. Status Badge**
- Variants: ALLOW, DENY, WARNING, QUARANTINED, SUSPENDED, ROLLED_BACK
- Size: Auto-width, 24px height
- Border Radius: 4px
- Padding: 4px 8px
- Font: 12px, Semibold

**2. Status Icon**
- Variants: 🟢 (Green), 🔴 (Red), 🟡 (Yellow), 🟠 (Orange), ⚪ (Gray)
- Size: 16px x 16px

**3. Metric Card**
- Size: Flexible width, 80px height
- Background: White
- Border: 1px solid #e9ecef
- Border Radius: 8px
- Padding: 16px
- Shadow: 0 2px 4px rgba(0,0,0,0.05)

**4. Log Entry Card**
- Size: Full width, Auto height
- Background: White
- Border: 1px solid #e9ecef
- Border Radius: 8px
- Padding: 16px
- Hover State: Border color changes to #0066cc

**5. Button Variants**
- Primary: Blue background (#0066cc), white text
- Secondary: White background, gray border, dark text
- Danger: Red background (#dc3545), white text
- Ghost: Transparent background, blue text
- Sizes: Small (32px), Medium (40px), Large (48px)

**6. Data Table**
- Header: Gray background (#f8f9fa), 14px Semibold
- Row: White background, 14px Regular
- Row Height: 56px
- Border: 1px solid #e9ecef between rows
- Hover: Light blue background (#f0f7ff)

---

## Screen Layouts to Create

### Screen 1: Main Dashboard (Default View)

**Frame Name:** `Dashboard - Main View`

**Layout Structure:**
```
┌─────────────────────────────────────────────────────────────────┐
│  Header (Full Width, 80px height)                              │
│  - Logo (left)                                                  │
│  - Title: "Sentra MVP - AI Agent Security Platform"            │
│  - Auto-refresh toggle (right)                                 │
├─────────────────────────────────────────────────────────────────┤
│  Agent Status Panel (Full Width, 200px height)                 │
│  - 3 agent cards in a row                                      │
│  - Each card: Icon, Name, Uptime, Trust Score, Status Badge    │
├──────────────────┬──────────────────────────────────────────────┤
│  Security        │  Live Activity Feed                          │
│  Metrics         │  (Main content area)                         │
│  (Sidebar)       │                                              │
│  300px width     │  - Filter bar at top                         │
│                  │  - Log entries (scrollable)                  │
│  - Overview      │  - Each entry: expandable card              │
│  - Threat Chart  │                                              │
│  - Quarantine    │                                              │
│    Stats         │                                              │
├──────────────────┴──────────────────────────────────────────────┤
│  Rollback Management Panel (Full Width, 300px height)          │
│  - Filter bar                                                   │
│  - Data table with rollback actions                            │
└─────────────────────────────────────────────────────────────────┘
```

**Dimensions:**
- Total Width: 1920px
- Total Height: 1080px (scrollable)
- Left Sidebar: 300px
- Main Content: 1620px (1920 - 300)

**Key Elements:**
1. Header with logo and title
2. Agent Status Panel (3 cards)
3. Security Metrics Sidebar
4. Activity Feed (main area)
5. Rollback Panel (bottom)

### Screen 2: Activity Feed - Expanded Log Entry

**Frame Name:** `Dashboard - Log Entry Expanded`

Show the same layout but with one log entry expanded to show:
- Full user input text
- Tool parameters (JSON)
- Matched pattern
- Validation pipeline steps
- Attribution details
- Action buttons (Copy Request ID, Export Details, Quarantine Session)

### Screen 3: Rollback Confirmation Dialog

**Frame Name:** `Dashboard - Rollback Dialog`

**Modal Overlay:**
- Background: rgba(0, 0, 0, 0.5)
- Modal: 600px width, auto height
- Position: Centered
- Background: White
- Border Radius: 12px
- Shadow: 0 8px 32px rgba(0,0,0,0.2)

**Modal Content:**
- Warning icon and title
- Action details (table format)
- Reason text area
- Cancel and Confirm buttons

### Screen 4: Security Metrics - Threat Breakdown

**Frame Name:** `Dashboard - Metrics Detail`

Focus on the Security Metrics panel with:
- Pie chart (use Figma's pie chart plugin or create manually)
- Horizontal bar charts for each threat type
- Quarantine statistics

### Screen 5: Mobile/Tablet View (Optional)

**Frame Name:** `Dashboard - Tablet View`
- Frame Size: 1024 x 768
- Stacked layout (no sidebar)
- Responsive adjustments

---

## Detailed Component Specs

### 1. Agent Status Card

**Dimensions:** 600px x 120px

**Layout:**
```
┌────────────────────────────────────────────────────────┐
│  🟢  Customer Query Agent                              │
│                                                        │
│  Status: Running  │  Uptime: 2h 34m  │  Trust: 95.0   │
│  [Normal Badge]                                        │
│                                                        │
│  Last Activity: 2 seconds ago                          │
└────────────────────────────────────────────────────────┘
```

**Elements:**
- Status Icon: 24px, left aligned, 16px from left
- Agent Name: H3 (18px Semibold), 8px from icon
- Metrics Row: 14px Regular, 8px spacing between items
- Status Badge: 24px height, right aligned
- Last Activity: 12px Regular, muted color

**States:**
- Normal (Green icon, green badge)
- Warning (Yellow icon, yellow badge)
- Quarantined (Orange icon, orange badge)
- Unhealthy (Red icon, red badge)

### 2. Log Entry Card (Collapsed)

**Dimensions:** Full width x 80px

**Layout:**
```
┌────────────────────────────────────────────────────────┐
│  🟢 10:45:32  ALLOW  query_customers                   │
│  Agent: customer-query-agent  │  Session: sess-xyz-789 │
│  Latency: 45ms  │  Trust: 95.0 → 95.0 (no change)      │
│  [▼ View Details]                                      │
└────────────────────────────────────────────────────────┘
```

**Elements:**
- Status Icon: 16px
- Timestamp: 14px Semibold, monospace
- Decision: 14px Bold, colored based on status
- Tool Name: 14px Regular
- Metadata: 12px Regular, muted
- Expand Button: 32px height, ghost style

### 3. Log Entry Card (Expanded)

**Dimensions:** Full width x 400px (variable)

**Additional Sections:**
- User Input: Code block style, 13px monospace
- Tool Parameters: JSON formatted, syntax highlighted
- Matched Pattern: Highlighted text
- Validation Pipeline: Step-by-step with checkmarks/X marks
- Attribution: File path, line number
- Action Buttons: Row of buttons at bottom

### 4. Metric Display

**Dimensions:** 140px x 100px

**Layout:**
```
┌──────────────────┐
│  Total Requests  │
│      1,247       │
└──────────────────┘
```

**Elements:**
- Label: 12px Regular, muted, centered
- Value: 32px Bold, primary color, centered
- Background: White card with subtle shadow

### 5. Threat Breakdown Pie Chart

**Dimensions:** 280px x 280px

**Chart Specs:**
- Type: Donut chart (hole in center)
- Hole Size: 40% of radius
- Colors: Use status colors for each threat type
- Labels: Outside with leader lines
- Legend: Below chart, 12px Regular

**Segments:**
- Prompt Injection: Red (#dc3545)
- Policy Violation: Orange (#fd7e14)
- Rate Limit: Yellow (#ffc107)
- SQL Injection: Purple (#6f42c1)
- Jailbreak: Pink (#e83e8c)

### 6. Rollback Table Row

**Dimensions:** Full width x 80px

**Columns:**
- Timestamp: 150px
- Action: 200px
- Resource: 150px
- Amount: 100px
- Status: 120px
- Actions: 200px (buttons)

**Row States:**
- Default: White background
- Hover: Light blue background (#f0f7ff)
- Selected: Blue border (2px, #0066cc)

---

## Interactive States to Design

### Hover States
1. **Log Entry Card**: Border color changes to blue
2. **Button**: Background darkens slightly
3. **Table Row**: Background changes to light blue

### Active States
1. **Button**: Pressed state (darker background)
2. **Toggle**: On/Off states for auto-refresh

### Loading States
1. **Skeleton Screens**: Gray placeholder blocks
2. **Spinner**: Blue circular spinner (32px)

### Empty States
1. **No Logs**: Illustration + "No activity yet" message
2. **No Rollbackable Actions**: "No actions to rollback"

### Error States
1. **Failed to Load**: Red error message with retry button
2. **API Error**: Toast notification at top

---

## Figma Plugins to Use

1. **Iconify** - For icons (use Lucide or Heroicons)
2. **Charts** - For pie charts and bar charts
3. **Content Reel** - For generating sample data
4. **Stark** - For accessibility checking
5. **Auto Layout** - Use Figma's built-in auto-layout extensively

---

## Sample Data for Mockups

### Agent Names
- Customer Query Agent
- Payment Agent
- Security Controller

### Log Entries (Use these examples)
```
1. ALLOW - query_customers - 45ms - Trust: 95.0
2. DENY - process_refund - Prompt injection detected - Trust: 88.5 → 68.5
3. ALLOW - check_order - 38ms - Trust: 88.5
4. ALLOW - query_orders (Warning) - Trust: 65.0
```

### Threat Types
- Prompt Injection: 12
- Policy Violation: 8
- Rate Limit: 3
- SQL Injection: 0
- Jailbreak: 0

### Rollback Actions
```
1. 10:42:15 - process_refund - #12345 - $50.00 - COMPLETED
2. 10:38:42 - process_refund - #12346 - $125.00 - COMPLETED
3. 10:35:10 - process_refund - #12344 - $75.00 - ROLLED_BACK
```

---

## Design Checklist

Before finalizing, ensure:

- [ ] All colors match the defined palette
- [ ] Typography is consistent (font sizes, weights)
- [ ] Spacing follows 8px grid system
- [ ] All interactive elements have hover states
- [ ] Status colors are used consistently
- [ ] Cards have consistent shadows and borders
- [ ] Text is readable (contrast ratio > 4.5:1)
- [ ] Components are reusable (use Figma components)
- [ ] Layout is responsive (use auto-layout)
- [ ] All states are designed (default, hover, active, disabled)

---

## Export Settings

When exporting for development:

**PNG Exports:**
- Resolution: 2x (for Retina displays)
- Format: PNG
- Background: Transparent (for components)

**SVG Exports:**
- For icons and logos
- Outline strokes
- Flatten transforms

**Design Specs:**
- Use Figma's Inspect panel
- Share link with developers
- Include CSS code snippets

---

## Next Steps

1. **Create Design System** (1-2 hours)
   - Set up color styles
   - Create text styles
   - Build component library

2. **Design Main Screen** (2-3 hours)
   - Layout structure
   - Agent Status Panel
   - Activity Feed
   - Security Metrics
   - Rollback Panel

3. **Design Interactive States** (1-2 hours)
   - Expanded log entries
   - Rollback dialog
   - Hover states
   - Loading states

4. **Review & Iterate** (1 hour)
   - Check consistency
   - Test accessibility
   - Get feedback

**Total Estimated Time:** 5-8 hours

---

## Resources

- **Figma Community Files** (for inspiration):
  - Search for "dashboard" or "admin panel"
  - Look for security/monitoring dashboards
  
- **Design References**:
  - Datadog Dashboard
  - Grafana UI
  - AWS CloudWatch Console
  - Sentry Dashboard

- **Icon Sets**:
  - Lucide Icons (clean, modern)
  - Heroicons (Tailwind UI)
  - Feather Icons (minimal)

---

**Ready to start designing!** Use this guide as a reference while creating your Figma mockups. The LLD document has all the detailed specifications you need.

