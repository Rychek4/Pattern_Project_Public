"""
Pattern Project - Project Manager
Manages structured multi-step plans with ordered actions.

Projects track concrete deliverables with checkable progress. Each project
has a name, description, status, and an ordered list of actions (steps).

Lifecycle:
    ACTIVE → COMPLETED (all actions done or manually completed)
    ACTIVE → PAUSED (park it, work on something else)
    ACTIVE → ABANDONED (with reason)
    PAUSED → ACTIVE (resume)

Currently enforces a single active project constraint (soft limit),
designed to support concurrent projects in the future.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple

from core.database import get_database
from concurrency.db_retry import db_retry
from core.logger import log_info, log_error

# Valid statuses
VALID_PROJECT_STATUSES = ('active', 'paused', 'completed', 'abandoned')
VALID_ACTION_STATUSES = ('pending', 'in_progress', 'completed')


@dataclass
class ProjectAction:
    """A single action (step) within a project."""
    id: int
    project_id: int
    description: str
    notes: Optional[str]
    status: str  # pending, in_progress, completed
    sort_order: int
    created_at: datetime
    updated_at: datetime


@dataclass
class Project:
    """A structured multi-step project."""
    id: int
    name: str
    description: str
    status: str  # active, paused, completed, abandoned
    abandonment_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    actions: List[ProjectAction]


class ProjectManager:
    """
    Manages projects — structured multi-step plans with progress tracking.

    Operations:
    - create: Start a new project with initial actions
    - update: Edit project name/description
    - complete/abandon/pause/resume: Lifecycle transitions
    - get: Retrieve project with actions
    - Action CRUD: add, update, remove, reorder, complete actions
    """

    def __init__(self):
        import config
        self._max_active = getattr(config, 'PROJECTS_MAX_ACTIVE', 1)

    # ── Project Operations ──

    @db_retry()
    def create(
        self,
        name: str,
        description: str,
        actions: Optional[List[str]] = None
    ) -> Tuple[Optional[Project], Optional[str]]:
        """
        Create a new project with optional initial actions.

        Args:
            name: Project name
            description: What this project is about
            actions: Optional list of action descriptions (in order)

        Returns:
            Tuple of (Project or None, error_message or None)
        """
        if not name or not isinstance(name, str):
            return None, "Project name is required"
        if not description or not isinstance(description, str):
            return None, "Project description is required"

        # Check active project limit
        active_count = self._count_active()
        if active_count >= self._max_active:
            return None, (
                f"Maximum {self._max_active} active project(s) allowed "
                f"(currently {active_count}). "
                f"Complete, pause, or abandon the current project first."
            )

        try:
            db = get_database()
            now = datetime.now().isoformat()

            with db.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO projects (name, description, status, created_at, updated_at)
                    VALUES (?, ?, 'active', ?, ?)
                    """,
                    (name, description, now, now)
                )
                project_id = cursor.lastrowid

                # Insert initial actions
                if actions:
                    for i, action_desc in enumerate(actions):
                        if action_desc and isinstance(action_desc, str):
                            conn.execute(
                                """
                                INSERT INTO project_actions
                                (project_id, description, status, sort_order, created_at, updated_at)
                                VALUES (?, ?, 'pending', ?, ?, ?)
                                """,
                                (project_id, action_desc, i, now, now)
                            )

            log_info(f"Project created: '{name}' (id={project_id})", prefix="📋")
            return self.get(project_id), None

        except Exception as e:
            error_msg = f"Failed to create project: {e}"
            log_error(error_msg)
            return None, error_msg

    @db_retry()
    def update(
        self,
        project_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Update project name and/or description."""
        if name is None and description is None:
            return False, "Nothing to update — provide name and/or description"

        try:
            db = get_database()
            project = self.get(project_id)
            if project is None:
                return False, f"No project found with id {project_id}"

            now = datetime.now().isoformat()
            updates = []
            params = []

            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if description is not None:
                updates.append("description = ?")
                params.append(description)

            updates.append("updated_at = ?")
            params.append(now)
            params.append(project_id)

            db.execute(
                f"UPDATE projects SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )

            log_info(f"Project {project_id} updated", prefix="📋")
            return True, None

        except Exception as e:
            error_msg = f"Failed to update project {project_id}: {e}"
            log_error(error_msg)
            return False, error_msg

    @db_retry()
    def complete(self, project_id: int) -> Tuple[bool, Optional[str]]:
        """Mark a project as completed."""
        return self._transition(project_id, 'completed', from_statuses=('active',))

    @db_retry()
    def abandon(self, project_id: int, reason: str) -> Tuple[bool, Optional[str]]:
        """Abandon a project with a reason."""
        if not reason or not isinstance(reason, str):
            return False, "Abandonment reason is required"

        project = self.get(project_id)
        if project is None:
            return False, f"No project found with id {project_id}"
        if project.status not in ('active', 'paused'):
            return False, f"Cannot abandon a project with status '{project.status}'"

        try:
            db = get_database()
            now = datetime.now().isoformat()
            db.execute(
                "UPDATE projects SET status = 'abandoned', abandonment_reason = ?, updated_at = ? WHERE id = ?",
                (reason, now, project_id)
            )
            log_info(f"Project {project_id} abandoned: {reason}", prefix="📋")
            return True, None
        except Exception as e:
            error_msg = f"Failed to abandon project {project_id}: {e}"
            log_error(error_msg)
            return False, error_msg

    @db_retry()
    def pause(self, project_id: int) -> Tuple[bool, Optional[str]]:
        """Pause an active project."""
        return self._transition(project_id, 'paused', from_statuses=('active',))

    @db_retry()
    def resume(self, project_id: int) -> Tuple[bool, Optional[str]]:
        """Resume a paused project."""
        # Check active limit before resuming
        active_count = self._count_active()
        if active_count >= self._max_active:
            return False, (
                f"Maximum {self._max_active} active project(s) allowed. "
                f"Complete, pause, or abandon the current active project first."
            )
        return self._transition(project_id, 'active', from_statuses=('paused',))

    @db_retry()
    def get(self, project_id: int) -> Optional[Project]:
        """Get a project with all its actions."""
        db = get_database()
        row = db.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
            fetch=True
        )
        if not row:
            return None

        actions = db.execute(
            "SELECT * FROM project_actions WHERE project_id = ? ORDER BY sort_order ASC",
            (project_id,),
            fetch=True
        )

        return self._row_to_project(row[0], actions or [])

    @db_retry()
    def get_active(self) -> Optional[Project]:
        """Get the currently active project (if any)."""
        db = get_database()
        row = db.execute(
            "SELECT * FROM projects WHERE status = 'active' ORDER BY created_at DESC LIMIT 1",
            fetch=True
        )
        if not row:
            return None

        project_id = row[0]["id"]
        actions = db.execute(
            "SELECT * FROM project_actions WHERE project_id = ? ORDER BY sort_order ASC",
            (project_id,),
            fetch=True
        )

        return self._row_to_project(row[0], actions or [])

    @db_retry()
    def get_paused(self) -> List[Project]:
        """Get all paused projects."""
        db = get_database()
        rows = db.execute(
            "SELECT * FROM projects WHERE status = 'paused' ORDER BY updated_at DESC",
            fetch=True
        )
        if not rows:
            return []

        projects = []
        for row in rows:
            actions = db.execute(
                "SELECT * FROM project_actions WHERE project_id = ? ORDER BY sort_order ASC",
                (row["id"],),
                fetch=True
            )
            projects.append(self._row_to_project(row, actions or []))
        return projects

    # ── Action Operations ──

    @db_retry()
    def add_action(
        self, project_id: int, description: str, notes: Optional[str] = None
    ) -> Tuple[Optional[int], Optional[str]]:
        """Add a new action to a project. Returns (action_id, error)."""
        project = self.get(project_id)
        if project is None:
            return None, f"No project found with id {project_id}"
        if project.status not in ('active', 'paused'):
            return None, f"Cannot add actions to a {project.status} project"

        try:
            db = get_database()
            now = datetime.now().isoformat()

            # Get max sort_order
            result = db.execute(
                "SELECT MAX(sort_order) as max_order FROM project_actions WHERE project_id = ?",
                (project_id,),
                fetch=True
            )
            next_order = (result[0]["max_order"] or -1) + 1 if result else 0

            with db.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO project_actions
                    (project_id, description, notes, status, sort_order, created_at, updated_at)
                    VALUES (?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (project_id, description, notes, next_order, now, now)
                )
                action_id = cursor.lastrowid

            # Update project's updated_at
            db.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id)
            )

            log_info(f"Action added to project {project_id}: '{description[:50]}'", prefix="📋")
            return action_id, None

        except Exception as e:
            error_msg = f"Failed to add action: {e}"
            log_error(error_msg)
            return None, error_msg

    @db_retry()
    def update_action(
        self,
        action_id: int,
        description: Optional[str] = None,
        notes: Optional[str] = None,
        status: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Update an action's description, notes, and/or status."""
        if description is None and notes is None and status is None:
            return False, "Nothing to update"

        if status is not None and status not in VALID_ACTION_STATUSES:
            return False, f"Invalid status '{status}'. Must be one of: {', '.join(VALID_ACTION_STATUSES)}"

        try:
            db = get_database()
            now = datetime.now().isoformat()

            # Verify action exists
            row = db.execute(
                "SELECT * FROM project_actions WHERE id = ?",
                (action_id,),
                fetch=True
            )
            if not row:
                return False, f"No action found with id {action_id}"

            project_id = row[0]["project_id"]

            updates = []
            params = []
            if description is not None:
                updates.append("description = ?")
                params.append(description)
            if notes is not None:
                updates.append("notes = ?")
                params.append(notes)
            if status is not None:
                updates.append("status = ?")
                params.append(status)
            updates.append("updated_at = ?")
            params.append(now)
            params.append(action_id)

            db.execute(
                f"UPDATE project_actions SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )

            # Update project's updated_at
            db.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id)
            )

            log_info(f"Action {action_id} updated", prefix="📋")
            return True, None

        except Exception as e:
            error_msg = f"Failed to update action {action_id}: {e}"
            log_error(error_msg)
            return False, error_msg

    @db_retry()
    def remove_action(self, action_id: int) -> Tuple[bool, Optional[str]]:
        """Remove an action from a project."""
        try:
            db = get_database()

            row = db.execute(
                "SELECT project_id FROM project_actions WHERE id = ?",
                (action_id,),
                fetch=True
            )
            if not row:
                return False, f"No action found with id {action_id}"

            project_id = row[0]["project_id"]
            now = datetime.now().isoformat()

            db.execute("DELETE FROM project_actions WHERE id = ?", (action_id,))

            # Update project's updated_at
            db.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id)
            )

            log_info(f"Action {action_id} removed from project {project_id}", prefix="📋")
            return True, None

        except Exception as e:
            error_msg = f"Failed to remove action {action_id}: {e}"
            log_error(error_msg)
            return False, error_msg

    @db_retry()
    def reorder_actions(
        self, project_id: int, action_ids: List[int]
    ) -> Tuple[bool, Optional[str]]:
        """Reorder actions by providing action IDs in desired order."""
        project = self.get(project_id)
        if project is None:
            return False, f"No project found with id {project_id}"

        existing_ids = {a.id for a in project.actions}
        provided_ids = set(action_ids)

        if existing_ids != provided_ids:
            return False, (
                f"Action IDs don't match. "
                f"Expected: {sorted(existing_ids)}, got: {sorted(provided_ids)}"
            )

        try:
            db = get_database()
            now = datetime.now().isoformat()

            with db.get_connection() as conn:
                for order, aid in enumerate(action_ids):
                    conn.execute(
                        "UPDATE project_actions SET sort_order = ?, updated_at = ? WHERE id = ?",
                        (order, now, aid)
                    )
                conn.execute(
                    "UPDATE projects SET updated_at = ? WHERE id = ?",
                    (now, project_id)
                )

            log_info(f"Project {project_id} actions reordered", prefix="📋")
            return True, None

        except Exception as e:
            error_msg = f"Failed to reorder actions: {e}"
            log_error(error_msg)
            return False, error_msg

    @db_retry()
    def complete_action(self, action_id: int) -> Tuple[bool, Optional[str]]:
        """Mark an action as completed."""
        return self.update_action(action_id, status='completed')

    # ── Internal Helpers ──

    def _transition(
        self, project_id: int, to_status: str, from_statuses: tuple
    ) -> Tuple[bool, Optional[str]]:
        """Transition a project between statuses."""
        project = self.get(project_id)
        if project is None:
            return False, f"No project found with id {project_id}"
        if project.status not in from_statuses:
            return False, (
                f"Cannot transition from '{project.status}' to '{to_status}'. "
                f"Project must be in one of: {', '.join(from_statuses)}"
            )

        try:
            db = get_database()
            now = datetime.now().isoformat()
            db.execute(
                "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                (to_status, now, project_id)
            )
            log_info(f"Project {project_id}: {project.status} → {to_status}", prefix="📋")
            return True, None
        except Exception as e:
            error_msg = f"Failed to transition project {project_id}: {e}"
            log_error(error_msg)
            return False, error_msg

    @db_retry()
    def _count_active(self) -> int:
        """Count projects with active status."""
        db = get_database()
        result = db.execute(
            "SELECT COUNT(*) as count FROM projects WHERE status = 'active'",
            fetch=True
        )
        return result[0]["count"] if result else 0

    def _row_to_project(self, row, action_rows) -> Project:
        """Convert database rows to a Project object."""
        created_at = row["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        updated_at = row["updated_at"]
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        actions = [self._row_to_action(a) for a in action_rows]

        return Project(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            status=row["status"],
            abandonment_reason=row["abandonment_reason"],
            created_at=created_at,
            updated_at=updated_at,
            actions=actions
        )

    def _row_to_action(self, row) -> ProjectAction:
        """Convert a database row to a ProjectAction object."""
        created_at = row["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        updated_at = row["updated_at"]
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        return ProjectAction(
            id=row["id"],
            project_id=row["project_id"],
            description=row["description"],
            notes=row["notes"],
            status=row["status"],
            sort_order=row["sort_order"],
            created_at=created_at,
            updated_at=updated_at
        )


# Global instance
_manager: Optional[ProjectManager] = None


def get_project_manager() -> ProjectManager:
    """Get the global ProjectManager instance."""
    global _manager
    if _manager is None:
        _manager = ProjectManager()
    return _manager
