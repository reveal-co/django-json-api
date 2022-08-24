from unittest import TestCase, mock
from urllib.parse import urlencode

import pytest
from django.core.cache import cache
from django.test import override_settings
from requests_mock import Mocker

from django_json_api.models import JSONAPIError, JSONAPIModel
from tests.models import Company, Dummy, Role, User


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
        Dummy.objects.prefetch_related.return_value.get.return_value = non_cached_instance
        self.assertEqual(
            {12: cached_instance, 137: non_cached_instance},
            Dummy.get_many([12, 137]),
        )
        Dummy.objects.prefetch_related.return_value.get.assert_called_once_with(pk=137)
        # Group Fetch
        Dummy.objects.prefetch_related.return_value.filter.return_value = [non_cached_instance]
        Dummy._meta.many_id_lookup = "id"
        self.assertEqual(
            {12: cached_instance, 137: non_cached_instance},
            Dummy.get_many([12, 137]),
        )
        Dummy.objects.prefetch_related.return_value.filter.assert_called_once_with(id="137")
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


def test_get_many__with_prefetch__one_to_many() -> None:
    cache.clear()
    cached_role = Role(pk=2001, role_name="role 1")
    cached_user = User(pk=1001, email="email 1")
    cached_user_2 = User(pk=1005, email="email 5")
    setattr(
        cached_user,
        "roles_identifiers",
        [
            {"id": "2001", "type": "roles"},
            {"id": "2002", "type": "roles"},
        ],
    )
    setattr(
        cached_user_2,
        "roles_identifiers",
        [],
    )
    cached_but_incomplete_user = User(pk=1002, email="email 2")
    cached_company = Company(pk=1, name="company 1")
    cached_company_2 = Company(pk=3, name="company 3")
    setattr(
        cached_company,
        "users_identifiers",
        [
            {"id": "1001", "type": "users"},
            {"id": "1002", "type": "users"},
            {"id": "1003", "type": "users"},
        ],
    )
    setattr(
        cached_company_2,
        "users_identifiers",
        [
            {"id": "1005", "type": "users"},
        ],
    )

    cache.set(Role.cache_key(cached_role.pk), cached_role)
    cache.set(User.cache_key(cached_user.pk), cached_user)
    cache.set(User.cache_key(cached_but_incomplete_user.pk), cached_but_incomplete_user)
    cache.set(User.cache_key(cached_user_2.pk), cached_user_2)
    cache.set(Company.cache_key(cached_company.pk), cached_company)
    cache.set(Company.cache_key(cached_company_2.pk), cached_company_2)

    with Mocker() as mocker:
        companies_page = {
            "data": {
                "id": "2",
                "type": "companies",
                "attributes": {"name": "company 2"},
                "relationships": {
                    "users": {
                        "data": [
                            {
                                "id": "1004",
                                "type": "users",
                            }
                        ]
                    }
                },
            },
            "included": [
                {
                    "id": "1004",
                    "type": "users",
                    "attributes": {
                        "email": "email 3",
                    },
                    "relationships": {
                        "roles": {
                            "data": [
                                {"id": "2004", "type": "roles"},
                            ]
                        }
                    },
                },
                {
                    "id": "2004",
                    "type": "roles",
                    "attributes": {
                        "role_name": "role 4",
                    },
                },
            ],
        }
        company_params = {
            "include": "users,users.roles",
            "fields[companies]": "name,users",
        }
        mocker.register_uri(
            "GET",
            f"http://test/api/companies/2/?{urlencode(company_params)}",
            status_code=200,
            json=companies_page,
        )

        users_page = {
            "data": [
                {
                    "id": "1002",
                    "type": "users",
                    "attributes": {"email": "email 2"},
                    "relationships": {
                        "roles": {
                            "data": [
                                {
                                    "id": "2003",
                                    "type": "roles",
                                }
                            ]
                        }
                    },
                },
                {
                    "id": "1003",
                    "type": "users",
                    "attributes": {"email": "email 3"},
                    "relationships": {"roles": {"data": []}},
                },
            ],
            "included": [
                {
                    "id": "2003",
                    "type": "roles",
                    "attributes": {
                        "role_name": "role 3",
                    },
                },
            ],
        }
        users_params = {
            "include": "roles",
            "fields[users]": "email,company,roles",
            "filter[id]": "1002,1003",
            "page[size]": 10,
            "page[number]": 1,
        }
        mocker.register_uri(
            "GET",
            f"http://test/api/users/?{urlencode(users_params)}",
            status_code=200,
            json=users_page,
        )

        role_page = {
            "data": {
                "id": "2002",
                "type": "roles",
                "attributes": {"role_name": "role 2"},
            },
            "included": [],
        }
        role_params = {
            "include": "user",
            "fields[roles]": "role_name,user",
        }
        mocker.register_uri(
            "GET",
            f"http://test/api/roles/2002/?{urlencode(role_params)}",
            status_code=200,
            json=role_page,
        )

        results = Company.get_many(record_ids=[1, 2, 3], prefetch_related=["users__roles"])

    cache.clear()
    assert len(results) == 3
    company_previously_cached = results[1]

    assert len(company_previously_cached.users) == 3
    assert company_previously_cached.users[0].pk == cached_user.pk
    assert company_previously_cached.users[0].roles[0].pk == cached_role.pk
    assert company_previously_cached.users[0].roles[1].pk == 2002
    assert company_previously_cached.users[1].pk == 1002
    assert company_previously_cached.users[1].roles[0].pk == 2003
    assert company_previously_cached.users[2].pk == 1003
    assert len(company_previously_cached.users[2].roles) == 0

    company_not_previously_cached = results[2]
    assert len(company_not_previously_cached.users) == 1
    assert company_not_previously_cached.users[0].pk == 1004
    assert company_not_previously_cached.users[0].roles[0].pk == 2004

    company_previously_cached = results[3]
    assert len(company_previously_cached.users) == 1
    assert company_previously_cached.users[0].pk == 1005
    assert len(company_previously_cached.users[0].roles) == 0


def test_get_many__with_prefetch__many_to_one() -> None:
    cache.clear()
    cached_role = Role(pk=2001, role_name="role 1")
    setattr(cached_role, "user_identifier", {"id": "1001", "type": "users"})
    cached_but_incomplete_role = Role(pk=2002, role_name="role 2")

    cached_user = User(pk=1001, email="email 1")
    setattr(cached_user, "company_identifier", {"id": "1", "type": "companies"})

    cache.set(Role.cache_key(cached_role.pk), cached_role)
    cache.set(Role.cache_key(cached_but_incomplete_role.pk), cached_but_incomplete_role)
    cache.set(User.cache_key(cached_user.pk), cached_user)

    with Mocker() as mocker:
        company_page = {
            "data": {
                "id": "1",
                "type": "companies",
                "attributes": {"name": "company 1"},
            },
            "included": [],
        }
        company_params = {
            "include": "users",
            "fields[companies]": "name,users",
        }
        mocker.register_uri(
            "GET",
            f"http://test/api/companies/1/?{urlencode(company_params)}",
            status_code=200,
            json=company_page,
        )

        role_page = {
            "data": {
                "id": "2002",
                "type": "roles",
                "attributes": {"role_name": "role 2"},
                "relationships": {
                    "user": {
                        "data": {
                            "id": "1002",
                            "type": "users",
                        }
                    }
                },
            },
            "included": [
                {
                    "id": "1002",
                    "type": "users",
                    "attributes": {
                        "id": "1002",
                        "email": "email 2",
                    },
                    "relationships": {
                        "company": {
                            "data": {"id": "2", "type": "companies"},
                        }
                    },
                },
                {
                    "id": "2",
                    "type": "companies",
                    "attributes": {
                        "id": "2",
                        "name": "company 2",
                    },
                },
            ],
        }
        role_params = {
            "include": "user",
            "fields[roles]": "role_name,user",
        }
        mocker.register_uri(
            "GET",
            f"http://test/api/roles/2002/?{urlencode(role_params)}",
            status_code=200,
            json=role_page,
        )

        results = Role.get_many(record_ids=[2001, 2002], prefetch_related=["user__company"])

        cache.clear()
        assert len(results) == 2
        previously_cached_role = results[2001]
        assert previously_cached_role.user.pk == 1001
        assert previously_cached_role.user.company.pk == 1
        previously_cached_but_incomplete_role = results[2002]
        assert previously_cached_but_incomplete_role.user.pk == 1002
        assert previously_cached_but_incomplete_role.user.company.pk == 2
