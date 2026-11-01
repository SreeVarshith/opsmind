"""Who may see which documents (role-based access control, RBAC).

Every chunk gets an `access` label at index time. Search filters on it inside Qdrant, so a
restricted document never reaches the LLM (or the response) for a user without access.

Policy for the demo knowledge base:
  - restricted: control-plane runbooks (etcd, API server, scheduler, controller manager, certificates)
                - changing these can take down the whole cluster
  - public:     everything else
"""
from app.rag.chunking import Chunk

PUBLIC = "public"
RESTRICTED = "restricted"

RESTRICTED_COMPONENTS = {"etcd"}
RESTRICTED_ALERTS = {"KubeAPIDown", "KubeAPIErrorBudgetBurn", "KubeAPITerminatedRequests", "KubeSchedulerDown",
                     "KubeControllerManagerDown", "KubeClientCertificateExpiration", "KubeAggregatedAPIDown",
                     "KubeAggregatedAPIErrors"}

ROLE_ACCESS: dict[str, list[str]] = {
    "admin": [PUBLIC, RESTRICTED],
    "sre": [PUBLIC, RESTRICTED],
    "developer": [PUBLIC],
}


def access_level(chunk: Chunk) -> str:
    if chunk.metadata.get("access") in (PUBLIC, RESTRICTED):  # chosen at upload time
        return chunk.metadata["access"]
    if chunk.source_type == "runbook" and (chunk.metadata.get("component") in RESTRICTED_COMPONENTS
                                           or chunk.metadata.get("alert") in RESTRICTED_ALERTS):
        return RESTRICTED
    return PUBLIC


def levels_for_role(role: str) -> list[str]:
    return ROLE_ACCESS.get(role, [PUBLIC])  # unknown roles get the least access
