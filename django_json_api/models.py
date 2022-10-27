from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple, Type, TypeVar, Union

from django.conf import settings
from django.core.cache import cache

from django_json_api.base import JSONAPIModelBase
from django_json_api.fields import Relationship
from django_json_api.manager import get_base_lookup_to_nested_lookups_mapping

T = TypeVar("T", bound="JSONAPIModel")


class JSONAPIError(Exception):
    pass


def _find_model_class(resource_type: str) -> Optional[Type["JSONAPIModel"]]:
    for cls in JSONAPIModel.__subclasses__():
        if resource_type == cls._meta.resource_type:
            return cls
    return None


class JSONAPIModel(metaclass=JSONAPIModelBase):
    def __init__(self: T, **kwargs: int) -> None:
        self.pk = kwargs.pop("pk", None) or kwargs.pop("id", None)
        if self.pk is not None:
            self.pk = int(self.pk)
        for key, value in kwargs.items():
            if key not in self._meta.fields:
                raise TypeError(
                    f'{self.__class__.__name__} got an unexpected keyword argument "{key}"'
                )
            setattr(self, key, value)
        super().__init__()

    def __eq__(self: T, other: Any) -> bool:
        if self.__class__ != other.__class__:
            return False
        my_pk = self.pk
        if my_pk is None:
            return self is other
        return int(my_pk) == int(other.pk)

    @property
    def id(self: T) -> int:
        return self.pk

    @staticmethod
    def from_resource(resource_dict: dict, persist: Optional[bool] = True) -> Optional[T]:
        cls = _find_model_class(resource_dict["type"])
        if cls:
            existing_cache = cls.from_cache(resource_dict["id"])
            record = cls._merge_resource_with_existing_cache(resource_dict, existing_cache)
            if persist:
                record.cache()
            return record
        return None

    @staticmethod
    def from_resources(resource_dicts: List[Dict]) -> List[T]:
        grouped_records = defaultdict(list)
        for record in resource_dicts:
            grouped_records[record["type"]].append(record)

        records = []
        for resource_type, resources in grouped_records.items():
            cls = _find_model_class(resource_type)
            if cls:
                resource_ids = [resource["id"] for resource in resources]
                cached_records = cls._get_many_from_cache(resource_ids)
                records_batch = [
                    cls._merge_resource_with_existing_cache(
                        resource,
                        cached_records.get(int(resource["id"])),
                    )
                    for resource in resources
                ]
                cls.cache_many(records_batch)
                records.extend(records_batch)
        return records

    @classmethod
    def cache_key(cls: Type[T], pk: Union[str, int]) -> str:
        resource_type = cls._meta.resource_type
        cache_key_version = getattr(settings, "DJANGO_JSON_API_CACHE_KEY_VERSION", None)
        if cache_key_version:
            versioned_resource_type = f"{resource_type}:{cache_key_version}"
            return f"jsonapi:{versioned_resource_type}:{pk}"
        return f"jsonapi:{resource_type}:{pk}"

    @classmethod
    def from_cache(cls: Type[T], pk: Union[str, int]) -> Optional[T]:
        return cache.get(cls.cache_key(pk))

    @classmethod
    def get_many(cls: Type[T], record_ids: List[Union[str, int]], prefetch_related=None) -> Dict:
        _prefetch_related = prefetch_related or []
        cached_records = cls._get_many_from_cache(record_ids)
        missing = set(map(int, filter(bool, record_ids))) - set(cached_records)
        records, records_to_re_fetch = cls._handle_prefetching(cached_records, _prefetch_related)
        missing.update(records_to_re_fetch)

        if missing:
            many_id_lookup = getattr(cls._meta, "many_id_lookup", None)
            if many_id_lookup:
                for item in cls.objects.prefetch_related(*_prefetch_related).filter(
                    **{many_id_lookup: ",".join(map(str, missing))}
                ):
                    records[item.id] = item
            else:
                for missing_id in missing:
                    records[missing_id] = cls.objects.prefetch_related(*_prefetch_related).get(
                        pk=missing_id
                    )
        return records

    @classmethod
    def _handle_prefetching(
        cls: Type[T],
        records: Dict[int, "JSONAPIModel"],
        prefetch_related: List[str],
    ) -> Tuple[Dict[int, "JSONAPIModel"], Set[int]]:
        to_re_fetch = set()
        base_lookup_to_nested_lookups = get_base_lookup_to_nested_lookups_mapping(prefetch_related)

        for relationship, nested_relations_to_prefetch in base_lookup_to_nested_lookups.items():
            identifiers_to_fetch: Set[Tuple[str, str]] = set()
            record_ids_to_related_ids = {}
            relation = getattr(cls, relationship, None)
            if relation is None or not isinstance(relation.field, Relationship):
                continue
            many_lookup = relation.field.many
            for record in records.values():
                if many_lookup and hasattr(record, f"{relationship}_identifiers"):
                    identifiers = getattr(record, f"{relationship}_identifiers")
                    identifiers_to_fetch.update(
                        {(identifier["type"], identifier["id"]) for identifier in identifiers}
                    )
                    record_ids_to_related_ids[record.pk] = [
                        int(resource["id"]) for resource in identifiers
                    ]
                elif hasattr(record, f"{relationship}_identifier"):
                    resource = getattr(record, f"{relationship}_identifier")
                    identifiers_to_fetch.add((resource["type"], resource["id"]))
                    record_ids_to_related_ids[record.pk] = int(resource["id"])
                else:
                    to_re_fetch.add(record.pk)

            resource_type = list(identifiers_to_fetch)[0][0] if identifiers_to_fetch else None
            model_class = _find_model_class(resource_type) if resource_type else None
            results = (
                model_class.get_many(
                    record_ids=[resource[1] for resource in identifiers_to_fetch],
                    prefetch_related=nested_relations_to_prefetch,
                )
                if model_class
                else {}
            )
            for record in records.values():
                if many_lookup:
                    related_ids = record_ids_to_related_ids.get(record.pk) or []
                    cache_value = [
                        results[related_id] for related_id in related_ids if related_id in results
                    ]
                else:
                    related_id = record_ids_to_related_ids.get(record.pk)
                    cache_value = results.get(related_id) if related_id else None
                setattr(record, f"_{relationship}_cache", cache_value)
        return records, to_re_fetch

    def cache(self: T) -> T:
        cache_expiration = getattr(self._meta, "cache_expiration", 24 * 60 * 60)
        cache.set(
            self.cache_key(self.pk),
            self,
            timeout=cache_expiration,
        )
        return self

    @classmethod
    def cache_many(cls: Type[T], instances: List[T]) -> List[T]:
        cache_expiration = getattr(cls._meta, "cache_expiration", 24 * 60 * 60)
        if cache_expiration is None or (cache_expiration > 0):
            cache.set_many(
                {instance.cache_key(instance.pk): instance for instance in instances},
                cache_expiration,
            )
        return instances

    def refresh_from_api(self: T) -> None:
        fresh = self.objects.get(pk=self.pk, ignore_cache=True)
        self.__dict__ = fresh.__dict__
        self.cache()

    def save(self: T, update_fields: Optional[List[str]] = None) -> T:
        if self.pk is None:
            raise JSONAPIError("Record creation not supported")

        if update_fields is None:
            raise JSONAPIError("Argument update_fields needed to update record")

        resource_type: str = self.JSONAPIMeta.resource_name

        non_allowed_fields = list(set(update_fields).difference(set(self._meta.fields)))
        if len(non_allowed_fields) > 0:
            raise JSONAPIError(
                f"Fields {non_allowed_fields} not present on resource {resource_type}"
            )

        update_data = {field: getattr(self, field) for field in update_fields}

        update_record = self.objects.client.patch(
            resource_type=self.JSONAPIMeta.resource_name,
            resource_id=self.pk,
            attributes=update_data,
        )
        return self.from_resource(update_record["data"])

    @classmethod
    def _get_many_from_cache(cls: Type[T], record_ids: List[int]) -> Dict[int, T]:
        cache_expiration = getattr(cls._meta, "cache_expiration", None)
        if cache_expiration == 0:
            return {}
        cache_keys = [cls.cache_key(pk) for pk in record_ids]
        cached_records = {record.id: record for record in cache.get_many(cache_keys).values()}
        return cached_records

    @classmethod
    def _merge_resource_with_existing_cache(
        cls: Type[T], resource_dict: Dict, existing_cache: Optional[T]
    ) -> T:
        kwargs = {}
        data = {
            **resource_dict.get("attributes", {}),
            **{
                name: value["data"]
                for name, value in resource_dict.get("relationships", {}).items()
                if "data" in value
            },
        }
        for name, field in cls._meta.fields.items():
            try:
                kwargs[name] = field.clean(data[name])
            except KeyError:
                if existing_cache and hasattr(existing_cache, f"{name}_identifiers"):
                    kwargs[name] = getattr(existing_cache, f"{name}_identifiers")
                elif existing_cache and hasattr(existing_cache, f"{name}_identifier"):
                    kwargs[name] = getattr(existing_cache, f"{name}_identifier")
        record = cls(id=resource_dict["id"], **kwargs)
        return record
