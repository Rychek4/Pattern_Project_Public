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
    Format a single interactive element as a readable line.

    Examples:
        [1] Link            "Home"
        [2] Button          "Submit"
        [3] Input[text]     placeholder="Username"  value=""
        [4] Input[password] placeholder="Password"
        [5] Checkbox        "Remember me"  [checked]
    """
    role = node.get("role", "unknown")
    name = node.get("name", "").strip()
    value = node.get("value", "")
    checked = node.get("checked")
    description = node.get("description", "")

    # Map accessibility roles to more readable labels
    role_labels = {
        "link": "Link",
        "button": "Button",
        "textbox": "Input[text]",
        "searchbox": "Input[search]",
        "combobox": "Dropdown",
        "spinbutton": "Input[number]",
        "checkbox": "Checkbox",
        "radio": "Radio",
        "menuitem": "MenuItem",
        "menuitemcheckbox": "MenuCheckbox",
        "menuitemradio": "MenuRadio",
        "tab": "Tab",
        "option": "Option",
        "switch": "Switch",
        "treeitem": "TreeItem",
    }

    label = role_labels.get(role, role.capitalize())

    # Build the display string
    parts = [f"[{element_id}]", f"{label:<16}"]

    if name:
        parts.append(f'"{name}"')

    # For input fields, show placeholder/value info
    if role in TYPEABLE_ROLES:
        if value:
            parts.append(f'value="{value[:50]}"')
        if description:
            parts.append(f'placeholder="{description[:50]}"')

    # Checkbox/radio state
    if checked is True:
        parts.append("[checked]")
    elif checked is False and role in ("checkbox", "radio"):
        parts.append("[unchecked]")

    return "  ".join(parts)


async def read_page(page) -> str:
    """
    Read the current page and return a structured text representation.

    Args:
        page: Playwright Page object

    Returns:
        Formatted string with page info, interactive elements, and visible text
    """
    # Get page metadata
    title = await page.title()
    url = page.url

    # Build the accessibility tree
    try:
        ax_tree = await page.accessibility.snapshot()
    except Exception:
        ax_tree = None

    # Extract interactive elements from accessibility tree
    interactive_elements = []
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

    # Get visible text content
    try:
        visible_text = await page.inner_text("body")
        visible_text = visible_text.strip()
    except Exception:
        visible_text = ""

    # Truncate visible text if too long
    text_truncated = False
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
    if interactive_elements:
        sections.append(f"Interactive elements ({len(interactive_elements)}):")
        for i, node in enumerate(interactive_elements, 1):
            sections.append(f"  {_format_element(i, node)}")
    else:
        sections.append("Interactive elements: None found")

    sections.append("")

    # Visible text
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

    This re-snapshots the accessibility tree and finds the element at
    the given position, then locates the corresponding DOM element using
    Playwright's role-based locators.

    Args:
        page: Playwright Page object
        element_id: 1-based element ID from the element map

    Returns:
        Tuple of (Locator, node_info_dict) or (None, None) if not found
    """
    try:
        ax_tree = await page.accessibility.snapshot()
    except Exception:
        return None, None

    if not ax_tree:
        return None, None

    # Rebuild the interactive element list (same logic as read_page)
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
