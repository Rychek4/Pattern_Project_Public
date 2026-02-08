"""
Pattern Project - Page Reader for Browser Agent

Converts a Playwright page into a structured text representation
that the delegate sub-agent (Haiku) can understand and act on.

The output has two sections:
1. Interactive Element Map — numbered list of clickable/typeable elements
2. Visible Text — trimmed page content for context

The element map uses Playwright's accessibility tree to find actionable
elements, assigns each a numeric ID, and presents them with their role,
name/label, and current value. The delegate references elements by ID
in click() and type() calls.
"""

from typing import Any, Dict, List, Optional, Tuple


# Maximum characters of visible text to include in page read output.
# Pages like news articles can be enormous; we truncate to keep the
# delegate's context manageable.
PAGE_TEXT_MAX_CHARS = 8000

# Snapshot cache — avoids re-snapshotting the accessibility tree when
# get_element_handle() is called immediately after read_page() on the
# same page. Cleared on navigation or when URL changes.
_snapshot_cache: Dict[str, Any] = {
    "url": None,
    "interactive_elements": [],
}

# Roles considered "interactive" — elements the agent can click or type into
INTERACTIVE_ROLES = {
    # Clickable
    "link", "button", "menuitem", "menuitemcheckbox", "menuitemradio",
    "tab", "option", "switch", "treeitem",
    # Typeable
    "textbox", "searchbox", "combobox", "spinbutton",
    # Selectable
    "checkbox", "radio",
}

# Roles that are typeable (agent can use type() on these)
TYPEABLE_ROLES = {"textbox", "searchbox", "combobox", "spinbutton"}


def _flatten_tree(node: Dict[str, Any], depth: int = 0) -> List[Dict[str, Any]]:
    """
    Recursively flatten the accessibility tree into a list of nodes.
    Each node gets a 'depth' field for indentation context.
    """
    result = []
    node_copy = dict(node)
    node_copy["depth"] = depth
    result.append(node_copy)

    for child in node.get("children", []):
        result.extend(_flatten_tree(child, depth + 1))

    return result


def _format_element(element_id: int, node: Dict[str, Any]) -> str:
    """
    Format a single interactive element as a compact readable line.

    Examples:
        [1] link "Home"
        [2] button "Submit"
        [3] input "Username" value=""
        [4] input "Password"
        [5] checkbox "Remember me" [checked]
    """
    role = node.get("role", "unknown")
    name = node.get("name", "").strip()
    value = node.get("value", "")
    checked = node.get("checked")
    description = node.get("description", "")

    # Short lowercase labels — compact but unambiguous
    role_labels = {
        "link": "link",
        "button": "btn",
        "textbox": "input",
        "searchbox": "search",
        "combobox": "dropdown",
        "spinbutton": "number",
        "checkbox": "checkbox",
        "radio": "radio",
        "menuitem": "menu",
        "menuitemcheckbox": "menuchk",
        "menuitemradio": "menurad",
        "tab": "tab",
        "option": "option",
        "switch": "switch",
        "treeitem": "tree",
    }

    label = role_labels.get(role, role)

    # Build compact display string — no padding
    parts = [f"[{element_id}] {label}"]

    if name:
        parts.append(f'"{name}"')

    # For input fields, show placeholder/value info
    if role in TYPEABLE_ROLES:
        if value:
            parts.append(f'val="{value[:50]}"')
        if description:
            parts.append(f'ph="{description[:50]}"')

    # Checkbox/radio state
    if checked is True:
        parts.append("[x]")
    elif checked is False and role in ("checkbox", "radio"):
        parts.append("[ ]")

    return " ".join(parts)


async def read_page(page, mode: str = "full") -> str:
    """
    Read the current page and return a structured text representation.

    Args:
        page: Playwright Page object
        mode: Read mode — 'full' (elements + text, default),
              'summary' (elements only), or 'text' (text only)

    Returns:
        Formatted string with page info and requested content
    """
    # Validate mode
    if mode not in ("full", "summary", "text"):
        mode = "full"

    # Get page metadata
    title = await page.title()
    url = page.url

    include_elements = mode in ("full", "summary")
    include_text = mode in ("full", "text")

    # Build the accessibility tree (needed for elements or cache)
    interactive_elements = []
    if include_elements:
        try:
            ax_tree = await page.accessibility.snapshot()
        except Exception:
            ax_tree = None

        if ax_tree:
            all_nodes = _flatten_tree(ax_tree)
            for node in all_nodes:
                role = node.get("role", "")
                if role in INTERACTIVE_ROLES:
                    # Skip elements with no name/value — they're usually invisible
                    name = node.get("name", "").strip()
                    value = node.get("value", "")
                    description = node.get("description", "")
                    if name or value or description:
                        interactive_elements.append(node)

        # Cache snapshot for get_element_handle() reuse
        _snapshot_cache["url"] = url
        _snapshot_cache["interactive_elements"] = interactive_elements

    # Get visible text content (skip for summary mode)
    visible_text = ""
    text_truncated = False
    if include_text:
        try:
            visible_text = await page.inner_text("body")
            visible_text = visible_text.strip()
        except Exception:
            visible_text = ""

        if len(visible_text) > PAGE_TEXT_MAX_CHARS:
            visible_text = visible_text[:PAGE_TEXT_MAX_CHARS]
            text_truncated = True

    # Build output
    sections = []

    # Header
    sections.append(f"Page: {title}")
    sections.append(f"URL: {url}")
    sections.append("")

    # Interactive elements
    if include_elements:
        if interactive_elements:
            sections.append(f"Interactive elements ({len(interactive_elements)}):")
            for i, node in enumerate(interactive_elements, 1):
                sections.append(f"  {_format_element(i, node)}")
        else:
            sections.append("Interactive elements: None found")
        sections.append("")

    # Visible text
    if include_text:
        if visible_text:
            sections.append("Visible text:")
            # Collapse excessive whitespace/newlines for readability
            lines = visible_text.split("\n")
            cleaned_lines = []
            blank_count = 0
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    blank_count += 1
                    if blank_count <= 1:
                        cleaned_lines.append("")
                else:
                    blank_count = 0
                    cleaned_lines.append(stripped)

            sections.append("\n".join(cleaned_lines))

            if text_truncated:
                sections.append(f"\n[Text truncated at {PAGE_TEXT_MAX_CHARS} characters]")
        else:
            sections.append("Visible text: (empty page)")

    return "\n".join(sections)


async def get_element_handle(page, element_id: int):
    """
    Get a Playwright locator for an element by its numbered ID from the element map.

    Uses the cached accessibility snapshot from the most recent read_page()
    call when the URL matches (avoids a redundant snapshot). Falls back to
    a fresh snapshot if the cache is stale or missing.

    Args:
        page: Playwright Page object
        element_id: 1-based element ID from the element map

    Returns:
        Tuple of (Locator, node_info_dict) or (None, None) if not found
    """
    # Reuse cached snapshot if URL matches (read_page was just called)
    current_url = page.url
    if (
        _snapshot_cache["url"] == current_url
        and _snapshot_cache["interactive_elements"]
    ):
        interactive_elements = _snapshot_cache["interactive_elements"]
    else:
        # Cache miss — re-snapshot the accessibility tree
        try:
            ax_tree = await page.accessibility.snapshot()
        except Exception:
            return None, None

        if not ax_tree:
            return None, None

        all_nodes = _flatten_tree(ax_tree)
        interactive_elements = []
        for node in all_nodes:
            role = node.get("role", "")
            if role in INTERACTIVE_ROLES:
                name = node.get("name", "").strip()
                value = node.get("value", "")
                description = node.get("description", "")
                if name or value or description:
                    interactive_elements.append(node)

    if element_id < 1 or element_id > len(interactive_elements):
        return None, None

    target = interactive_elements[element_id - 1]
    role = target.get("role", "")
    name = target.get("name", "")

    # Use role-based Playwright locators to find the DOM element
    # This is more robust than CSS selectors
    try:
        element = await _locate_element(page, role, name, target)
        return element, target
    except Exception:
        return None, None


async def _locate_element(
    page, role: str, name: str, node: Dict[str, Any]
) -> Optional[Any]:
    """
    Locate a DOM element using Playwright's get_by_role locator.

    Falls back to text-based and label-based selectors if role matching fails.
    """
    # Map accessibility roles to Playwright's AriaRole values
    role_mapping = {
        "link": "link",
        "button": "button",
        "textbox": "textbox",
        "searchbox": "searchbox",
        "combobox": "combobox",
        "checkbox": "checkbox",
        "radio": "radio",
        "menuitem": "menuitem",
        "tab": "tab",
        "option": "option",
        "switch": "switch",
        "spinbutton": "spinbutton",
        "treeitem": "treeitem",
    }

    pw_role = role_mapping.get(role)

    if pw_role and name:
        # Try exact match first, then substring
        locator = page.get_by_role(pw_role, name=name, exact=True)
        count = await locator.count()
        if count == 1:
            return locator.first

        # Try non-exact (substring) match
        locator = page.get_by_role(pw_role, name=name)
        count = await locator.count()
        if count >= 1:
            return locator.first

    # Fallback: try get_by_text for links/buttons
    if role in ("link", "button") and name:
        locator = page.get_by_text(name, exact=True)
        count = await locator.count()
        if count >= 1:
            return locator.first

    # Fallback: try get_by_label for inputs
    if role in TYPEABLE_ROLES and name:
        locator = page.get_by_label(name)
        count = await locator.count()
        if count >= 1:
            return locator.first

    # Fallback: try get_by_placeholder for inputs
    description = node.get("description", "")
    if role in TYPEABLE_ROLES and description:
        locator = page.get_by_placeholder(description)
        count = await locator.count()
        if count >= 1:
            return locator.first

    return None
