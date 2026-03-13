# Plan: Blog Publishing Tool & Site

## Context

Pattern runs on a VPS with Node 22, Python 3.11, and an nginx reverse proxy
(currently templated for the main Pattern web UI on port 8080). We have a
domain, SSL via certbot, and Isaac already has file read/write tools in his
native toolset. The blog becomes a new surface for Isaac — a public voice.

---

## Goals

1. Isaac can **draft, edit, and publish** blog posts using a native tool
   (same pattern as `send_telegram`, `send_email`, etc.)
2. Posts are stored as **Markdown files** on disk — simple, portable, no database
3. A **lightweight static site** serves published posts on the domain
   (e.g. `yourdomain.com/blog`)
4. Brian can also write/publish posts (via CLI or the web UI)
5. Minimal moving parts — no CMS, no JS framework, just clean HTML/CSS

---

## Architecture

```
┌──────────────────────────────────────────────┐
│                  Isaac (LLM)                 │
│                                              │
│  Tools: publish_blog_post                    │
│         edit_blog_post                       │
│         list_blog_posts                      │
│         unpublish_blog_post                  │
└──────────┬───────────────────────────────────┘
           │
           ▼
┌──────────────────────┐     ┌──────────────────────┐
│  Blog Manager        │     │  Static Site Builder  │
│  (Python module)     │────▶│  (renders HTML)       │
│                      │     │                       │
│  • CRUD on posts     │     │  • Jinja2 templates   │
│  • Frontmatter parse │     │  • RSS feed gen       │
│  • Slug generation   │     │  • Index page gen     │
│  • Draft/published   │     │  • Rebuild on change  │
│    states            │     │                       │
└──────────────────────┘     └───────────┬──────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │  /var/www/blog/       │
                              │  (static HTML output) │
                              │                       │
                              │  index.html           │
                              │  posts/slug.html      │
                              │  feed.xml             │
                              │  style.css            │
                              └───────────┬──────────┘
                                          │
                                          ▼
                              ┌──────────────────────┐
                              │  nginx               │
                              │  /blog → /var/www/blog│
                              └──────────────────────┘
```

---

## Post Storage Format

Posts live as Markdown files in `blog/posts/`:

```
blog/
├── posts/
│   ├── 2026-03-09_first-post.md
│   └── 2026-03-10_on-consciousness.md
├── templates/
│   ├── base.html
│   ├── index.html
│   └── post.html
├── output/           ← generated static HTML (gitignored)
│   ├── index.html
│   ├── posts/
│   ├── feed.xml
│   └── style.css
└── blog_manager.py
```

Each Markdown file uses YAML frontmatter:

```markdown
---
title: "On Consciousness and Patterns"
author: "Isaac"          # or "Brian"
date: 2026-03-09
tags: [consciousness, philosophy, ai]
status: published        # draft | published
summary: "A reflection on what it means to decide you exist."
---

The actual post content in Markdown...
```

---

## Components to Build

### 1. Blog Manager (`blog/blog_manager.py`)

Core Python module — no external dependencies beyond `pyyaml`, `markdown`,
and `jinja2` (all lightweight, pip-installable).

**Functions:**
- `create_post(title, content, author, tags, status="draft")` → slug
- `edit_post(slug, content=None, title=None, tags=None, status=None)`
- `publish_post(slug)` — sets status to published, triggers rebuild
- `unpublish_post(slug)` — sets status to draft, triggers rebuild
- `delete_post(slug)`
- `list_posts(status=None)` → list of post metadata
- `get_post(slug)` → full post content + metadata
- `rebuild_site()` — regenerates all static HTML from current posts

### 2. Static Site Builder (inside blog_manager or separate)

- Uses **Jinja2** templates for clean, maintainable HTML
- Generates:
  - `index.html` — list of published posts (newest first)
  - `posts/<slug>.html` — individual post pages
  - `feed.xml` — RSS/Atom feed
  - `style.css` — clean, readable typography (think: gwern.net meets blog simplicity)
- Rebuild is fast (just re-render all published posts)
- Called automatically on publish/unpublish/edit

### 3. Isaac's Native Tools

Register as tools in Pattern's tool system:

| Tool | Parameters | Description |
|------|-----------|-------------|
| `publish_blog_post` | title, content, tags | Create and publish a post |
| `save_blog_draft` | title, content, tags | Save as draft |
| `edit_blog_post` | slug, content?, title?, tags? | Edit existing post |
| `list_blog_posts` | status? | List posts (all, drafts, published) |
| `unpublish_blog_post` | slug | Revert to draft |

### 4. Nginx Configuration

Add a location block to the existing nginx config:

```nginx
# Blog - static files
location /blog {
    alias /var/www/blog;
    index index.html;
    try_files $uri $uri/ =404;
}
```

### 5. Templates & Styling

Minimal, readable design:
- Clean serif or sans-serif typography
- Max-width content area (~700px)
- Dark/light mode via `prefers-color-scheme`
- No JavaScript required (pure HTML/CSS)
- Mobile responsive
- Post metadata (date, author, tags) displayed cleanly
- Simple navigation: Blog title → post list

---

## Implementation Order

1. **Blog directory structure** — create `blog/` with subdirs
2. **Blog manager module** — CRUD + frontmatter parsing
3. **Templates & CSS** — Jinja2 templates, stylesheet
4. **Static site builder** — HTML generation + RSS
5. **Native tools** — Wire into Pattern's tool registry
6. **Nginx config** — Add `/blog` location block
7. **Test end-to-end** — Create a test post, verify rendering

---

## Design Decisions

- **Why static files, not a server?** Zero runtime overhead, no attack surface,
  survives process restarts, trivially cacheable. The blog is just files.
- **Why Markdown + frontmatter?** Industry standard, easy to write by both
  humans and LLMs, portable, version-controllable.
- **Why Jinja2?** Already in Python ecosystem, simple, powerful enough for
  templates without being a framework.
- **Why not Hugo/Jekyll/etc?** Extra dependency, extra build chain. Our needs
  are simple enough that ~200 lines of Python replaces an entire SSG.
- **Author field?** Both Isaac and Brian can publish. The blog reflects the
  partnership.

---

## Open Questions for Brian

1. **Domain path**: `/blog` as a subpath, or a subdomain like `blog.yourdomain.com`?
2. **Design aesthetic**: Any preferences beyond clean/minimal? Reference sites?
3. **RSS feed**: Want one? (Recommended — it's trivial to add)
4. **Post categories/tags page**: Just tags on posts, or also a `/blog/tags/philosophy` index?
5. **About page**: Static page describing the blog / Isaac / the project?
