"""ucp-gen — generate Universal Context Packages from real systems."""
from .build import build_package
from .build_jira import build_jira_package

__version__ = "0.2.0"

__all__ = ["build_package", "build_jira_package", "__version__"]
