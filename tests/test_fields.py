from datetime import datetime, timezone
from unittest import mock

from django_json_api.fields import (
    Attribute,
    AttributeDescriptor,
    DateTimeAttribute,
    Relationship,
    RelationshipDescriptor,
    get_model,
    is_identifier,
)
from tests.models import Dummy, DummyRelated


def test_is_identifier():
    assert not is_identifier("anything")
    assert not is_identifier({})
    assert not is_identifier({"id": 42})
    assert not is_identifier({"type": "tests"})
    assert is_identifier({"id": 42, "type": "tests"})


def test_get_model():
    assert get_model("related_records") == DummyRelated
    assert get_model("unknown") is None


class EmptyClass:
    pass


def test_attribute_contribute_to_class():
    attribute = Attribute()
    attribute.contribute_to_class(EmptyClass, "attribute")
    assert hasattr(EmptyClass, "attribute")
    assert isinstance(EmptyClass.attribute, AttributeDescriptor)
    assert attribute.name == "attribute"
    assert attribute.model == EmptyClass
    delattr(EmptyClass, "attribute")


def test_attribute_clean():
    attribute = Attribute()
    assert attribute.clean("42") == "42"
    assert attribute.clean({42: "value"}) == {"42": "value"}


def test_datetime_attribute_clean():
    attribute = DateTimeAttribute()
    assert attribute.clean("2020-02-15T01:23:45+00:00") == datetime(
        2020, 2, 15, 1, 23, 45, tzinfo=timezone.utc
    )
    assert attribute.clean(42) is None


def test_relationship_contribute_to_class():
    relation = Relationship()
    relation.contribute_to_class(EmptyClass, "relation")
    assert hasattr(EmptyClass, "relation")
    assert isinstance(EmptyClass.relation, RelationshipDescriptor)
    assert relation.name == "relation"
    assert relation.model == EmptyClass
    delattr(EmptyClass, "relation")


def test_relationship_many_clean():
    relation = Relationship(many=True)
    raw = [
        {"id": "12", "type": "tests"},
        {},
        {"id": "42", "type": "tests"},
    ]
    assert relation.clean(raw) == [{"id": "12", "type": "tests"}, {"id": "42", "type": "tests"}]
    assert relation.clean(None) is None
    assert relation.clean([]) == []


def test_relationship_single_clean():
    relation = Relationship(many=False)
    raw = {"id": "12", "type": "tests"}
    assert relation.clean(raw) == raw
    assert relation.clean([raw]) == raw
    assert relation.clean(None) is None
    assert relation.clean("anything") is None
    assert relation.clean(["anything"]) is None


def test_relationship_descriptor_many_set():
    relation = Relationship(many=True)
    relation.contribute_to_class(EmptyClass, "relation")
    instance = EmptyClass()
    # Identifier
    identifiers = [{"id": "12", "type": "tests"}]
    instance.relation = identifiers
    assert instance.relation_identifiers == identifiers
    instance.relation = [Dummy(pk=12)]
    assert instance.relation_identifiers == identifiers
    delattr(EmptyClass, "relation")


def test_relationship_descriptor_single_set():
    relation = Relationship(many=False)
    relation.contribute_to_class(EmptyClass, "relation")
    instance = EmptyClass()
    # Identifier
    identifier = {"id": "12", "type": "tests"}
    instance.relation = identifier
    assert instance.relation_identifier == identifier
    instance.relation = Dummy(pk=12)
    assert instance.relation_identifier == identifier
    delattr(EmptyClass, "relation")


def test_relationship_descriptor_get_on_class():
    relation = Relationship()
    relation.contribute_to_class(EmptyClass, "relation")
    assert isinstance(EmptyClass.relation, RelationshipDescriptor)
    delattr(EmptyClass, "relation")


def test_relationship_descriptor_get_from_cache():
    relation = Relationship()
    relation.contribute_to_class(EmptyClass, "relation")
    instance = EmptyClass()
    setattr(instance, "_relation_cache", "Cached Value")
    assert instance.relation == "Cached Value"
    delattr(EmptyClass, "relation")


def test_relationship_descriptor_many_get_refresh_from_api():
    relation = Relationship(many=True)
    relation.contribute_to_class(EmptyClass, "relation")
    instance = EmptyClass()
    instance.refresh_from_api = mock.Mock()
    instance.relation
    instance.refresh_from_api.assert_called_once()
    delattr(EmptyClass, "relation")


def test_relationship_descriptor_single_get_refresh_from_api():
    relation = Relationship(many=False)
    relation.contribute_to_class(EmptyClass, "relation")
    instance = EmptyClass()
    instance.refresh_from_api = mock.Mock()
    instance.relation
    instance.refresh_from_api.assert_called_once()
    delattr(EmptyClass, "relation")


def test_relationship_descriptor_single_get():
    relation = Relationship(many=False)
    relation.contribute_to_class(EmptyClass, "relation")
    with mock.patch("django_json_api.fields.get_model") as get_model:
        instance = EmptyClass()
        instance.relation_identifier = {"id": "42", "type": "tests"}
        assert instance.relation == get_model.return_value.objects.get.return_value
        get_model.assert_called_once_with("tests")
        get_model.return_value.objects.get.assert_called_once_with(pk="42")
        assert hasattr(instance, "_relation_cache")
    delattr(EmptyClass, "relation")


def test_relationship_descriptor_many_get():
    relation = Relationship(many=True)
    relation.contribute_to_class(EmptyClass, "relation")
    with mock.patch("django_json_api.fields.get_model") as get_model:
        instance = EmptyClass()
        instance.relation_identifiers = [{"id": "42", "type": "tests"}]
        dummy_42 = Dummy(pk=42)
        get_model.return_value.get_many.return_value = {
            42: dummy_42,
        }
        assert instance.relation == [dummy_42]
        get_model.assert_called_once_with("tests")
        get_model.return_value.get_many.assert_called_once_with(record_ids=["42"])
        assert hasattr(instance, "_relation_cache")
    delattr(EmptyClass, "relation")
