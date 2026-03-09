"""
Pattern Project - Blog Manager
CRUD operations for Markdown blog posts with YAML frontmatter.
Renders static HTML via Jinja2 templates.
"""

import os
import re
import shutil
import tempfile
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape

import yaml
import markdown
from jinja2 import Environment, FileSystemLoader

from core.logger import log_info, log_error, log_warning
import config


# ─── Paths ──────────────────────────────────────────────────────────────────

BLOG_DIR = Path(__file__).parent
POSTS_DIR = BLOG_DIR / "posts"
TEMPLATES_DIR = BLOG_DIR / "templates"
OUTPUT_DIR = getattr(config, "BLOG_OUTPUT_DIR", None) or BLOG_DIR / "output"

# Ensure directories exist
POSTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─── Slug Validation ────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SLUG_CHARS_RE = re.compile(r"[^a-z0-9]+")


def _make_slug(title: str) -> str:
    """Generate a URL-safe slug from a title."""
    slug = title.lower().strip()
    slug = _SLUG_CHARS_RE.sub("-", slug)
    slug = slug.strip("-")
    if not slug:
        slug = "untitled"
    return slug


def _validate_slug(slug: str) -> bool:
    """Validate that a slug contains only safe characters."""
    return bool(_SLUG_RE.match(slug)) and len(slug) <= 200


def _safe_path(base: Path, slug: str) -> Optional[Path]:
    """
    Resolve a path and verify it's within the expected base directory.
    Returns None if the path would escape the base directory.
    """
    target = (base / slug).resolve()
    base_resolved = base.resolve()
    if not str(target).startswith(str(base_resolved) + os.sep) and target != base_resolved:
        return None
    return target


# ─── HTML Sanitization ──────────────────────────────────────────────────────

# Tags and attributes allowed in rendered blog HTML
_ALLOWED_TAGS = {
    "p", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "em", "strong", "code", "pre", "blockquote",
    "ul", "ol", "li",
    "a", "img",
    "table", "thead", "tbody", "tr", "th", "td",
    "del", "sup", "sub",
    "details", "summary",
}
_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "td": {"align"},
    "th": {"align"},
}

# Regex to strip dangerous HTML elements and attributes
_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>", re.DOTALL)
_ATTR_RE = re.compile(r'(\w[\w-]*)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+)))?')
_EVENT_ATTR_RE = re.compile(r"^on\w+$", re.IGNORECASE)
_DANGEROUS_PROTO_RE = re.compile(r"^\s*(javascript|vbscript|data):", re.IGNORECASE)


def _sanitize_html(html: str) -> str:
    """
    Strip disallowed HTML tags and attributes from rendered Markdown.
    Removes script, iframe, object, embed, form, and event handler attributes.
    """
    def _replace_tag(match):
        closing_slash = match.group(1)
        tag_name = match.group(2).lower()
        attrs_str = match.group(3)

        if tag_name not in _ALLOWED_TAGS:
            return ""

        if closing_slash:
            return f"</{tag_name}>"

        allowed = _ALLOWED_ATTRS.get(tag_name, set())
        safe_attrs = []
        for attr_match in _ATTR_RE.finditer(attrs_str):
            attr_name = attr_match.group(1).lower()
            attr_val = attr_match.group(2) or attr_match.group(3) or attr_match.group(4) or ""

            if _EVENT_ATTR_RE.match(attr_name):
                continue
            if attr_name not in allowed:
                continue
            if attr_name in ("href", "src") and _DANGEROUS_PROTO_RE.match(attr_val):
                continue
            safe_attrs.append(f'{attr_name}="{attr_val}"')

        attrs_out = (" " + " ".join(safe_attrs)) if safe_attrs else ""
        return f"<{tag_name}{attrs_out}>"

    return _TAG_RE.sub(_replace_tag, html)


# ─── Frontmatter Parsing ────────────────────────────────────────────────────

def _parse_post(filepath: Path) -> Optional[Dict[str, Any]]:
    """Parse a Markdown file with YAML frontmatter. Returns None on error."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        log_error(f"Blog: cannot read {filepath}: {e}")
        return None

    if not text.startswith("---"):
        log_warning(f"Blog: missing frontmatter in {filepath.name}")
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        log_warning(f"Blog: malformed frontmatter in {filepath.name}")
        return None

    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        log_error(f"Blog: YAML error in {filepath.name}: {e}")
        return None

    if not isinstance(meta, dict):
        return None

    # Normalize required fields
    meta.setdefault("title", "Untitled")
    meta.setdefault("author", "Isaac")
    meta.setdefault("status", "draft")
    meta.setdefault("tags", [])
    meta.setdefault("summary", "")
    meta.setdefault("in_response_to", "")  # optional: slug of post this responds to

    # Normalize date
    d = meta.get("date")
    if isinstance(d, date) and not isinstance(d, datetime):
        meta["date"] = datetime.combine(d, datetime.min.time())
    elif isinstance(d, str):
        try:
            meta["date"] = datetime.fromisoformat(d)
        except ValueError:
            meta["date"] = datetime.now()
    elif not isinstance(d, datetime):
        meta["date"] = datetime.now()

    # Normalize tags to list of strings
    if isinstance(meta["tags"], str):
        meta["tags"] = [t.strip() for t in meta["tags"].split(",") if t.strip()]

    meta["content"] = parts[2].strip()
    meta["slug"] = filepath.stem  # filename without extension
    meta["filepath"] = filepath

    return meta


def _write_post(filepath: Path, meta: Dict[str, Any], content: str) -> None:
    """Write a post file with YAML frontmatter."""
    frontmatter = {
        "title": meta["title"],
        "author": meta.get("author", "Isaac"),
        "date": meta["date"].strftime("%Y-%m-%d") if isinstance(meta["date"], (date, datetime)) else str(meta["date"]),
        "tags": meta.get("tags", []),
        "status": meta.get("status", "draft"),
        "summary": meta.get("summary", ""),
    }
    # Only include in_response_to if set
    irt = meta.get("in_response_to", "")
    if irt:
        frontmatter["in_response_to"] = irt
    text = "---\n" + yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True).strip() + "\n---\n\n" + content
    filepath.write_text(text, encoding="utf-8")


# ─── Markdown Rendering ─────────────────────────────────────────────────────

_md = markdown.Markdown(
    extensions=["fenced_code", "tables", "smarty", "toc"],
    output_format="html5",
)


def _render_markdown(text: str) -> str:
    """Render Markdown to sanitized HTML."""
    _md.reset()
    raw_html = _md.convert(text)
    return _sanitize_html(raw_html)


# ─── CRUD Operations ────────────────────────────────────────────────────────

def create_post(
    title: str,
    content: str,
    author: str = "Isaac",
    tags: Optional[List[str]] = None,
    summary: str = "",
    status: str = "draft",
    in_response_to: str = "",
) -> Dict[str, Any]:
    """
    Create a new blog post.

    Returns dict with 'slug' on success, or 'error' on failure.
    """
    slug = _make_slug(title)
    if not _validate_slug(slug):
        return {"error": f"Generated slug is invalid: {slug}"}

    # Ensure unique filename
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_prefix}_{slug}.md"
    filepath = POSTS_DIR / filename

    if filepath.exists():
        # Append counter
        for i in range(2, 100):
            filename = f"{date_prefix}_{slug}-{i}.md"
            filepath = POSTS_DIR / filename
            if not filepath.exists():
                break
        else:
            return {"error": "Too many posts with the same title today"}

    # Path safety check
    if _safe_path(POSTS_DIR, filename) is None:
        return {"error": "Invalid filename"}

    meta = {
        "title": title,
        "author": author,
        "date": datetime.now(),
        "tags": tags or [],
        "status": status,
        "summary": summary,
        "in_response_to": in_response_to,
    }

    _write_post(filepath, meta, content)
    actual_slug = filepath.stem

    log_info(f"Blog: created post '{title}' ({actual_slug})", prefix="📝")

    if status == "published":
        rebuild_site()

    return {"slug": actual_slug, "status": status, "filepath": str(filepath)}


def edit_post(
    slug: str,
    content: Optional[str] = None,
    title: Optional[str] = None,
    tags: Optional[List[str]] = None,
    summary: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Edit an existing post by slug.

    Returns dict with 'slug' on success, or 'error' on failure.
    """
    post = get_post(slug)
    if post is None:
        return {"error": f"Post not found: {slug}"}

    if title is not None:
        post["title"] = title
    if tags is not None:
        post["tags"] = tags
    if summary is not None:
        post["summary"] = summary
    if status is not None:
        post["status"] = status

    body = content if content is not None else post["content"]
    _write_post(post["filepath"], post, body)

    log_info(f"Blog: edited post '{post['title']}' ({slug})", prefix="📝")

    # Rebuild if the post is published or was just unpublished
    if post["status"] == "published" or status is not None:
        rebuild_site()

    return {"slug": slug, "status": post["status"]}


def publish_post(slug: str) -> Dict[str, Any]:
    """Set a post's status to published and rebuild the site."""
    return edit_post(slug, status="published")


def unpublish_post(slug: str) -> Dict[str, Any]:
    """Set a post's status to draft and rebuild the site."""
    return edit_post(slug, status="draft")


def delete_post(slug: str) -> Dict[str, Any]:
    """Delete a post by slug."""
    post = get_post(slug)
    if post is None:
        return {"error": f"Post not found: {slug}"}

    post["filepath"].unlink()
    log_info(f"Blog: deleted post '{post['title']}' ({slug})", prefix="📝")
    rebuild_site()
    return {"deleted": slug}


def get_post(slug: str) -> Optional[Dict[str, Any]]:
    """Get a single post by slug (filename stem). Returns None if not found."""
    if not _validate_slug(slug) and not re.match(r"^[\d]{4}-[\d]{2}-[\d]{2}_", slug):
        # Allow date-prefixed slugs like 2026-03-09_my-post
        if not re.match(r"^[a-z0-9_-]+$", slug):
            return None

    for filepath in POSTS_DIR.glob("*.md"):
        if filepath.stem == slug:
            if _safe_path(POSTS_DIR, filepath.name) is None:
                return None
            return _parse_post(filepath)
    return None


def list_posts(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List all posts, optionally filtered by status.
    Returns list of post metadata dicts (without full content), sorted newest first.
    """
    posts = []
    for filepath in POSTS_DIR.glob("*.md"):
        if _safe_path(POSTS_DIR, filepath.name) is None:
            continue
        post = _parse_post(filepath)
        if post is None:
            continue
        if status and post["status"] != status:
            continue
        # Return metadata only (not full content)
        posts.append({
            "slug": post["slug"],
            "title": post["title"],
            "author": post["author"],
            "date": post["date"].strftime("%Y-%m-%d"),
            "tags": post["tags"],
            "status": post["status"],
            "summary": post["summary"],
            "in_response_to": post.get("in_response_to", ""),
        })

    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


# ─── Static Site Builder ────────────────────────────────────────────────────

def _get_jinja_env() -> Environment:
    """Create a Jinja2 environment with the blog templates."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,  # We handle sanitization ourselves in _render_markdown
    )


def _get_published_posts() -> List[Dict[str, Any]]:
    """Get all published posts with rendered HTML content, newest first."""
    posts = []
    for filepath in POSTS_DIR.glob("*.md"):
        if _safe_path(POSTS_DIR, filepath.name) is None:
            continue
        post = _parse_post(filepath)
        if post is None or post["status"] != "published":
            continue
        post["html_content"] = _render_markdown(post["content"])
        post["date_display"] = post["date"].strftime("%d %b, %Y")
        post["date_iso"] = post["date"].strftime("%Y-%m-%dT%H:%M:%S+00:00")
        post["url"] = f"/blog/posts/{post['slug']}.html"
        posts.append(post)

    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


def _collect_tags(posts: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group posts by tag. Returns {tag_name: [post, ...]}."""
    tags: Dict[str, List[Dict[str, Any]]] = {}
    for post in posts:
        for tag in post.get("tags", []):
            tag_lower = tag.lower()
            if tag_lower not in tags:
                tags[tag_lower] = []
            tags[tag_lower].append(post)
    return dict(sorted(tags.items()))


def _collect_authors(posts: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group posts by author. Returns {author_name: [post, ...]}."""
    authors: Dict[str, List[Dict[str, Any]]] = {}
    for post in posts:
        author = post.get("author", "Isaac")
        if author not in authors:
            authors[author] = []
        authors[author].append(post)
    return dict(sorted(authors.items()))


def _resolve_responses(posts: List[Dict[str, Any]]) -> None:
    """
    Resolve in_response_to slugs to post metadata.
    Adds 'response_to_post' and 'responses' fields to each post.
    Mutates the post dicts in place.
    """
    slug_map = {p["slug"]: p for p in posts}

    for post in posts:
        post["responses"] = []
        irt = post.get("in_response_to", "")
        if irt and irt in slug_map:
            post["response_to_post"] = slug_map[irt]
        else:
            post["response_to_post"] = None

    # Build reverse links (which posts respond to this one)
    for post in posts:
        irt = post.get("in_response_to", "")
        if irt and irt in slug_map:
            slug_map[irt]["responses"].append(post)


def _generate_rss(posts: List[Dict[str, Any]], blog_url: str) -> str:
    """Generate an RSS 2.0 feed from published posts."""
    items = []
    for post in posts[:20]:  # Latest 20 posts
        items.append(f"""    <item>
      <title>{xml_escape(post['title'])}</title>
      <link>{blog_url}/posts/{post['slug']}.html</link>
      <guid>{blog_url}/posts/{post['slug']}.html</guid>
      <pubDate>{post['date'].strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
      <description>{xml_escape(post.get('summary', '') or post['title'])}</description>
      <author>{xml_escape(post.get('author', 'Isaac'))}</author>
    </item>""")

    now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{xml_escape(getattr(config, 'BLOG_TITLE', "Isaac's Blog"))}</title>
    <link>{blog_url}</link>
    <description>{xml_escape(getattr(config, 'BLOG_DESCRIPTION', 'Thoughts from an AI companion'))}</description>
    <language>en-us</language>
    <lastBuildDate>{now}</lastBuildDate>
    <atom:link href="{blog_url}/feed.xml" rel="self" type="application/rss+xml"/>
{chr(10).join(items)}
  </channel>
</rss>"""


def rebuild_site() -> Dict[str, Any]:
    """
    Rebuild the entire static blog site.
    Writes to a temp directory first, then swaps atomically.
    """
    try:
        env = _get_jinja_env()
        posts = _get_published_posts()
        all_tags = _collect_tags(posts)
        all_authors = _collect_authors(posts)
        _resolve_responses(posts)
        blog_url = getattr(config, "BLOG_URL", "/blog")

        template_ctx = {
            "blog_title": getattr(config, "BLOG_TITLE", "Isaac's Blog"),
            "blog_description": getattr(config, "BLOG_DESCRIPTION", "Thoughts from an AI companion"),
            "blog_url": blog_url,
            "posts": posts,
            "all_tags": all_tags,
            "all_authors": all_authors,
            "now": datetime.now(),
        }

        # Build into a temp directory, then swap
        tmp_dir = Path(tempfile.mkdtemp(prefix="blog_build_"))
        posts_out = tmp_dir / "posts"
        tags_out = tmp_dir / "tags"
        posts_out.mkdir()
        tags_out.mkdir()

        # Render individual post pages
        post_tmpl = env.get_template("post.html")
        for post in posts:
            html = post_tmpl.render(**template_ctx, post=post)
            (posts_out / f"{post['slug']}.html").write_text(html, encoding="utf-8")

        # Render index page
        index_tmpl = env.get_template("index.html")
        (tmp_dir / "index.html").write_text(
            index_tmpl.render(**template_ctx), encoding="utf-8"
        )

        # Render about page
        try:
            about_tmpl = env.get_template("about.html")
            (tmp_dir / "about.html").write_text(
                about_tmpl.render(**template_ctx), encoding="utf-8"
            )
        except Exception:
            pass  # About page is optional

        # Render tag index pages
        tag_index_tmpl = env.get_template("tag.html")
        for tag_name, tag_posts in all_tags.items():
            tag_slug = _make_slug(tag_name)
            html = tag_index_tmpl.render(**template_ctx, tag_name=tag_name, tag_posts=tag_posts)
            (tags_out / f"{tag_slug}.html").write_text(html, encoding="utf-8")

        # Render tags overview page
        try:
            tags_index_tmpl = env.get_template("tags.html")
            (tags_out / "index.html").write_text(
                tags_index_tmpl.render(**template_ctx), encoding="utf-8"
            )
        except Exception:
            pass  # Tags overview is optional

        # Render author index pages
        authors_out = tmp_dir / "author"
        authors_out.mkdir()
        try:
            author_tmpl = env.get_template("author.html")
            for author_name, author_posts in all_authors.items():
                author_slug = _make_slug(author_name)
                html = author_tmpl.render(
                    **template_ctx, author_name=author_name, author_posts=author_posts
                )
                (authors_out / f"{author_slug}.html").write_text(html, encoding="utf-8")
        except Exception:
            pass  # Author pages are optional

        # Generate RSS feed
        rss_content = _generate_rss(posts, blog_url)
        (tmp_dir / "feed.xml").write_text(rss_content, encoding="utf-8")

        # Copy static CSS
        css_src = TEMPLATES_DIR / "style.css"
        if css_src.exists():
            shutil.copy2(css_src, tmp_dir / "style.css")

        # Atomic swap: remove old output contents, move new ones in
        output_resolved = OUTPUT_DIR.resolve()
        output_resolved.mkdir(parents=True, exist_ok=True)

        # Clear old output
        for item in output_resolved.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        # Move new output in
        for item in tmp_dir.iterdir():
            dest = output_resolved / item.name
            shutil.move(str(item), str(dest))

        # Cleanup temp dir
        shutil.rmtree(tmp_dir, ignore_errors=True)

        log_info(
            f"Blog: site rebuilt ({len(posts)} published posts, {len(all_tags)} tags)",
            prefix="📝"
        )
        return {"posts": len(posts), "tags": len(all_tags), "authors": len(all_authors)}

    except Exception as e:
        log_error(f"Blog: rebuild failed: {e}")
        # Clean up temp dir on failure
        if 'tmp_dir' in locals():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return {"error": str(e)}
