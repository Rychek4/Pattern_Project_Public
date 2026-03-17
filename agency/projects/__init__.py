"""
Pattern Project - Projects
Structured multi-step plans with progress tracking.

Projects sit between active thoughts (volatile working memory) and growth threads
(developmental aspirations). They represent concrete deliverables with ordered
actions that can be tracked, edited, paused, and completed.
"""

from agency.projects.manager import (
    Project,
    ProjectAction,
    ProjectManager,
    get_project_manager,
)

__all__ = [
    'Project',
    'ProjectAction',
    'ProjectManager',
    'get_project_manager',
]
