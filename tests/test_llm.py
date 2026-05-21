from __future__ import annotations

from androidharness.llm import GoogleGenaiClient, LLMClient


def test_llm_module_exports_protocol_and_google_client():
    """The Protocol and the relocated Google client both live in androidharness.llm.
    GoogleGenaiClient must structurally satisfy the LLMClient Protocol — i.e. it
    exposes a `generate(*, model, system_instruction, contents, tools) -> dict`
    method. We don't need to instantiate it; just check the attribute is there."""
    assert hasattr(GoogleGenaiClient, "generate")
    assert callable(getattr(GoogleGenaiClient, "generate"))
    assert LLMClient is not None
