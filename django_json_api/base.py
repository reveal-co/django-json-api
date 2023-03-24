from django_json_api.manager import JSONAPIManager


class Options:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class JSONAPIModelBase(type):
    def __new__(cls, name, bases, attrs, **kwargs):
        super_new = super().__new__
        parents = [b for b in bases if isinstance(b, JSONAPIModelBase)]
        if not parents:
            return super_new(cls, name, bases, attrs)
        meta = attrs.pop("Meta")
        new_attrs = {}
        contributable_attrs = {}
        for obj_name, obj in list(attrs.items()):
            if hasattr(obj, "contribute_to_class"):
                contributable_attrs[obj_name] = obj
            else:
                new_attrs[obj_name] = obj
        new_class = super_new(cls, name, bases, new_attrs, **kwargs)
        new_class._meta = meta
        new_class._meta.model = new_class
        new_class._meta.fields = {}
        new_class._meta.auth = getattr(meta, "auth", None)

        class JSONAPIMeta:
            resource_name = new_class._meta.resource_type

        new_class.JSONAPIMeta = JSONAPIMeta

        for obj_name, obj in contributable_attrs.items():
            new_class._meta.fields[obj_name] = obj.contribute_to_class(new_class, obj_name)
        new_class.objects = JSONAPIManager(new_class)
        return new_class
