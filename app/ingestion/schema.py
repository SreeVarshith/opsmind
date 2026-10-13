"""The one format every data source is converted into before indexing."""
import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field

SourceType = Literal["runbook", "postmortem", "log", "ticket"]


class Document(BaseModel):
    id: str
    source_type: SourceType
    title: str
    text: str
    source: str = Field(description="Where it came from: a URL or a file path, used for citations")
    metadata: dict[str, Any] = Field(default_factory=dict)


def make_id(source_type: str, *parts: str) -> str:
    """Stable id: the same input always gives the same id, so re-ingesting never creates duplicates."""
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{source_type}-{digest}"
