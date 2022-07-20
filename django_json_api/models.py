from collections import defaultdict
from typing import Any, Dict, List, Optional, Type, TypeVar, Union

from django.conf import settings
from django.core.cache import cache

from django_json_api.base import JSONAPIModelBase

T = TypeVar("T", bound="JSONAPIModel")


class JSONAPIError(Exception):
    pass


def _find_model_class(resource_type: str) -> Type:
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
    def from_resource(resource_dict: dict, persist: Optional[bool] = True) -> T:
        cls = _find_model_class(resource_dict["type"])
        if cls:
            kwargs = {}
            data = {
                **resource_dict.get("attributes", {}),
                **{
                    name: value["data"]
                    for name, value in resource_dict.get("relationships", {}).items()
                    if "data" in value
                },
            }
            existing_cache = cls.from_cache(resource_dict["id"])
            for name, field in cls._meta.fields.items():
                try:
                    kwargs[name] = field.clean(data[name])
                except KeyError:
                    if existing_cache and hasattr(existing_cache, f"{name}_identifiers"):
                        kwargs[name] = getattr(existing_cache, f"{name}_identifiers")
                    elif existing_cache and hasattr(existing_cache, f"{name}_identifier"):
                        kwargs[name] = getattr(existing_cache, f"{name}_identifier")
            record = cls(id=resource_dict["id"], **kwargs)
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
                records.extend(
                    cls.cache_many([cls.from_resource(item, persist=False) for item in resources])
                )
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
    def from_cache(cls: Type[T], pk: Union[str, int]) -> T:
        return cache.get(cls.cache_key(pk))

    @classmethod
    def get_many(cls: Type[T], record_ids: List[Union[str, int]]) -> Dict:
        cache_keys = [cls.cache_key(pk) for pk in record_ids]
        records = {record.id: record for record in cache.get_many(cache_keys).values()}
        missing = set(map(int, filter(bool, record_ids))) - set(records)
        if missing:
            many_id_lookup = getattr(cls._meta, "many_id_lookup", None)
            if many_id_lookup:
                for item in cls.objects.filter(**{many_id_lookup: ",".join(map(str, missing))}):
                    records[item.id] = item
            else:
                for missing_id in missing:
                    records[missing_id] = cls.objects.get(pk=missing_id)
        return records

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
        cache.set_many(
            {instance.cache_key(instance.pk): instance for instance in instances}, cache_expiration
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
