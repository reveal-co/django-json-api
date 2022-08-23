from unittest import mock

from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import BaseSerializer

from django_json_api.client import JSONAPIClientError
from django_json_api.rest_framework import ModelSerializer, get_default_relation_serializer
from tests.models import DummyModel, DummyRelated


class DummySerializer(ModelSerializer):
    class Meta:
        model = DummyModel
        fields = ("id", "related")


class DummyWithExcludeSerializer(ModelSerializer):
    class Meta:
        model = DummyModel
        fields = ("id", "related")
        exclude_by_default = ("related",)


def test_get_default_relation_serializer():
    serializer_class = get_default_relation_serializer(DummyRelated)
    serializer = serializer_class(DummyRelated(pk=42, name="Test").cache())
    assert serializer.data == {"id": 42, "name": "Test"}


def test_get_default_relation_serializer_limit_fields():
    serializer_class = get_default_relation_serializer(DummyRelated, only_fields=[])
    serializer = serializer_class(DummyRelated(pk=42, name="Test").cache())
    assert serializer.data == {"id": 42}


class JsonAPISerializerTestCase(TestCase):
    def test_serialized_data(self):
        instance = DummyModel(pk=12, related=DummyRelated(pk=42).cache())
        serializer = DummySerializer(instance)
        assert serializer.data == {"id": 12, "related": {"type": "related_records", "id": "42"}}

    def test_included_serializers(self):
        serializers = DummySerializer.included_serializers
        self.assertIn("related", serializers)
        self.assertEqual(
            serializers["related"](DummyRelated(pk=42, name="Test")).data,
            {"id": 42, "name": "Test"},
        )

    def test_hide_default_excludes(self):
        instance = DummyModel(pk=12, related=DummyRelated(pk=42).cache())
        serializer = DummyWithExcludeSerializer(instance)
        self.assertEqual(serializer.data, {"id": 12})

    def test_show_default_excludes_if_included(self):
        instance = DummyModel(pk=12, related=DummyRelated(pk=42).cache())
        request = mock.Mock(
            query_params={
                "include": "related",
            }
        )
        serializer = DummyWithExcludeSerializer(instance, context={"request": request})
        self.assertEqual(
            serializer.data, {"id": 12, "related": {"type": "related_records", "id": "42"}}
        )

    def test_show_default_excludes_if_in_data(self):
        instance = DummyModel(pk=12, related=DummyRelated(pk=42).cache())
        serializer = DummyWithExcludeSerializer(instance, data={"related": instance.related})
        serializer.is_valid()
        self.assertEqual(
            serializer.data, {"id": 12, "related": {"type": "related_records", "id": "42"}}
        )

    def test_show_default_exclude_if_contexts_says_so(self):
        instance = DummyModel(pk=12, related=DummyRelated(pk=42).cache())
        request = mock.Mock(
            query_params={
                "fields[DummyModel]": "related",
            }
        )
        serializer = DummyWithExcludeSerializer(instance, context={"request": request})
        self.assertEqual(serializer.data, {"related": {"type": "related_records", "id": "42"}})

    def test_manually_include_excluded_by_default_fields(self):
        instance = DummyModel(pk=12, related=DummyRelated(pk=42).cache())
        serializer = DummyWithExcludeSerializer(instance, context={"include_fields": ["related"]})
        self.assertEqual(
            serializer.data, {"id": 12, "related": {"type": "related_records", "id": "42"}}
        )

    def test_is_valid_for_success(self):
        instance = DummyModel(pk=12, related=DummyRelated(pk=42).cache())
        serializer = DummySerializer(instance)

        with mock.patch.object(BaseSerializer, "is_valid") as patcher:
            self.assertEqual(serializer.is_valid(), patcher.return_value)

    def test_is_valid_for_failures(self):
        instance = DummyModel(pk=12, related=DummyRelated(pk=42).cache())
        serializer = DummySerializer(instance)

        for thrown, raised in [
            (KeyError, KeyError),
            (JSONAPIClientError(response=mock.Mock(status_code=500)), JSONAPIClientError),
            (JSONAPIClientError(response=mock.Mock(status_code=404)), ValidationError),
        ]:
            with self.subTest(thrown=thrown, raised=raised):
                with mock.patch.object(BaseSerializer, "is_valid", side_effect=thrown):
                    self.assertRaises(raised, serializer.is_valid)
