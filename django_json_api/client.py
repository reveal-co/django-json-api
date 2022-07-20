import json
from typing import Dict, List, Optional, Union
from urllib.parse import urlencode

import requests
from django.conf import settings

from django_json_api import __version__
from django_json_api.fields import Relationship, get_model

Fields = Dict[str, List[str]]
Include = List[str]
Filters = Dict[str, str]
ResourceId = Union[str, int]
Sort = List[str]


class JSONAPIClientError(Exception):
    def __init__(self, *args, response=None, **kwargs):
        self.response = response
        super().__init__(*args, **kwargs)


class JSONAPIClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/vnd.api+json",
                "Accept": "application/vnd.api+json",
                "User-Agent": f"JSONAPIClient/{__version__}",
                **getattr(settings, "DJANGO_JSON_API_ADDITIONAL_HEADERS", {}),
            }
        )

    def url_for_resource(self, resource_type: str, resource_id: Optional[ResourceId] = None) -> str:
        model = get_model(resource_type)
        if model is None:
            raise JSONAPIClientError(f'Cannot resolve resource "{resource_type}"')
        dasherized_resource_type = resource_type.replace("_", "-")
        url = f"{model._meta.api_url}/{dasherized_resource_type}/"
        if resource_id is not None:
            url += f"{resource_id}/"
        return url

    def _get_fields(self, resource_type: str, fields: Optional[Fields] = None) -> Dict[str, str]:
        model = get_model(resource_type)
        fields = fields or {}
        if resource_type not in fields:
            fields[resource_type] = model._meta.fields.keys()
        return {
            f"fields[{rtype}]": ",".join(field_names)
            for rtype, field_names in fields.items()
            if field_names
        }

    def _get_include(self, resource_type: str, include: Optional[Include] = None) -> Dict[str, str]:
        model = get_model(resource_type)
        if include is None:
            include = [
                fieldname
                for fieldname, field in model._meta.fields.items()
                if isinstance(field, Relationship)
            ]
        elif not include:
            return {}
        return {
            "include": ",".join(include),
        }

    def get(
        self,
        resource_type: str,
        resource_id: Optional[ResourceId] = None,
        filters: Optional[Filters] = None,
        include: Optional[Include] = None,
        fields: Optional[Fields] = None,
        sort: Optional[Sort] = None,
        page_size: Optional[int] = None,
        page_number: Optional[int] = None,
    ) -> Dict:
        url = self.url_for_resource(resource_type, resource_id=resource_id)
        params = {}
        params.update(self._get_fields(resource_type, fields))
        params.update(self._get_include(resource_type, include))
        if filters is not None:
            params.update({f"filter[{field}]": value for field, value in filters.items()})
        if page_size is not None:
            params["page[size]"] = str(page_size)
        if page_number is not None:
            params["page[number]"] = str(page_number)
        if sort:
            params["sort"] = ",".join(sort)
        if params:
            url += "?" + urlencode(params)
        response = self.session.get(url)
        if not response.ok:
            raise JSONAPIClientError(f"HTTP Error: {response.status_code}", response=response)
        return response.json()

    def patch(
        self,
        resource_type: str,
        resource_id: ResourceId,
        attributes: Dict,
    ) -> Dict:
        url = self.url_for_resource(resource_type, resource_id=resource_id)
        payload = {
            "data": {
                "type": resource_type,
                "id": str(resource_id),
                "attributes": attributes,
            }
        }
        response = self.session.patch(url, data=json.dumps(payload))
        if not response.ok:
            raise JSONAPIClientError(f"HTTP Error: {response.status_code}", response=response)
        return response.json()
