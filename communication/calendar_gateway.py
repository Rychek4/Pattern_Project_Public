"""
Pattern Project - Google Calendar Gateway
OAuth2-based Google Calendar API integration for reading and writing events.

This module provides the underlying calendar service used by the calendar
tool handlers. On first use, it triggers a browser-based OAuth consent flow.
After consent, tokens are saved locally and auto-refresh.
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.logger import log_info, log_error, log_success, log_warning


@dataclass
class CalendarResult:
    """
    Result from a calendar gateway operation.

    Attributes:
        success: Whether the operation succeeded
        message: Status message (success info or error description)
        data: Structured result data (event dict, list of events, etc.)
        timestamp: When the operation occurred
    """
    success: bool
    message: str
    data: Optional[Any] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def __str__(self) -> str:
        status = "Success" if self.success else "Failed"
        return f"{status}: {self.message}"


class CalendarGateway:
    """
    Google Calendar gateway using the Calendar API v3.

    Handles OAuth2 authentication with automatic token refresh.
    On first use, opens a browser for user consent. After consent,
    the token is stored locally and refreshed automatically.
    """

    # Full read/write access to Google Calendar
    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(
        self,
        credentials_path: str,
        token_path: str,
    ):
        """
        Initialize the calendar gateway.

        Args:
            credentials_path: Path to the OAuth2 credentials JSON from Google Cloud Console
            token_path: Path where the OAuth2 token will be saved/loaded
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._service = None

    def is_available(self) -> bool:
        """
        Check if the gateway is properly configured.

        Returns:
            True if the credentials file exists, False otherwise
        """
        return os.path.exists(self.credentials_path)

    def _get_service(self):
        """
        Get or create the authenticated Google Calendar API service.

        On first call (no token file), opens a browser for OAuth consent.
        On subsequent calls, loads the saved token and refreshes if needed.

        Returns:
            Authenticated Google Calendar API service object

        Raises:
            RuntimeError: If credentials file is missing or auth fails
        """
        if self._service is not None:
            return self._service

        if not self.is_available():
            raise RuntimeError(
                f"Google Calendar credentials not found at {self.credentials_path}. "
                "Download OAuth2 credentials from Google Cloud Console."
            )

        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = None

        # Load existing token if available
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(
                    self.token_path, self.SCOPES
                )
                log_info("Loaded existing Google Calendar token")
            except Exception as e:
                log_warning(f"Failed to load token, will re-authenticate: {e}")
                creds = None

        # Refresh or obtain new credentials
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                log_info("Refreshed Google Calendar token")
            except Exception as e:
                log_warning(f"Token refresh failed, will re-authenticate: {e}")
                creds = None

        if not creds or not creds.valid:
            log_info("Starting Google Calendar OAuth consent flow (browser will open)...")
            flow = InstalledAppFlow.from_client_secrets_file(
                self.credentials_path, self.SCOPES
            )
            creds = flow.run_local_server(port=0)
            log_success("Google Calendar OAuth consent completed")

            # Save token for future use
            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())
            log_info(f"Saved Google Calendar token to {self.token_path}")

        self._service = build("calendar", "v3", credentials=creds)
        log_success("Google Calendar API service initialized")
        return self._service

    def list_events(
        self,
        start_date: str,
        end_date: str,
        max_results: int = 50,
    ) -> CalendarResult:
        """
        List events within a date range from the primary calendar.

        Args:
            start_date: Start of range in ISO 8601 format (e.g., "2025-03-01T00:00:00")
            end_date: End of range in ISO 8601 format (e.g., "2025-03-31T23:59:59")
            max_results: Maximum number of events to return (default 50)

        Returns:
            CalendarResult with list of event dicts in data field
        """
        try:
            service = self._get_service()

            # Ensure timezone info is present for the API
            time_min = self._ensure_timezone(start_date)
            time_max = self._ensure_timezone(end_date)

            events_result = service.events().list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = events_result.get("items", [])
            log_info(f"Retrieved {len(events)} calendar events")

            # Simplify event data for the AI
            simplified = []
            for event in events:
                simplified.append(self._simplify_event(event))

            return CalendarResult(
                success=True,
                message=f"Found {len(simplified)} events",
                data=simplified,
            )

        except RuntimeError as e:
            log_error(f"Calendar gateway error: {e}")
            return CalendarResult(
                success=False,
                message=str(e),
            )
        except Exception as e:
            log_error(f"Failed to list calendar events: {e}")
            return CalendarResult(
                success=False,
                message=f"Failed to list events: {str(e)}",
            )

    def create_event(
        self,
        title: str,
        start_time: str,
        end_time: str,
        description: str = "",
        location: str = "",
        recurrence: str = "",
        reminders: Optional[List[Dict[str, Any]]] = None,
    ) -> CalendarResult:
        """
        Create a new event on the primary calendar.

        Args:
            title: Event title/summary
            start_time: Start time in ISO 8601 format
            end_time: End time in ISO 8601 format
            description: Optional event description
            location: Optional event location
            recurrence: Optional RRULE string (e.g., "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR")

        Returns:
            CalendarResult with created event data
        """
        try:
            service = self._get_service()

            event_body: Dict[str, Any] = {
                "summary": title,
                "start": self._build_datetime_field(start_time),
                "end": self._build_datetime_field(end_time),
            }

            if description:
                event_body["description"] = description
            if location:
                event_body["location"] = location
            if recurrence:
                event_body["recurrence"] = [recurrence]

            # Apply reminders: AI-provided, defaults from config, or none
            event_body["reminders"] = self._build_reminders_field(reminders)

            created = service.events().insert(
                calendarId="primary",
                body=event_body,
            ).execute()

            log_success(f"Created calendar event: {title}")

            return CalendarResult(
                success=True,
                message=f"Event created: {title}",
                data=self._simplify_event(created),
            )

        except RuntimeError as e:
            log_error(f"Calendar gateway error: {e}")
            return CalendarResult(
                success=False,
                message=str(e),
            )
        except Exception as e:
            log_error(f"Failed to create calendar event: {e}")
            return CalendarResult(
                success=False,
                message=f"Failed to create event: {str(e)}",
            )

    def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        recurrence: Optional[str] = None,
        update_scope: str = "this_event",
        reminders: Optional[List[Dict[str, Any]]] = None,
    ) -> CalendarResult:
        """
        Update an existing event on the primary calendar.

        Args:
            event_id: The event ID to update
            title: New title (if changing)
            start_time: New start time (if changing)
            end_time: New end time (if changing)
            description: New description (if changing)
            location: New location (if changing)
            recurrence: New RRULE string (if changing)
            update_scope: "this_event" for single instance, "all_events" for entire series

        Returns:
            CalendarResult with updated event data
        """
        try:
            service = self._get_service()

            # For recurring series updates, use the base event ID (strip instance suffix)
            target_id = event_id
            if update_scope == "all_events" and "_" in event_id:
                target_id = event_id.split("_")[0]

            # Fetch current event to merge changes
            existing = service.events().get(
                calendarId="primary",
                eventId=target_id,
            ).execute()

            # Apply changes
            if title is not None:
                existing["summary"] = title
            if start_time is not None:
                existing["start"] = self._build_datetime_field(start_time)
            if end_time is not None:
                existing["end"] = self._build_datetime_field(end_time)
            if description is not None:
                existing["description"] = description
            if location is not None:
                existing["location"] = location
            if recurrence is not None:
                existing["recurrence"] = [recurrence] if recurrence else []
            if reminders is not None:
                existing["reminders"] = self._build_reminders_field(reminders)

            updated = service.events().update(
                calendarId="primary",
                eventId=target_id,
                body=existing,
            ).execute()

            scope_label = "series" if update_scope == "all_events" else "event"
            log_success(f"Updated calendar {scope_label}: {updated.get('summary', event_id)}")

            return CalendarResult(
                success=True,
                message=f"Updated {scope_label}: {updated.get('summary', event_id)}",
                data=self._simplify_event(updated),
            )

        except RuntimeError as e:
            log_error(f"Calendar gateway error: {e}")
            return CalendarResult(
                success=False,
                message=str(e),
            )
        except Exception as e:
            log_error(f"Failed to update calendar event: {e}")
            return CalendarResult(
                success=False,
                message=f"Failed to update event: {str(e)}",
            )

    def delete_event(
        self,
        event_id: str,
        delete_scope: str = "this_event",
    ) -> CalendarResult:
        """
        Delete an event from the primary calendar.

        Args:
            event_id: The event ID to delete
            delete_scope: "this_event" for single instance, "all_events" for entire series

        Returns:
            CalendarResult with deletion confirmation
        """
        try:
            service = self._get_service()

            # For recurring series deletion, use the base event ID
            target_id = event_id
            if delete_scope == "all_events" and "_" in event_id:
                target_id = event_id.split("_")[0]

            service.events().delete(
                calendarId="primary",
                eventId=target_id,
            ).execute()

            scope_label = "series" if delete_scope == "all_events" else "event"
            log_success(f"Deleted calendar {scope_label}: {event_id}")

            return CalendarResult(
                success=True,
                message=f"Deleted {scope_label}: {event_id}",
                data={"event_id": event_id, "scope": delete_scope},
            )

        except RuntimeError as e:
            log_error(f"Calendar gateway error: {e}")
            return CalendarResult(
                success=False,
                message=str(e),
            )
        except Exception as e:
            log_error(f"Failed to delete calendar event: {e}")
            return CalendarResult(
                success=False,
                message=f"Failed to delete event: {str(e)}",
            )

    def _simplify_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simplify a Google Calendar event dict for AI consumption.

        Strips internal fields and returns only what's useful for the AI.

        Args:
            event: Raw event dict from Google Calendar API

        Returns:
            Simplified event dict
        """
        start = event.get("start", {})
        end = event.get("end", {})

        simplified = {
            "event_id": event.get("id", ""),
            "title": event.get("summary", "(No title)"),
            "start": start.get("dateTime", start.get("date", "")),
            "end": end.get("dateTime", end.get("date", "")),
        }

        if event.get("description"):
            simplified["description"] = event["description"]
        if event.get("location"):
            simplified["location"] = event["location"]
        if event.get("recurrence"):
            simplified["recurrence"] = event["recurrence"]
        if event.get("recurringEventId"):
            simplified["recurring_event_id"] = event["recurringEventId"]
        if event.get("status") and event["status"] != "confirmed":
            simplified["status"] = event["status"]

        return simplified

    def _build_reminders_field(
        self, reminders: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """
        Build the Google Calendar reminders field for an event.

        Args:
            reminders: List of reminder dicts with 'method' and 'minutes',
                       or None to apply defaults from config.
                       An empty list means no reminders.

        Returns:
            Dict with 'useDefault' and optional 'overrides' for the API
        """
        if reminders is None:
            # Apply defaults from config
            from config import GOOGLE_CALENDAR_DEFAULT_REMINDERS
            overrides = GOOGLE_CALENDAR_DEFAULT_REMINDERS
        else:
            overrides = reminders

        if not overrides:
            # Explicitly no reminders
            return {"useDefault": False, "overrides": []}

        return {
            "useDefault": False,
            "overrides": [
                {"method": r["method"], "minutes": r["minutes"]}
                for r in overrides[:5]  # Google API max is 5
            ],
        }

    def _build_datetime_field(self, iso_time: str) -> Dict[str, str]:
        """
        Build a Google Calendar datetime field from an ISO 8601 string.

        Handles both date-only ("2025-03-01") and datetime ("2025-03-01T10:00:00")
        formats. Datetime values get a timezone suffix if not already present.

        Args:
            iso_time: ISO 8601 date or datetime string

        Returns:
            Dict with either "date" or "dateTime" and "timeZone" keys
        """
        # Date-only format (all-day events)
        if len(iso_time) == 10 and "T" not in iso_time:
            return {"date": iso_time}

        # Datetime format
        return {
            "dateTime": self._ensure_timezone(iso_time),
            "timeZone": self._get_local_timezone(),
        }

    def _ensure_timezone(self, iso_time: str) -> str:
        """
        Ensure an ISO 8601 datetime string has timezone info.

        If no timezone offset or 'Z' suffix is present, appends the
        local timezone offset.

        Args:
            iso_time: ISO 8601 datetime string

        Returns:
            Datetime string with timezone info
        """
        # Already has timezone info
        if iso_time.endswith("Z") or "+" in iso_time[10:] or iso_time.count("-") > 2:
            return iso_time

        # Append local timezone offset
        try:
            local_offset = datetime.now().astimezone().strftime("%z")
            # Format as +HH:MM
            offset_formatted = f"{local_offset[:3]}:{local_offset[3:]}"
            return f"{iso_time}{offset_formatted}"
        except Exception:
            # Fallback: assume UTC
            return f"{iso_time}Z"

    def _get_local_timezone(self) -> str:
        """
        Get the IANA timezone name for calendar events.

        Uses the configured GOOGLE_CALENDAR_TIMEZONE setting, falling back
        to system detection and then UTC.

        Returns:
            IANA timezone name (e.g., "America/New_York") or UTC fallback
        """
        from config import GOOGLE_CALENDAR_TIMEZONE

        if GOOGLE_CALENDAR_TIMEZONE:
            return GOOGLE_CALENDAR_TIMEZONE

        try:
            # Try to get the proper IANA name from the system
            local_tz = datetime.now().astimezone().tzinfo
            if hasattr(local_tz, 'key'):
                return local_tz.key
            if hasattr(local_tz, 'zone'):
                return local_tz.zone
        except Exception:
            pass

        return "UTC"


# Singleton instance
_gateway: Optional[CalendarGateway] = None


def get_calendar_gateway() -> CalendarGateway:
    """
    Get the global calendar gateway instance.

    Returns:
        The global CalendarGateway instance

    Raises:
        RuntimeError: If gateway not initialized
    """
    if _gateway is None:
        raise RuntimeError(
            "Calendar gateway not initialized. Call init_calendar_gateway() first."
        )
    return _gateway


def init_calendar_gateway(
    credentials_path: Optional[str] = None,
    token_path: Optional[str] = None,
) -> CalendarGateway:
    """
    Initialize the global calendar gateway instance.

    Args:
        credentials_path: Path to OAuth2 credentials JSON (defaults to config)
        token_path: Path to save/load OAuth2 token (defaults to config)

    Returns:
        The initialized CalendarGateway instance
    """
    global _gateway

    from config import (
        GOOGLE_CALENDAR_CREDENTIALS_PATH,
        GOOGLE_CALENDAR_TOKEN_PATH,
    )

    _gateway = CalendarGateway(
        credentials_path=credentials_path or GOOGLE_CALENDAR_CREDENTIALS_PATH,
        token_path=token_path or GOOGLE_CALENDAR_TOKEN_PATH,
    )

    if _gateway.is_available():
        log_info("Google Calendar gateway initialized")
    else:
        log_warning(
            "Google Calendar gateway initialized but credentials not found at "
            f"{_gateway.credentials_path}"
        )

    return _gateway
