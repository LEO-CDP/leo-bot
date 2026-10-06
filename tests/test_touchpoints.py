import numpy as np

from leoai.ai_core import get_embedding_model, get_touchpoint_embedding_model
from leoai.leo_datamodel import GeolocationTouchpointRequest
from leoai.rag_db_manager import build_touchpoint_embedding_text


def test_touchpoint_embedding_configuration_is_separate_from_chat_embeddings():
    assert get_embedding_model().dimensions == 768
    assert get_touchpoint_embedding_model().dimensions == 768


def test_touchpoint_embedding_text_is_stable_and_structured():
    assert build_touchpoint_embedding_text(
        "Cafe",
        "Nearby coffee",
        "venue",
        ["coffee", "wifi"],
    ) == (
        "name: Cafe\n"
        "description: Nearby coffee\n"
        "type: venue\n"
        "keywords: coffee, wifi"
    )


def test_touchpoint_request_defaults_metadata_without_changing_coordinates():
    request = GeolocationTouchpointRequest(
        visitor_id="visitor-1",
        latitude=21.028,
        longitude=105.804,
    )

    assert request.name == "Web visitor"
    assert request.description == ""
    assert request.type == "web"
    assert request.keywords == []
    assert np.isclose(request.latitude, 21.028)
