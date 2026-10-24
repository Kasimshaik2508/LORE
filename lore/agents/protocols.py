"""Typed messages exchanged between the LORE router and its specialist agents."""

from uagents import Model


class IngestRequest(Model):
    source: str  # "folder" | "github"
    target: str  # folder path or owner/repo
    limit: int = 20


class IngestResponse(Model):
    ok: bool
    summary: str
    created: int = 0


class AskRequest(Model):
    question: str


class AskResponse(Model):
    answer_md: str
    evidence_json: str
    impact_json: str = ""


class ReviewRequest(Model):
    change: str
    files: list[str] = []
    justification: str = ""
    actor: str = ""


class ReviewResponse(Model):
    status: str
    report_md: str
    findings_json: str


class OnboardRequest(Model):
    focus: str = ""


class OnboardResponse(Model):
    report_md: str

