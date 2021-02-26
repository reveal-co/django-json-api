from unittest import TestCase, mock

from django.core.cache import cache

from django_json_api.models import JSONAPIModel
from tests.models import Dummy


class JSONAPIModelBaseTestCase(TestCase):
    def setUp(self):
        cache.clear()
        return super().setUp()

    def test_cache_key(self):
        self.assertEqual(Dummy.cache_key(42), "jsonapi:tests:42")

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
