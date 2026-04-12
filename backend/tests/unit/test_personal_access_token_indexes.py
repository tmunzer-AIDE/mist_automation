"""Unit tests for PersonalAccessToken model index configuration."""

import pytest
from pymongo import ASCENDING, IndexModel

from app.models.personal_access_token import PersonalAccessToken


@pytest.mark.unit
def test_pat_expires_at_ttl_index_present():
    ttl_index_found = False

    for index in PersonalAccessToken.Settings.indexes:
        if isinstance(index, IndexModel):
            doc = index.document
            keys = list(doc["key"].items())
            if keys == [("expires_at", ASCENDING)] and doc.get("expireAfterSeconds") == 0:
                ttl_index_found = True
                break

    assert ttl_index_found is True
