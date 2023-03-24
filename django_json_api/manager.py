import typing
from collections import defaultdict
from copy import deepcopy
from typing import Dict, Iterator, List, Set, Union

from rest_framework.status import HTTP_404_NOT_FOUND

from django_json_api.client import JSONAPIClient, JSONAPIClientError

if typing.TYPE_CHECKING:
    from django_json_api.models import JSONAPIModel


def get_base_lookup_to_nested_lookups_mapping(lookups: List[str]) -> Dict[str, List[str]]:
    base_lookup_to_nested_lookups = defaultdict(list)
    for lookup in lookups:
        base, *nested_path = lookup.split("__", 1)
        base_lookup_to_nested_lookups[base].extend(nested_path)
    return base_lookup_to_nested_lookups


class JSONAPIManager:
    def __init__(self, model, **kwargs):
        self.client = JSONAPIClient(auth=model._meta.auth)
        self.model = model
        self._fields = kwargs.get("fields", {})
        self._prefetch_related = kwargs.get("prefetch_related", [])
        self._include = kwargs.get("include", [])
        self._include = sorted(list(set(self._include) | self._prepared_prefetch_for_include))
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
        _prefetch_related = deepcopy(self._prefetch_related)
        _prefetch_related.extend(list(kwargs.get("prefetch_related", [])))
        _sort = deepcopy(self._sort)
        _sort.extend(list(kwargs.get("sort", [])))
        return JSONAPIManager(
            model=self.model,
            fields=_fields,
            filters=_filters,
            include=_include,
            sort=_sort,
            prefetch_related=_prefetch_related,
        )

    def sort(self, *args) -> "JSONAPIManager":
        return self.modify(sort=args)

    def filter(self, **kwargs) -> "JSONAPIManager":
        return self.modify(filters=kwargs)

    def include(self, *args) -> "JSONAPIManager":
        return self.modify(include=args)

    def prefetch_related(self, *args) -> "JSONAPIManager":
        return self.modify(prefetch_related=args)

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
            included_records = self.model.from_resources(included)
            records = self.model.from_resources(data)
            yield from self._enrich_records_with_included_resources(records, included_records)
            if number_records < page_size:
                break

    def _fetch_all(self) -> List["JSONAPIModel"]:  # noqa
        if self._cache is None:
            self._cache = list(self._fetch_iterate())
        return self._cache

    @property
    def _prepared_prefetch_for_include(self) -> Set[str]:
        prepared = set()
        for item in self._prefetch_related:
            elements = item.split("__")
            current_chain = []
            for element in elements:
                current_chain.append(element)
                prepared.add(".".join(current_chain))
        return prepared

    def _enrich_records_with_included_resources(
        self,
        records: List["JSONAPIModel"],
        included_records: List["JSONAPIModel"],
    ) -> List["JSONAPIModel"]:
        if self._prefetch_related:
            included_records_mapping = self._group_resources_by_type(included_records)
            records = self._set_cache_value_on_records(
                records, self._prefetch_related, included_records_mapping
            )
        return records

    def _set_cache_value_on_records(
        self,
        records: List["JSONAPIModel"],
        prefetch_lookups: List[str],
        included_records_mapping: Dict[str, Dict[str, "JSONAPIModel"]],
    ) -> List["JSONAPIModel"]:
        base_lookup_to_nested_lookups = get_base_lookup_to_nested_lookups_mapping(prefetch_lookups)
        for relationship, nested_prefetch in base_lookup_to_nested_lookups.items():
            nested_records = []
            for record in records:
                if hasattr(record, f"{relationship}_identifiers"):
                    result = [
                        included_records_mapping[resource["type"]][resource["id"]]
                        for resource in getattr(record, f"{relationship}_identifiers")
                    ]
                    nested_records.extend(result)
                elif hasattr(record, f"{relationship}_identifier"):
                    resource = getattr(record, f"{relationship}_identifier")
                    result = included_records_mapping[resource["type"]][resource["id"]]
                    nested_records.append(result)
                else:
                    continue
                setattr(record, f"_{relationship}_cache", result)
            self._set_cache_value_on_records(
                nested_records, nested_prefetch, included_records_mapping
            )

        return records

    @staticmethod
    def _group_resources_by_type(
        records: List["JSONAPIModel"],
    ) -> Dict[str, Dict[str, "JSONAPIModel"]]:
        records_mapping = defaultdict(dict)
        for record in records:
            records_mapping[record._meta.resource_type][str(record.pk)] = record
        return records_mapping

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
            included_records = self.model.from_resources(document.get("included") or [])
            record = self._enrich_records_with_included_resources(
                [self.model.from_resource(data)],
                included_records,
            )[0]
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
