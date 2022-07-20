from unittest import TestCase, mock

import pytest
from django.core.cache import cache
from django.test import override_settings

from django_json_api.models import JSONAPIError, JSONAPIModel
from tests.models import Dummy


class JSONAPIModelBaseTestCase(TestCase):
    def setUp(self):
        cache.clear()
        return super().setUp()

    def test_cache_key__no_version(self):
        self.assertEqual(Dummy.cache_key(42), "jsonapi:tests:42")

    @override_settings(DJANGO_JSON_API_CACHE_KEY_VERSION="v2")
    def test_cache_key__with_version(self):
        self.assertEqual(Dummy.cache_key(42), "jsonapi:tests:v2:42")

    def test_eq(self):
        self.assertEqual(
            Dummy(pk=12),
            Dummy(pk=12, field="test"),
        )
        self.assertNotEqual(Dummy(pk=12), 42)
        empty = Dummy()
        self.assertEqual(empty, empty)
        self.assertNotEqual(empty, Dummy())

    def test_init(self):
        model = Dummy(pk="12", field="test", related={"id": "12", "type": "tests"})
        self.assertEqual(model.id, 12)
        self.assertEqual(model.field, "test")
        self.assertEqual(model.related_identifier, {"id": "12", "type": "tests"})

    def test_init_bad_kwargs(self):
        with self.assertRaises(TypeError):
            Dummy(unknown="test")

    def test_cache(self):
        instance = Dummy(pk=12)
        instance.cache()
        self.assertEqual(cache.get(Dummy.cache_key(12)), instance)

    def test_from_cache(self):
        instance = Dummy(pk=12)
        cache.set(Dummy.cache_key(instance.pk), instance)
        self.assertEqual(
            instance,
            Dummy.from_cache(instance.pk),
        )

    def test_get_many(self):
        _manager = Dummy.objects
        cached_instance = Dummy(pk=12)
        cache.set(Dummy.cache_key(cached_instance.pk), cached_instance)
        non_cached_instance = Dummy(pk=137)
        Dummy.objects = mock.Mock()
        # Fetch one by one
        Dummy.objects.get.return_value = non_cached_instance
        self.assertEqual(
            {12: cached_instance, 137: non_cached_instance},
            Dummy.get_many([12, 137]),
        )
        Dummy.objects.get.assert_called_once_with(pk=137)
        # Group Fetch
        Dummy.objects.filter.return_value = [non_cached_instance]
        Dummy._meta.many_id_lookup = "id"
        self.assertEqual(
            {12: cached_instance, 137: non_cached_instance},
            Dummy.get_many([12, 137]),
        )
        Dummy.objects.filter.assert_called_once_with(id="137")
        Dummy.objects = _manager
        delattr(Dummy._meta, "many_id_lookup")

    def test_refresh_from_api(self):
        _manager = Dummy.objects
        Dummy.objects = mock.Mock()
        Dummy.objects.get.return_value = Dummy(pk=12, field="other")
        instance = Dummy(pk=12, field="test")
        instance.cache()
        instance.refresh_from_api()
        Dummy.objects = _manager
        self.assertEqual(instance.field, "other")
        self.assertEqual(Dummy.from_cache(12).field, "other")

    def test_from_resource(self):
        resource = {
            "type": "tests",
            "id": "137",
            "attributes": {
                "field": "Example",
            },
            "relationships": {
                "related": {
                    "data": {
                        "id": "12",
                        "type": "tests",
                    }
                }
            },
        }
        record = JSONAPIModel.from_resource(resource)
        self.assertIsInstance(record, Dummy)
        self.assertEqual(record.id, 137)
        self.assertEqual(record.field, "Example")
        self.assertEqual(record.related_identifier, {"id": "12", "type": "tests"})

    def test_from_resource_unknown(self):
        resource = {
            "type": "unknown",
            "id": "137",
        }
        self.assertIsNone(JSONAPIModel.from_resource(resource))

    def test_from_resource_missing_fields(self):
        resource = {
            "type": "tests",
            "id": "137",
            "attributes": {},
            "relationships": {},
        }
        record = JSONAPIModel.from_resource(resource)
        self.assertIsInstance(record, Dummy)
        self.assertEqual(record.id, 137)


def test_save_record_with_no_id() -> None:
    model = Dummy()
    with pytest.raises(JSONAPIError):
        model.save()


def test_save_record_without_update_fields() -> None:
    model = Dummy(pk=1)
    with pytest.raises(JSONAPIError):
        model.save()


def test_save_record_with_wrong_update_fields() -> None:
    model = Dummy(pk=1)
    with pytest.raises(JSONAPIError):
        model.save(update_fields=["field_not_in_meta"])


def test_save_record() -> None:
    model = Dummy(pk=1, field="updated_value")
    with mock.patch.object(model, "objects") as mocked_manager:
        mocked_manager.client.patch.return_value = {
            "data": {"id": "1", "type": "tests", "attributes": {"field": "actual_updated_value"}},
        }
        model.save(update_fields=["field"])
        mocked_manager.client.patch.assert_called_once_with(
            resource_type="tests",
            resource_id=1,
            attributes={"field": "updated_value"},
        )

    from_cache = Dummy.from_cache(pk=1)
    assert from_cache.field == "actual_updated_value"
