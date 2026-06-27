__version__ = "0.40.0"

from .client import AppConversationStart, OpenHandsClient, OpenHandsError, OpenHandsHTTPError, OpenHandsRunResult
from .conversation import OpenHandsConversation
from .instance import OpenHandsInstance
from .models import RoleRunResult, RoleRunSpec, RoleSummary, SummaryAttempt
from .runner import OpenHandsRoleRunner
from .summary import DEFAULT_SUMMARY_INSTRUCTIONS, build_summary_prompt, parse_json_strict, parse_role_summary
from .role import run_role_with_summary

__all__ = [
    "__version__",
    "AppConversationStart",
    "OpenHandsClient",
    "OpenHandsConversation",
    "OpenHandsError",
    "OpenHandsHTTPError",
    "OpenHandsInstance",
    "OpenHandsRoleRunner",
    "OpenHandsRunResult",
    "RoleRunResult",
    "RoleRunSpec",
    "RoleSummary",
    "SummaryAttempt",
    "DEFAULT_SUMMARY_INSTRUCTIONS",
    "build_summary_prompt",
    "parse_json_strict",
    "parse_role_summary",
    "run_role_with_summary",
]
