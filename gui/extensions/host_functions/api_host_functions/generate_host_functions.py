from functools import wraps
from typing import TypedDict, Type, Annotated, get_origin, Any

from extism import Json

from rm_api import Document, Metadata, Content, DocumentCollection
from . import export_types as et
from .. import definitions as d


def document_wrapper(func):
    """
    This wrapper is for documents. Takes in document_uuid.

    api.documents[document_uuid] will be returned.
    """
    func.__annotations__.pop('item')
    ref = func.__annotations__.pop('ref', None)
    func.__annotations__ = {'document_uuid': str, **func.__annotations__}

    @wraps(func)
    def wrapper(document_uuid: str, *args, **kwargs):
        document = d.api.documents[document_uuid]
        if ref:
            kwargs['ref'] = document
        return func(document, *args, **kwargs)

    return wrapper


def document_sub_wrapper(sub_attribute: str):
    """
    This wrapper is for sub attributes of a document. Takes in document_uuid.

    api.documents[document_uuid].sub_attribute will be returned.
    :param sub_attribute: The sub attribute of the document that will be affected
    """

    def wrapper(func):
        func.__annotations__.pop('item')
        ref = func.__annotations__.pop('ref', None)  # The function might accept the reference to the document
        func.__annotations__ = {'document_uuid': str, **func.__annotations__}

        @wraps(func)
        def inner_wrapper(document_uuid: str, *args, **kwargs):
            document = d.api.documents[document_uuid]
            if ref:
                kwargs['ref'] = document  # Pass the document to the function per request
            return func(getattr(document, sub_attribute), *args, **kwargs)

        return inner_wrapper

    return wrapper


def collection_wrapper(func):
    """
    This wrapper is for collections. Takes in document_collection_uuid.

    api.collections[document_collection_uuid] will be returned.
    """
    func.__annotations__.pop('item')
    func.__annotations__ = {'document_collection_uuid': str, **func.__annotations__}

    @wraps(func)
    def wrapper(document_collection_uuid: str, *args, **kwargs):
        document_collection = d.api.document_collections[document_collection_uuid]
        return func(document_collection, *args, **kwargs)

    return wrapper


def collection_sub_wrapper(sub_attribute: str):
    """
    This wrapper is for sub attributes of a collection. Takes in document_collection_uuid.

    api.collections[document_collection_uuid].sub_attribute will be returned.
    :param sub_attribute: The sub attribute of the document collection that will be affected
    """

    def wrapper(func):
        func.__annotations__.pop('item')
        ref = func.__annotations__.pop('ref', None)  # The function might accept the reference to the collection
        func.__annotations__ = {'document_collection_uuid': str, **func.__annotations__}

        @wraps(func)
        def inner_wrapper(document_collection_uuid: str, *args, **kwargs):
            document_collection = d.api.document_collections[document_collection_uuid]
            if ref:
                kwargs['ref'] = document_collection  # Pass the document collection to the function per request
            return func(getattr(document_collection, sub_attribute), *args, **kwargs)

        return inner_wrapper

    return wrapper


def metadata_wrapper(func):
    """
    This wrapper is for standalone metadata data stored on the extension manager. Takes in metadata_id.

    em.metadata_objects[metadata_id] will be returned.
    """
    func.__annotations__.pop('item')
    func.__annotations__ = {'metadata_id': str, **func.__annotations__}

    @wraps(func)
    def wrapper(metadata_id: str, *args, **kwargs):
        metadata = d.extension_manager.metadata_objects[metadata_id]
        return func(metadata, *args, **kwargs)

    return wrapper


def content_wrapper(func):
    """
    This wrapper is for standalone content data stored on the extension manager. Takes in content_id.
    em.content_objects[content_id] will be returned
    """
    func.__annotations__.pop('item')
    func.__annotations__ = {'content_id': str, **func.__annotations__}

    @wraps(func)
    def wrapper(content_id: str, *args, **kwargs):
        content = d.extension_manager.content_objects[content_id]
        return func(content, *args, **kwargs)

    return wrapper


def document_ref_wrapper(use_ref: bool = True):
    # Create a basic wrapper which will add document_uuid to the metadata and content
    def wrapper(func):
        @wraps(func)
        def wrapped(item: Any, *args, ref, **kwargs):
            # Accepts the document through ref, cause item might be the metadata or content
            document_dict = func(item, *args, **kwargs)
            document_dict['metadata']['document_uuid'] = ref.uuid
            document_dict['content']['document_uuid'] = ref.uuid
            return document_dict

        return wrapped

    if use_ref:  # By default, pass the item as the ref, cause the item would be the document
        def ref_wrapper(func):
            wrapped = wrapper(func)

            @wraps(wrapped)
            def ref_wrapped(item: Document, *args, **kwargs):
                return wrapped(item, *args, ref=item, **kwargs)

            return ref_wrapped

        return ref_wrapper
    # If the item is not the document, then the ref should be passed from other wrappers

    return wrapper


def check_is_dict(_t: Type[TypedDict]):
    return isinstance(_t, type) and issubclass(_t, dict) or get_origin(_t) is dict


def generate_for_type(t: Type[TypedDict], item_type: type, prefix: str, wrapper, extra_item_data_wrapper=lambda x: x):
    """
    Helper function to generate host functions for a TypedDict type.

    :param t: The TypedDict type
    :param item_type: The type of the item that the TypedDict represents, e.g. Document, Metadata, Content
    :param prefix: The prefix for the host functions
    :param wrapper: A base wrapper to update how the item will be passed to the host functions
    :param extra_item_data_wrapper: A wrapper to update the return value of the host functions to add extra data
    """
    can_get = {}
    can_set = {}
    for name, _t in t.__annotations__.items():
        is_dict = check_is_dict(_t)

        if is_dict:
            _t = Annotated[_t, Json]

        can_get[name] = _t

        if is_dict:
            continue

        if (prop := getattr(item_type, name, None)) and isinstance(prop, property) and prop.fset is None:
            continue

        if get_origin(_t) is list:
            continue

        can_set[name] = _t

    @d.host_fn(f"{prefix}get")
    @d.debug_result
    @d.transform_to_json
    @wrapper
    def _func(item: item_type, key: str):
        value_type = can_get.get(item, None)
        if not value_type:
            raise ValueError(f"Can't get {key} from {item_type.__name__}")

        if check_is_dict(value_type):
            return getattr(item, key).__dict__
        return getattr(item, key)

    @d.host_fn(f"_{prefix}set")
    @d.debug_result
    @d.unpack
    @wrapper
    def _func(item: item_type, key: str, value: Annotated[Any, Json]):
        value_type = can_set.get(key, None)
        if not value_type:
            raise ValueError(f"Can't set {key} on {item_type.__name__}")
        if type(value) is not value_type:
            raise ValueError(
                f"Can't set {key} on {item_type.__name__} "
                f"because type {type(value)} "
                f"does not match required type {value_type}"
            )
        return setattr(item, key, value)

    @d.host_fn(f"{prefix}get_all")
    @d.debug_result
    @wrapper
    @extra_item_data_wrapper
    def _func(item: t) -> Annotated[t, Json]:
        return item.__dict__


# Top most objects
generate_for_type(et.TRM_Document, Document, "moss_api_document_", document_wrapper, document_ref_wrapper())
generate_for_type(et.TRM_DocumentCollection, DocumentCollection, "moss_api_collection_", collection_wrapper)

# Metadata
generate_for_type(et.TRM_MetadataDocument, Metadata,  # Metadata of a document
                  "moss_api_document_metadata_", document_sub_wrapper('metadata'), document_ref_wrapper(False))
generate_for_type(et.TRM_MetadataBase, Metadata,  # Metadata of a collection
                  "moss_api_collection_metadata_", collection_sub_wrapper('metadata'))
generate_for_type(et.TRM_MetadataDocument, Metadata,  # Standalone metadata
                  "moss_api_metadata_", metadata_wrapper)

# Content
generate_for_type(et.TRM_Content, Content, "moss_api_document_content_", document_sub_wrapper('content'))
generate_for_type(et.TRM_Content, Content, "moss_api_content_", content_wrapper)
