from typing import Any, Optional, List, Dict, TypedDict

from rm_api.defaults import ZoomModes, FileTypes, Orientations, DocumentTypes


class TRM_File(TypedDict):
    content_count: int
    hash: str
    rm_filename: str
    size: int
    uuid: str


class TRM_TimestampedValue(TypedDict):
    timestamp: str
    value: Any


class TRM_Tag(TypedDict):
    name: str
    timestamp: int


class TRM_Page(TypedDict):
    id: str
    index: TRM_TimestampedValue
    template: TRM_TimestampedValue
    redirect: Optional[TRM_TimestampedValue]
    scroll_time: Optional[TRM_TimestampedValue]
    vertical_scroll: Optional[TRM_TimestampedValue]


class TRM_CPagesUUID(TypedDict):
    first: str
    second: int


class TRM_CPages(TypedDict):
    pages: List[TRM_Page]
    original: TRM_TimestampedValue
    last_opened: TRM_TimestampedValue
    uuid: List[TRM_CPagesUUID]


class TRM_Zoom(TypedDict):  # RAW
    zoomMode: ZoomModes
    customZoomCenterX: int
    customZoomCenterY: int
    customZoomPageHeight: int
    customZoomPageWidth: int
    customZoomScale: float


class TRM_Content(TypedDict):
    hash: str
    c_pages: TRM_CPages
    cover_page_number: int
    file_type: FileTypes
    version: int
    usable: bool
    zoom: TRM_Zoom
    orientation: Orientations
    tags: List[TRM_Tag]
    size_in_bytes: int
    dummy_document: bool


class TRM_MetadataBase(TypedDict):
    hash: str
    type: DocumentTypes
    parent: Optional[str]
    created_time: int
    last_modified: int
    visible_name: str
    metadata_modified: bool
    modified: bool
    synced: bool
    version: Optional[int]


class TRM_MetadataDocument(TRM_MetadataBase):
    last_opened: int
    last_opened_page: int


class TRM_DocumentCollection(TypedDict):
    tags: List[TRM_Tag]
    metadata: TRM_MetadataBase
    uuid: str
    has_items: bool


class TRM_Document(TypedDict):
    files: List[TRM_File]
    content_data: Dict[str, bytes]
    content: TRM_Content
    metadata: TRM_MetadataDocument
    uuid: str
    server_hash: str
    files_available: List[str]
    downloading: bool
    provision: bool
    available: bool


class TRM_RootInfo(TypedDict):
    generation: int
    hash: str
