"""Stable token names and values; no model output is interpolated here."""

DESIGN_SYSTEM_VERSION = "2.0"

TOKENS = {
    "font_body": "system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
    "font_mono": "ui-monospace,SFMono-Regular,monospace", "font_weight_regular": "400",
    "font_weight_medium": "600", "font_weight_bold": "700", "font_size_body": "1rem",
    "font_size_small": ".875rem", "font_size_title": "clamp(1.55rem,4vw,2.35rem)",
    "font_size_heading": "clamp(1.2rem,2.5vw,1.65rem)", "line_height_body": "1.65",
    "space_page": "clamp(0.75rem,3vw,1.5rem)", "space_card": "clamp(1rem,3vw,1.625rem)",
    "space_1": ".25rem", "space_2": ".5rem", "space_3": ".75rem", "space_4": "1rem",
    "radius_card": "0.875rem", "radius_control": "0.5rem", "radius_pill": "999px",
    "shadow_card": "0 4px 18px #17324b16", "content_max": "60rem", "density": "1",
    "focus_width": "3px", "touch_min": "44px", "state_success": "#147a4b", "state_error": "#b42318",
    "state_warning": "#a25a16", "grid_columns": "12", "safe_area": "clamp(1rem,2.5vw,2rem)",
    "density_compact": ".84", "density_comfortable": "1", "density_spacious": "1.16",
    "radius_panel": "1.25rem", "shadow_floating": "0 18px 48px #17324b20",
    "page_header_height": "3rem", "page_footer_height": "3.5rem",
}

__all__ = ["DESIGN_SYSTEM_VERSION", "TOKENS"]
