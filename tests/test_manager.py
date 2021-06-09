from typing import Optional
from urllib.parse import urlencode

import pytest
from django.core.cache import cache
from requests_mock.mocker import Mocker
from rest_framework.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from django_json_api.client import JSONAPIClientError
from django_json_api.manager import JSONAPIManager
from tests.models import Dummy

PAGES = [
    {
        "data": [
            {
                "id": str(10 * j + i + 1),
                "type": "tests",
                "attributes": {
                    "name": f"Record #{10 * j + i + 1}",
                },
            }
            for i in range(0, (8 if j == 4 else 10))
        ],
    }
    for j in range(0, 5)
]


@pytest.fixture
def pages() -> Mocker:
    with Mocker() as mocker:
        for i, page in enumerate(PAGES):
            params = {
                "include": "related",
                "fields[tests]": "field,related",
                "page[size]": 10,
                "page[number]": i + 1,
            }
            mocker.register_uri(
                "GET",
                f"http://test/api/tests/?{urlencode(params)}",
                status_code=200,
                json=page,
            )
        yield mocker


@pytest.fixture
def empty_page() -> Mocker:
    page = {
        "data": [],
        "meta": {"record_count": 0},
        "links": {"first": "first", "last": "last"},
    }

    with Mocker() as mocker:
        params = {
            "include": "related",
            "fields[tests]": "field,related",
            "page[size]": 10,
            "page[number]": 1,
        }
        mocker.register_uri(
            "GET",
            f"http://test/api/tests/?{urlencode(params)}",
            status_code=200,
            json=page,
        )
        yield mocker


def test_jsonapi_manager_sort() -> None:
    manager = JSONAPIManager(Dummy)
    manager_with_sort = manager.sort("field1", "field2")
    manager_with_extended_sort = manager_with_sort.sort("field3")
    assert manager._sort == []
    assert manager_with_sort._sort == ["field1", "field2"]
    assert manager_with_extended_sort._sort == ["field1", "field2", "field3"]


def test_jsonapi_manager_fields() -> None:
    manager = JSONAPIManager(Dummy)
    manager_with_fields = manager.fields(related=["field1", "field2"])
    manager_with_extended_fields = manager_with_fields.fields(other=["field1"])
    assert manager._fields == {}
    assert manager_with_fields._fields == {"related": ["field1", "field2"]}
    assert manager_with_extended_fields._fields == {
        "related": ["field1", "field2"],
        "other": ["field1"],
    }


def test_jsonapi_manager_include() -> None:
    manager = JSONAPIManager(Dummy)
    manager_with_include = manager.include("related1", "related2")
    manager_with_extended_include = manager_with_include.include("related3")
    assert manager._include == []
    assert manager_with_include._include == ["related1", "related2"]
    assert manager_with_extended_include._include == ["related1", "related2", "related3"]


def test_jsonapi_manager_filter() -> None:
    manager = JSONAPIManager(Dummy)
    manager_with_filters = manager.filter(pk=42)
    manager_with_extended_filters = manager_with_filters.filter(name="Test")
    assert manager._filters == {}
    assert manager_with_filters._filters == {"pk": 42}
    assert manager_with_extended_filters._filters == {"pk": 42, "name": "Test"}


def test_jsonapi_manager_iterator(pages: Mocker) -> None:
    manager = JSONAPIManager(Dummy)
    records = list(manager.iterator())
    assert len(records) == 48
    assert all(map(lambda x: isinstance(x, Dummy), records))
    assert list(map(lambda x: x.id, records)) == list(range(1, 49))


def test_jsonapi_manager_iterator_with_included() -> None:
    cache.clear()
    page = {
        "data": [
            {"id": "137", "type": "tests", "attributes": {}},
        ],
        "included": [
            {
                "id": "42",
                "type": "tests",
                "attributes": {
                    "field": "Included Record",
                },
            }
        ],
    }
    with Mocker() as mocker:
        params = {
            "include": "related",
            "fields[tests]": "field,related",
            "page[size]": 10,
            "page[number]": 1,
        }
        mocker.register_uri(
            "GET",
            f"http://test/api/tests/?{urlencode(params)}",
            status_code=200,
            json=page,
        )
        manager = JSONAPIManager(Dummy)
        list(manager.iterator())
    assert cache.get("jsonapi:tests:42").field == "Included Record"


def test_jsonapi_manager_all(pages: Mocker) -> None:
    manager = JSONAPIManager(Dummy)
    records = list(manager.all())
    assert len(records) == 48
    assert manager._cache == records
    pages.reset_mock()
    assert manager.all() == records
    assert not pages.called


@pytest.mark.parametrize(
    "status_code,page_number,expected_number_of_records",
    [
        (HTTP_404_NOT_FOUND, 3, 20),
        (HTTP_404_NOT_FOUND, 4, 30),
        (HTTP_404_NOT_FOUND, 1, None),
        (HTTP_500_INTERNAL_SERVER_ERROR, 3, None),
        (HTTP_400_BAD_REQUEST, 4, None),
    ],
)
def test_jsonapi_manager_all_handles_404_empty_page(
    pages: Mocker,
    status_code: int,
    page_number: int,
    expected_number_of_records: Optional[int],
) -> None:
    params = {
        "include": "related",
        "fields[tests]": "field,related",
        "page[size]": 10,
        "page[number]": page_number,
    }
    pages.register_uri(
        "GET",
        f"http://test/api/tests/?{urlencode(params)}",
        status_code=status_code,
    )
    manager = JSONAPIManager(Dummy)

    if expected_number_of_records is None:
        with pytest.raises(JSONAPIClientError):
            list(manager.all())
    else:
        records = list(manager.all())
        assert len(records) == expected_number_of_records


def test_jsonapi_manager_count() -> None:
    params = {
        "page[size]": 1,
        "filter[key]": "value",
    }
    with Mocker() as mocker:
        url = f"http://test/api/tests/?{urlencode(params)}"
        mocker.register_uri(
            "GET",
            url,
            status_code=200,
            json={
                "meta": {
                    "record_count": 137,
                }
            },
        )
        manager = JSONAPIManager(Dummy)
        assert manager.filter(key="value").count() == 137


def test_jsonapi_manager_getitem(pages: Mocker) -> None:
    manager = JSONAPIManager(Dummy)
    assert manager[5].pk == 6


def test_jsonapi_manager_iter(pages: Mocker) -> None:
    manager = JSONAPIManager(Dummy)
    assert len(list(iter(manager))) == 48
    assert manager._cache


def test_jsonapi_manager_bool_true(pages: Mocker) -> None:
    manager = JSONAPIManager(Dummy)
    result = bool(manager)
    expected = True
    assert result is expected


def test_jsonapi_manager_bool_false(empty_page: Mocker) -> None:
    manager = JSONAPIManager(Dummy)
    result = bool(manager)
    expected = False
    assert result is expected


def test_jsonapi_manager_get() -> None:
    cache.clear()
    document = {
        "data": {"id": "12", "type": "tests", "attributes": {}},
        "included": [
            {
                "id": "137",
                "type": "tests",
                "attributes": {"field": "Included Record"},
            }
        ],
    }

    with Mocker() as mocker:
        params = {
            "fields[tests]": "field,related",
            "include": "related",
        }
        url = f"http://test/api/tests/12/?{urlencode(params)}"
        mocker.register_uri(
            "GET",
            url,
            status_code=200,
            json=document,
        )
        manager = JSONAPIManager(Dummy)
        record = manager.get(pk=12)
        # Verify API call and result
        assert record.id == 12
        assert mocker.called
        assert mocker.last_request.url == url
        # Loads included in cache
        assert cache.get("jsonapi:tests:137").field == "Included Record"
        # Uses cache
        mocker.reset_mock()
        assert manager.get(pk=12) == record
        assert not mocker.called
        # Ignore cache
        assert manager.get(pk=12, ignore_cache=True) == record
        assert mocker.called
