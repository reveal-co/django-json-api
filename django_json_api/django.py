from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, Type

from django.db.models import Manager, Model, QuerySet
from django.db.models.fields import IntegerField
from django.db.models.query import ModelIterable

__all__ = ("RelatedJSONAPIField",)


from django_json_api.models import JSONAPIModel


class RelatedJSONAPIDescriptor:
    def __init__(self, field):
        self.field = field

    def __get__(self, instance, cls=None):
        if instance is None:
            return self

        cached = getattr(instance, f"_cache_{self.field.name}", None)
        if cached:
            return cached

        _model = self.field.json_api_model
        _pk = getattr(instance, self.field.get_attname(), None)
        if not _pk:
            return None

        value = _model.objects.get(pk=_pk)
        setattr(instance, f"_cache_{self.field.name}", value)
        return value

    def __set__(self, instance, value):
        if value is not None:
            if not isinstance(value, self.field.json_api_model):
                raise ValueError(
                    "Cannot assign {}: {}.{} must be a {} instance".format(
                        value,
                        instance._meta.object_name,
                        self.field.name,
                        self.field.json_api_model.__name__,
                    )
                )
            if not value.pk:
                raise ValueError(
                    "Cannot assign {} without pk to {}.{}".format(
                        self.field.json_api_model.__name__,
                        instance._meta.object_name,
                        self.field.name,
                    )
                )
            setattr(instance, self.field.get_attname(), value.pk)
        else:
            setattr(instance, self.field.get_attname(), None)

        setattr(instance, f"_cache_{self.field.name}", value)


class RelatedJSONAPIField(IntegerField):
    description = "Field for JSON API External Relations"

    def __init__(
        self: "RelatedJSONAPIField", json_api_model: Optional[Type[JSONAPIModel]] = None, **kwargs
    ):
        kwargs.pop("rel", None)
        super().__init__(**kwargs)
        self.json_api_model = json_api_model

    @property
    def validators(self):
        return []

    def get_attname(self):
        return f"{self.name}_id"

    def get_attname_column(self):
        attname = self.get_attname()
        column = self.db_column or attname
        return attname, column

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["json_api_model"] = self.json_api_model
        return name, path, args, kwargs

    def contribute_to_class(self, cls, name, private_only=False):
        super().contribute_to_class(cls, name, private_only=private_only)
        setattr(cls, self.name, RelatedJSONAPIDescriptor(self))

    def to_python(self, value):
        if value is None:
            return None
        return self.json_api_model(pk=value)


def get_jsonapi_id(source: Model, path: str) -> Optional[Any]:
    splitted_path = path.split("__")
    attr = splitted_path.pop(-1)
    current_source = source
    for relation in splitted_path:
        current_source = getattr(current_source, relation, None)
    return getattr(current_source, f"{attr}_id", None)


def set_prefetched_value(source: Model, path: str, value: Any) -> None:
    splitted_path = path.split("__")
    attr = splitted_path.pop(-1)
    current_source = source
    for relation in splitted_path:
        current_source = getattr(current_source, relation, None)
        if current_source is None:
            return
    setattr(current_source, f"_cache_{attr}", value)


def prefetch_jsonapi(model_instances: List[Model], related_lookups: Dict):
    data_to_prefetch = defaultdict(set)
    resource_to_prefetch_lookups = defaultdict(list)

    models = {}
    for path, json_api_model_and_lookups in related_lookups.items():
        json_api_model, prefetch_lookups = json_api_model_and_lookups
        models[json_api_model._meta.resource_type] = json_api_model
        resource_to_prefetch_lookups[json_api_model._meta.resource_type].extend(prefetch_lookups)

        for instance in model_instances:
            value = get_jsonapi_id(instance, path)
            if value:
                data_to_prefetch[json_api_model._meta.resource_type].add(value)

    prefetched_data = {
        resource_type: models[resource_type].get_many(
            record_ids, prefetch_related=resource_to_prefetch_lookups[resource_type]
        )
        for resource_type, record_ids in data_to_prefetch.items()
    }

    for instance in model_instances:
        for attr, json_api_model_and_lookups in related_lookups.items():
            json_api_model, _ = json_api_model_and_lookups
            records = prefetched_data.get(json_api_model._meta.resource_type, {})
            set_prefetched_value(instance, attr, records.get(get_jsonapi_id(instance, attr)))


def model_and_prefetch_from_related_path(
    model: Type[Model], path: str
) -> Tuple[str, JSONAPIModel, List[str]]:
    current_model = model
    for index, relation in enumerate(path.split("__")):
        relation_field = current_model._meta.get_field(relation)
        if hasattr(relation_field, "json_api_model"):
            splitted_path = path.split("__", index + 1)
            return (
                "__".join(splitted_path[: index + 1]),
                relation_field.json_api_model,
                splitted_path[index + 1 :],
            )
        current_model = relation_field.related_model
    raise ValueError(f"path {path} does not include valid JSONAPIModel")


class WithJSONApiQuerySet(QuerySet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._prefetch_jsonapi_lookups = {}
        self._prefetched_jsonapi = False

    def _clone(self):
        clone = super()._clone()
        clone._prefetch_jsonapi_lookups = self._prefetch_jsonapi_lookups.copy()
        return clone

    def prefetch_jsonapi(self, *lookups):
        clone = self._clone()
        for related in lookups:
            path, json_api_model, lookup_to_prefetch = model_and_prefetch_from_related_path(
                self.model,
                related,
            )
            if path in clone._prefetch_jsonapi_lookups:
                clone._prefetch_jsonapi_lookups[path][1].extend(lookup_to_prefetch)
            else:
                clone._prefetch_jsonapi_lookups[path] = (
                    json_api_model,
                    lookup_to_prefetch,
                )
        return clone

    def _do_prefetch_jsonapi(self):
        if issubclass(self._iterable_class, ModelIterable):
            prefetch_jsonapi(self._result_cache, self._prefetch_jsonapi_lookups)
            self._prefetched_jsonapi = True

    def _fetch_all(self):
        super()._fetch_all()
        if self._prefetch_jsonapi_lookups and not self._prefetched_jsonapi:
            self._do_prefetch_jsonapi()


WithJSONApiManager = Manager.from_queryset(WithJSONApiQuerySet)
