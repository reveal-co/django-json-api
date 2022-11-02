# Changelog

## [0.3.2] - 2022-11-02
- Support passing Enums in `filter(...)`

## [0.3.2] - 2022-10-27
- Cache performance improvements

## [0.3.0] - 2022-08-23
- Implement `prefetch_related(...)` method on JSONAPIManager
  - It was not implemented
  - It is meant to prevent n+1 issue on cache querying
- Add optional parameter `prefetch_related` to method `get_many(...)` of JSONAPIModel
  - It is meant to prevent n+1 issue on cache querying
- Improve `prefetch_jsonapi` method used in `WithJSONApiQuerySet`
  - Now bears nested jsonapi prefetch
  - It is meant to prevent n+1 issue on cache querying

## [0.2.7] - 2022-07-20
- Implement `save(...)` method on JSONAPIModel
    - It was not implemented
- Implement `patch(...)` method on JSONAPIClient
    - It was not implemented

## [0.2.6] - 2021-10-04
- Typing rollback

## [0.2.5] - 2022-07-01
- Add `DJANGO_JSON_API_CACHE_KEY_VERSION` as optional setting config, as a way to invalidate cache

## [0.2.4] - 2021-10-29
- Fix manager's `.prefetch_jsonapi(...)` to be silently ignored when using `.values(...)` or `.values_list(...)`.
    - It used to raise an exception


## [0.2.3] - 2021-06-09
- **Fix `_fetch_iterate`**
  - With `x-no-count` true we collected only first page and stopped.
  - Better handle pagination

## [0.2.2] - 2021-06-02
- **Improvement on prefetch_json_api**
  - Better handle nested relations

## [0.2.1] - 2021-06-01
- **Improvement on prefetch_json_api**
  - Bear missing relations in lookups

## [0.2.0] - 2021-03-19
- **Quality of life**
  - Bumping the project's version through `VERSION` resource will not require changes in test cases
- **Requirements Changes**
  - djangorestframework -> 3.12.2
  - djangorestframework-jsonapi -> 4.1.0

## [0.1.1] -  2021-02-26
- **Packaging Fix**
    - Include `VERSION` resource in package, fixing `FileNotFoundError`

## [0.1.0] -  2021-02-24
- **New**
    - Add public version code
