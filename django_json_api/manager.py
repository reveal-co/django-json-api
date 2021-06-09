from copy import deepcopy
from typing import Iterator, List, Union

from rest_framework.status import HTTP_404_NOT_FOUND

from django_json_api.client import JSONAPIClient, JSONAPIClientError


class JSONAPIManager:
    def __init__(self, model, **kwargs):
        self.client = JSONAPIClient()
        self.model = model
        self._fields = kwargs.get("fields", {})
        self._include = kwargs.get("include", [])
        self._filters = kwargs.get("filters", {})
        self._sort = kwargs.get("sort", [])
        self._cache = None

    def modify(self, **kwargs) -> "JSONAPIManager":
        _fields = {
            **self._fields,
            **kwargs.get("fields", {}),
        }
        _filters = {
            **self._filters,
            **kwargs.get("filters", {}),
        }
        _include = deepcopy(self._include)
        _include.extend(list(kwargs.get("include", [])))
        _sort = deepcopy(self._sort)
        _sort.extend(list(kwargs.get("sort", [])))
        return JSONAPIManager(
            model=self.model,
            fields=_fields,
            filters=_filters,
            include=_include,
            sort=_sort,
        )

    def sort(self, *args) -> "JSONAPIManager":
        return self.modify(sort=args)

    def filter(self, **kwargs) -> "JSONAPIManager":
        return self.modify(filters=kwargs)

    def include(self, *args) -> "JSONAPIManager":
        return self.modify(include=args)

    def fields(self, **kwargs) -> "JSONAPIManager":
        return self.modify(fields=kwargs)

    @property
    def resource_type(self) -> str:
        return self.model._meta.resource_type

    def _fetch_get(self, resource_id: Union[str, int] = None) -> dict:
        return self.client.get(
            self.resource_type,
            resource_id=resource_id,
            filters=self._filters,
            include=self._include or None,
            fields=self._fields,
            sort=self._sort,
        )

    def _fetch_iterate(self) -> Iterator:
        client = JSONAPIClient()
        client.session.headers["X-No-Count"] = "true"
        page_size = getattr(self.model._meta, "page_size", 50)
        page_number = 1
        while True:
            try:
                page = client.get(
                    self.resource_type,
                    filters=self._filters,
                    include=self._include or None,
                    fields=self._fields,
                    sort=self._sort,
                    page_size=page_size,
                    page_number=page_number,
                )
            except JSONAPIClientError as error:
                if not (page_number > 1 and error.response.status_code == HTTP_404_NOT_FOUND):
                    raise error
                break

            included = page.get("included") or []
            data = page.get("data")
            number_records = len(data)

            page_number += 1
            self.model.from_resources(included)
            yield from self.model.from_resources(data)
            if number_records < page_size:
                break

    def _fetch_all(self) -> List["JSONAPIModel"]:  # noqa
        if self._cache is None:
            self._cache = list(self._fetch_iterate())
        return self._cache

    def count(self) -> int:
        data = self.client.get(
            self.resource_type,
            include=[],
            fields={self.resource_type: []},
            filters=self._filters,
            page_size=1,
        )
        return data.get("meta", {}).get("record_count")

    def iterator(self) -> Iterator["JSONAPIModel"]:  # noqa
        return self._fetch_iterate()

    def all(self) -> List["JSONAPIModel"]:  # noqa
        return self._fetch_all()

    def get(self, pk, ignore_cache=False) -> "JSONAPIModel":  # noqa
        record = self.model.from_cache(pk)
        if record is None or ignore_cache:
            document = self._fetch_get(resource_id=pk)
            data = document["data"]
            record = self.model.from_resource(data)
            self.model.from_resources(document.get("included") or [])
        return record

    def __getitem__(self, k) -> "JSONAPIModel":  # noqa
        self._fetch_all()
        return self._cache[k]

    def __iter__(self) -> Iterator["JSONAPIModel"]:  # noqa
        self._fetch_all()
        return iter(self._cache)

    def __bool__(self: "JSONAPIManager") -> bool:
        self._fetch_all()
        return bool(self._cache)
