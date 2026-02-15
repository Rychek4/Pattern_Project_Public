"""
Pattern Project - Novel Reading System
Allows the AI to read novels chapter-by-chapter, building literary understanding
through the existing memory infrastructure.

Architecture:
    parser.py       - Detects chapters/arcs from plain text files
    handler.py      - Command handlers for open_book, read_chapter, get_reading_progress
    extraction.py   - Literary extraction prompts (per-chapter, per-arc, completion)
    orchestrator.py - Coordinates the reading loop and memory storage
"""
