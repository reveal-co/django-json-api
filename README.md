# django-json-api

[![PyPI version](https://badge.fury.io/py/django-json-api.svg)](https://badge.fury.io/py/django-json-api)
[![codecov](https://codecov.io/gh/share-work/django-json-api/branch/develop/graph/badge.svg?token=hTGA39HrJV)](https://codecov.io/gh/share-work/django-json-api)
[![Reveal](https://circleci.com/gh/reveal-co/django-json-api.svg?style=shield&circle-token=727d6ee289cf310d7f2a473d02574506f6ea8ef7)](https://app.circleci.com/pipelines/github/reveal-co/django-json-api)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)


**django-json-api** uses Django's ORM interfaces as inspiration to serialize, request and
deserialize entities from databases of other microservices using (and benefiting from) the
[JSON:API](https://jsonapi.org/) specification.


## Installation

To install via pip:

```sh
pip install django-json-api
```

You can also install from the source:

```sh
git clone git@github.com:reveal-co/django-json-api.git
cd django-json-api
git checkout main
pip install -e .
```

## Getting started

Suppose you have a `django.db.models.Model` class inside microservice A, such as:

```python
from django.db import models

class Company(models.Model):
    name = models.CharField(max_length=256)
    domain = models.CharField(max_length=256)
    deleted_at = models.DateTimeField(null=True, default=None)
```

If you wish to consume it from microservice B, first add this inside the aforementioned model's
definition:


```python
    class JSONAPIMeta:
        resource_name = 'companies'
```

and define an instance of a `django_json_api.models.JSONAPIModel` inside microservice B:

```python
from django_json_api.models import JSONAPIModel
from django_json_api.fields import Attribute

class Company(JSONAPIModel):
    class Meta:
        api_url = MICROSERVICE_A_API_URL
        resource_type = 'companies'

    name = Attribute()
    domain = Attribute()
```

PS: `api_url` expects a url with protocol (i.e. starting with `http(s)://`) and ending with a trailing slash `/`.

Now, querying companies from microservice B is as easy as:

```python
  Company.objects.all()
  Company.objects.filter(name="Reveal")
  Company.objects.iterator()
  ...
```

You can also have entities in one microservice relate to entities in another by leveraging both `RelatedJSONAPIField`
and `WithJSONAPIQuerySet`. Take a look at this model definition from microservice B:

```python
from django.db import models
from django_json_api.django import RelatedJSONAPIField


class User(models.Model):
    name = models.CharField(max_length=256)
    company = RelatedJSONAPIField(json_api_model=Company)
    deleted_at = models.DateTimeField(null=True, default=None)
```

Here, `Company` is the `JSONAPIModel` defined above. This makes it possible, when querying for a user, to also
fetch its related company:

```python
user = User.objects.get(pk=1)
user.company # This will be resolved through an underlying HTTP request
```

In case of larger querysets, you might want to prefetch the relations as you do with django's `prefetch_related`. For
that, you imbue `User`'s manager using `WithJSONApiQuerySet`, which will grant the manager a new
method: `prefetch_jsonapi`.

If the remote microservice API supports PATCH request, you can save a record's attributes:

```python
user = User.objects.get(pk=1)
print(user.name)  # Joe
user.name = "Jack"
user.save(update_fields=["name"]) # This will perform a PATCH HTTP request
updated_user = User.from_cache(pk=1)
print(updated_user.name)  # Jack: the updated record with its new attributes is cached
```

## Authentication

It is possible to path a `auth` parameter to the `JSONAPIClient` in order to dynamically set the authorization headers on
requests before sending them to the remote HTTP server.

In a similar way, it is possible to specify `auth` in the models' `Meta`.

```python
import jwt
import time


class CustomJWTAuth:
    def __init__(self: "CustomJWTAuth", subject: str, secret: str, audience: str) -> None:
    	self.audience = audience
    	self.secret = secret
	self.subject = subject

    def __call__(self: "CustomJWTAuth", request: requests.Request) -> requests.Request:
        iat = int(time.time())
    	token = jwt.encode(
	    {"sub": self.subject, "iat": iat, "exp": iat + 60, "aud": self.audience},
	    self.secret,
	    "HS256",
	)
	request.headers["Authorization"] = f"Bearer {token}"
	return request

# This client will generate a new signed JWT for each request
client = JSONAPIClient(auth=CustomJWTAuth("myService", "*******", "jsonapi"))

# This model will rely on JWT as well when fetching data from the remote service
class ModelWithJWT(JSONAPIModel):
    class Meta:
        resource_type = "examples"
        auth = CustomJWTAuth("myService", "*****", "jsonapi")
```


## License

[MIT](LICENSE)
