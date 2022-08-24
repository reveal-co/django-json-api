import typing
from typing import Optional, Type

from dateutil.parser import parse

if typing.TYPE_CHECKING:
    from django_json_api.models import JSONAPIModel


def is_identifier(value):
    return isinstance(value, dict) and "id" in value and "type" in value


def get_identifier(value):
    from django_json_api.models import JSONAPIModel

    if is_identifier(value):
        return value
    if isinstance(value, JSONAPIModel):
        return {"id": str(value.id), "type": value._meta.resource_type}
    return None


def get_model(resource_type: str) -> Optional[Type["JSONAPIModel"]]:
    from django_json_api.models import JSONAPIModel

    for klass in JSONAPIModel.__subclasses__():
        if klass._meta.resource_type == resource_type:
            return klass
    return None


class AttributeDescriptor:
    def __init__(self, field):
        self.field = field

    def __get__(self, obj, obj_type=None):
        if obj is None:
            return self
        return obj.__dict__.get(self.field.name)

    def __set__(self, obj, value):
        obj.__dict__[self.field.name] = value


class RelationshipDescriptor:
    def __init__(self, field):
        self.field = field

    def __get__(self, obj, obj_type=None):
        if obj is None:
            return self
        if hasattr(obj, f"_{self.field.name}_cache"):
            return getattr(obj, f"_{self.field.name}_cache")
        if self.field.many:
            if not hasattr(obj, f"{self.field.name}_identifiers"):
                obj.refresh_from_api()
            identifiers = getattr(obj, f"{self.field.name}_identifiers", [])
            resource_type = identifiers[0]["type"] if identifiers else None
            resource_model = get_model(resource_type) if resource_type else None
            result = (
                list(
                    resource_model.get_many(
                        record_ids=[resource["id"] for resource in identifiers]
                    ).values()
                )
                if resource_model is not None
                else []
            )
        else:
            if not hasattr(obj, f"{self.field.name}_identifier"):
                obj.refresh_from_api()
            identifier = getattr(obj, f"{self.field.name}_identifier", None)
            result = (
                get_model(identifier["type"]).objects.get(pk=identifier["id"])
                if identifier is not None
                else None
            )
        setattr(obj, f"_{self.field.name}_cache", result)
        return result

    def __set__(self, obj, value):
        if self.field.many:
            setattr(obj, f"{self.field.name}_identifiers", list(map(get_identifier, value or [])))
        else:
            setattr(obj, f"{self.field.name}_identifier", get_identifier(value))


class Attribute:
    def __init__(self, name=None, model=None):
        self.name = name
        self.model = model

    def contribute_to_class(self, model, name):
        self.name = self.name or name
        self.model = model
        setattr(model, name, AttributeDescriptor(self))
        return self

    def clean(self, value):
        if isinstance(value, dict):
            return dict((str(attr), self.clean(val)) for attr, val in value.items())
        return value


class DateTimeAttribute(Attribute):
    def clean(self, value):
        return parse(value) if isinstance(value, str) else None


class Relationship(Attribute):
    def __init__(self, many=False, **kwargs):
        super().__init__(**kwargs)
        self.many = many

    def contribute_to_class(self, model, name):
        super().contribute_to_class(model, name)
        setattr(model, name, RelationshipDescriptor(self))
        return self

    def clean(self, value):
        if self.many and value is not None:
            return list(filter(bool, map(get_identifier, value)))
        if value:
            if isinstance(value, list):
                value = value[0]
            return get_identifier(value)
        return None
