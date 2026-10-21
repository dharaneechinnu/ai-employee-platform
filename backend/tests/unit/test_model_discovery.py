"""Which models a key is offered, and which is tried first."""

from app.agent.providers.models import chat_models, is_chat_model, try_order


def test_models_that_cannot_chat_are_dropped() -> None:
    ids = [
        "llama-3.3-70b-versatile",
        "whisper-large-v3",
        "text-embedding-3-small",
        "gemini-2.0-flash",
        "llama-guard-3-8b",
        "gpt-4o-mini-tts",
        "omni-moderation-latest",
        "imagen-3.0-generate",
    ]
    assert chat_models(ids) == ["llama-3.3-70b-versatile", "gemini-2.0-flash"]
    assert not is_chat_model("")


def test_the_model_in_use_is_tried_first_then_stable_before_preview() -> None:
    ids = [
        "gemini-2.5-pro-preview-05-06",
        "gemini-2.0-flash",
        "some-odd-model",
        "llama-3.3-70b-versatile",
    ]
    ordered = try_order(ids, current="some-odd-model")
    assert ordered[0] == "some-odd-model"
    # Stable well-known models come before a preview, and unknown ones last.
    assert ordered.index("llama-3.3-70b-versatile") < ordered.index("gemini-2.5-pro-preview-05-06")
    assert ordered.index("gemini-2.0-flash") < ordered.index("gemini-2.5-pro-preview-05-06")


def test_duplicates_are_removed_and_order_is_stable_for_ties() -> None:
    assert try_order(["a-model", "b-model", "a-model"]) == ["a-model", "b-model"]


def test_an_extra_auth_header_comes_from_data_not_code() -> None:
    """A provider that wants its key under its own header needs no adapter."""
    from app.agent.providers import build_provider

    sarvam = build_provider(
        "sarvam",
        "sk_test",
        base_url="https://api.sarvam.ai/v1",
        api_format="openai",
        auth_header="api-subscription-key",
    )
    assert sarvam.base_url == "https://api.sarvam.ai/v1"
    assert sarvam._headers() == {
        "Authorization": "Bearer sk_test",
        "api-subscription-key": "sk_test",
    }
    # Everyone else is unchanged.
    from app.agent.providers.openai_compatible import OpenAICompatibleProvider

    assert OpenAICompatibleProvider("k", provider_key="groq")._headers() == {
        "Authorization": "Bearer k"
    }
