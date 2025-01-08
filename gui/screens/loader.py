import os
import threading
import time
from traceback import print_exc
from typing import TYPE_CHECKING, Union, Dict

import pygameextra as pe

from gui.defaults import Defaults
from gui.helpers import invert_icon
from gui.screens.main_menu import MainMenu
from gui.screens.mixins import LogoMixin
from rm_api.notifications.models import SyncCompleted, NewDocuments

if TYPE_CHECKING:
    from gui.gui import GUI
    from rm_api import API
    from gui.extensions import ExtensionManager


class ReusedIcon:
    def __init__(self, key: str, scale: float):
        self.key = key
        self.scale = scale


class InvertedIcon:
    def __init__(self, item: 'AcceptedLoadTypes'):
        self.item = item


class ResizedIcon:
    def __init__(self, item: str, scale: float):
        self.item = item
        self.scale = scale


AcceptedLoadTypes = Union[str, ReusedIcon, ResizedIcon, InvertedIcon]


class Loader(pe.ChildContext, LogoMixin):
    TO_LOAD = {
        # Icons and Images
        'folder': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'folder.svg')),
        'folder_add': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'folder_add.svg')),
        'folder_empty': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'folder_empty.svg')),
        'star': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'star.svg')),
        'star_empty': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'star_empty.svg')),
        'tag': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'tag.svg')),
        'chevron_down': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'chevron_down.svg')),
        'chevron_right': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'chevron_right.svg')),
        'small_chevron_down': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'small_chevron_down.svg')),
        'small_chevron_right': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'small_chevron_right.svg')),
        'cloud': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'cloud.svg')),
        'cloud_download': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'cloud_download.svg')),
        'cloud_synced': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'cloud_synced.svg')),
        'warning_circle': os.path.join(Defaults.ICON_DIR, 'warning_circle.svg'),
        'notebook_large': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'notebook_large.svg')),
        'notebook': InvertedIcon(ReusedIcon('notebook_large', 0.333)),
        'notebook_add': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'notebook_add.svg')),
        'share': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'share.svg')),
        'export': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'export.svg')),
        'copy': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'copy.svg')),
        'import': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'import.svg')),
        'info': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'information_circle.svg')),
        'rotate': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'rotate.svg')),
        'burger': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'burger.svg')),
        'filter': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'filter.svg')),
        'context_menu': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'context_menu.svg')),
        'pencil': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'pencil.svg')),
        'my_files': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'my_files.svg')),
        'trashcan': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'trashcan.svg')),
        'trashcan_delete': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'trashcan_delete.svg')),
        'cog': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'cog.svg')),
        'heart': os.path.join(Defaults.ICON_DIR, 'heart.svg'),
        'compass': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'compass.svg')),
        'duplicate': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'duplicate.svg')),
        'text_edit': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'text_edit.svg')),
        'move': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'move.svg')),
        'x_medium': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'x_medium.svg')),
        'x_small': InvertedIcon(os.path.join(Defaults.ICON_DIR, 'x_small.svg')),
        'discord_qr_code': ResizedIcon(os.path.join(Defaults.IMAGES_DIR, 'discord_qr_code.png'), 0.253),

        # 'screenshot': 'Screenshot_20241023_162027.png',

        # Data files
        'light_pdf': os.path.join(Defaults.DATA_DIR, 'light.pdf')
    }

    LAYER = pe.AFTER_LOOP_LAYER
    icons: Dict[str, pe.Image]
    api: 'API'
    extension_manager: 'ExtensionManager'
    logo: pe.Text
    line_rect: pe.Rect

    def __init__(self, parent: 'GUI'):
        super().__init__(parent)
        self.initialize_logo_and_line()
        self.api.add_hook('loader_resize_check', self.resize_check_hook)
        self.items_loaded = 0
        self.files_loaded = 0
        self.loading_feedback = 0  # Used by main menu to know if enough changes have been made since last checked
        self.loading_complete_marker = 0  # A timestamp of last sync completion
        self.files_to_load: Union[int, None] = None
        self.last_progress = 0
        self.current_progress = 0
        self.initialized = False
        self.to_load = len(self.TO_LOAD)

    def start_syncing(self):
        threading.Thread(target=self.get_documents, daemon=True).start()

    def __load(self, key: str, item: AcceptedLoadTypes):
        if isinstance(item, ReusedIcon):
            self.icons[key] = self.icons[item.key].copy()
            self.icons[key].resize(tuple(v * item.scale for v in self.icons[key].size))
        elif isinstance(item, ResizedIcon):
            self.load_image(key, item.item, item.scale)
        elif isinstance(item, InvertedIcon):
            self.__load(key, item.item)
            key_inverted = f'{key}_inverted'
            invert_icon(self, key, key_inverted)
        elif not isinstance(item, str):
            return
        elif item.endswith('.svg'):
            # SVGs are 40px, but we use 1000px height, so they are 23px
            # 23 / 40 = 0.575
            # but, I find 0.5 to better match
            self.load_image(key, item, 0.5)
        elif item.endswith('.png'):
            self.load_image(key, item)
        else:
            self.load_data(key, item)

    def _load(self):
        for key, item in self.TO_LOAD.items():
            self.__load(key, item)
            self.items_loaded += 1

        # Wait for extensions to load
        while not self.extension_manager.extensions_loaded == self.extension_manager.extension_count:
            pass

        # Load extension data
        self.to_load += len(self.extension_manager.extra_items)
        for key, item in self.extension_manager.extra_items.items():
            if item.endswith('.svg'):
                self.load_image(key, item, 0.5)
            elif item.endswith('.png'):
                self.load_image(key, item)
            else:
                self.load_data(key, item)
            self.items_loaded += 1

    def load(self):
        try:
            self._load()
        except:
            print_exc()

    def load_extensions(self):
        try:
            self.extension_manager.load()
        except:
            print_exc()

    def get_documents(self):
        def progress(loaded, to_load):
            self.files_loaded = loaded
            self.files_to_load = to_load

        self.loading_feedback = 0
        self.loading_complete_marker = 0
        self.api.get_documents(progress)
        if self.config.last_root != self.api.last_root:
            self.config.last_root = self.api.last_root
            self.parent_context.dirty_config = True
        self.files_to_load = None
        if not self.current_progress:
            self.current_progress = 1
        self.api.spread_event(NewDocuments())

        self.loading_complete_marker = time.time()

    def load_image(self, key, file, multiplier: float = 1):
        self.icons[key] = pe.Image(file)
        self.icons[key].resize(tuple(self.ratios.pixel(v * multiplier) for v in self.icons[key].size))

    def load_data(self, key, file):
        with open(file, 'rb') as f:
            self.data[key] = f.read()

    def progress(self):
        if self.files_to_load is None and self.config.wait_for_everything_to_load and not self.current_progress:
            # Before we know the file count, just return 0 progress
            return 0
        try:
            base_division_a = (
                    self.extension_manager.extensions_loaded +
                    self.items_loaded
            )
            base_division_b = (
                    self.extension_manager.extension_count +
                    self.to_load
            )
            if not self.config.wait_for_everything_to_load:
                self.current_progress = base_division_a / base_division_b
            else:
                self.current_progress = (
                                                base_division_a +
                                                self.files_loaded
                                        ) / (
                                                base_division_b +
                                                (self.files_to_load or self.files_loaded)
                                        )
        except ZeroDivisionError:
            self.current_progress = 0
        self.last_progress = self.last_progress + (self.current_progress - self.last_progress) / (self.FPS * .1)
        if not self.config.wait_for_everything_to_load and self.current_progress == 1 and self.last_progress < 0.9:
            self.last_progress = 0.9
        return self.last_progress

    def loop(self):
        self.logo.display()
        progress = self.progress()
        if progress:
            pe.draw.rect(Defaults.LINE_GRAY, self.line_rect, self.ratios.loader_loading_bar_thickness,
                         edge_rounding=self.ratios.loader_loading_bar_rounding)
            progress_rect = self.line_rect.copy()
            progress_rect.width *= progress
            pe.draw.rect(Defaults.SELECTED, progress_rect, 0, edge_rounding=self.ratios.loader_loading_bar_rounding)
            if self.config.debug:
                if self.extension_manager.extension_count:
                    extensions_rect = self.line_rect.copy()
                    extensions_rect.width *= (
                            self.extension_manager.extensions_loaded / self.extension_manager.extension_count)
                    pe.draw.rect(Defaults.TEXT_ERROR_COLOR[0], extensions_rect,
                                 self.ratios.loader_loading_bar_thickness * 3,
                                 edge_rounding=self.ratios.loader_loading_bar_rounding)
                icons_rect = self.line_rect.copy()
                icons_rect.width *= (self.items_loaded / len(self.TO_LOAD))
                pe.draw.rect(Defaults.LINE_GRAY_LIGHT, icons_rect, self.ratios.loader_loading_bar_thickness * 2,
                             edge_rounding=self.ratios.loader_loading_bar_rounding)

    def post_loop(self):
        if self.current_progress == 1 and self.last_progress >= .98:
            self.screens.put(MainMenu(self.parent_context))
            self.api.connect_to_notifications()
            self.api.add_hook('loader', self.loader_hook)

    def loader_hook(self, event):
        if isinstance(event, SyncCompleted):
            self.start_syncing()

    def pre_loop(self):
        if not self.initialized:
            threading.Thread(target=self.load, daemon=True).start()
            threading.Thread(target=self.load_extensions, daemon=True).start()
            self.start_syncing()
            self.initialized = True
