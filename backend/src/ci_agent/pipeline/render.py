"""Renderer dispatch (PDF §4 renderers, Phase 7 platform adapters).

Each renderer is deterministic: same IR -> same bytes. Renderers translate the
IR only; they never call the LLM and never invent steps.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..common.models import PipelineIR


@dataclass
class RenderedOutput:
    filename: str
    content: str
    notes: list[str] = field(default_factory=list)
    renderer: str = ""


def render(ir: PipelineIR) -> RenderedOutput:
    from . import azure, github, gitlab, jenkins

    modules = {"github": github, "azure": azure, "gitlab": gitlab, "jenkins": jenkins}
    module = modules.get(ir.platform)
    if module is None:
        raise ValueError(f"no renderer for platform '{ir.platform}'")
    content, notes = module.render(ir)
    return RenderedOutput(filename=module.filename(ir), content=content, notes=notes, renderer=ir.platform)


def supported_platforms() -> list[str]:
    return ["github", "azure", "gitlab", "jenkins"]
