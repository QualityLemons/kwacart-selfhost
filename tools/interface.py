from abc import ABC, abstractmethod
from django.core.exceptions import ValidationError


class BaseTool(ABC):
    """Standard interface for all tool implementations.

    Three-step pipeline
    -------------------
    1. ``validate()`` — populate ``self.errors`` with any field-level problems.
    2. ``execute()``  — calls ``validate()``, raises ``ValidationError`` if
       ``self.errors`` is non-empty, then calls ``process()``.
    3. ``process()``  — the core logic; returns a dict of structured output
       whose keys match the tool's ``PHASES`` field names.

    ``self.errors``
    ---------------
    A dict populated by ``validate()``.  Keys are field names (matching form
    field names); values are human-readable error strings.  Mirrors the
    structure of Django's form ``errors`` dict so views can pass them directly
    to form error display.  ``execute()`` raises
    ``django.core.exceptions.ValidationError(self.errors)`` if it is non-empty.

    Subclasses must implement both abstract methods (``validate`` and
    ``process``).
    """

    # Used by get_metadata() and stored in ToolInstance.tool_version at creation time.
    name = "Base Tool"
    description = ""
    version = "1.0"

    def __init__(self, user_input=None):
        self.user_input = user_input or {}
        # errors is populated by validate(); keys are field names, values are
        # human-readable strings.  execute() raises ValidationError(self.errors)
        # if it is non-empty after validate() returns.
        self.errors = {}

    @abstractmethod
    def validate(self):
        """Check if user_input meets the tool's requirements."""
        pass

    @abstractmethod
    def process(self):
        """The core logic of the tool. Returns structured data."""
        pass

    def execute(self):
        """Run the full validate → process pipeline.

        Calls ``validate()`` first.  If ``self.errors`` is non-empty after
        validation, raises ``django.core.exceptions.ValidationError`` with the
        error dict so the calling view can surface field-level messages.  Only
        when validation passes does it call ``process()`` and return its result.
        """
        self.validate()
        if self.errors:
            raise ValidationError(self.errors)

        return self.process()

    def get_metadata(self):
        """Return a dict of core tool metadata.

        Called by ``tools.utils.get_tool_metadata`` to supplement the registry
        entry with runtime attributes (name, version, description) from the
        ``BaseTool`` subclass.
        """
        return {
            "tool_name": self.name,
            "version": self.version,
            "description": self.description,
        }
