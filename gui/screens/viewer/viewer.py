import threading
import time
from typing import TYPE_CHECKING, Dict

import pygameextra as pe
from colorama import Fore

from gui.screens.viewer.renderers.pdf.cef import PDF_CEF_Viewer
from .renderers.notebook.rm_lines_svg_inker import Notebook_rM_Lines_Renderer
from .renderers.pdf.pymupdf import PDF_PyMuPDF_Viewer
from ...events import ResizeEvent

try:
    import CEF4pygame

    CEF4pygame.print = lambda *args, **kwargs: None
    from CEF4pygame import CEFpygame
    from cefpython3 import cefpython as cef
except Exception:
    CEFpygame = None
    cef = None

from gui.defaults import Defaults
from gui.pp_helpers import DraggablePuller
from rm_api import models

if TYPE_CHECKING:
    from gui.gui import GUI, ConfigType
    from queue import Queue
    from rm_api.models import Document, Content


class UnusableContent(Exception):
    def __init__(self, content: 'Content'):
        self.content = content
        super().__init__(f"Unusable content: {content}")


class CannotRenderDocument(Exception):
    def __init__(self, document: 'Document'):
        self.document = document
        super().__init__(f"Cannot render document {document.metadata.visible_name}")


class DocumentRenderer(pe.ChildContext):
    LAYER = pe.BEFORE_POST_LAYER
    DOT_TIME = .4

    config: 'ConfigType'

    PAGE_NAVIGATION_DELAY = 0.2  # Initial button press delay
    PAGE_NAVIGATION_SPEED = 0.1  # After initial button press delay
    ZOOM_SENSITIVITY = 10  # How fast the zoom changes
    ZOOM_WAIT = 0.2  # How long to wait after zoom before handling intense scaling tasks

    def __init__(self, parent: 'GUI', document: 'Document'):
        self.document = document
        self.loading = 0
        self.began_loading = False
        self._error = None
        self.hold_next = False
        self.hold_previous = False
        self.hold_timer = 0
        self.base_zoom = 1
        self._zoom = 1
        self.zoom_scaling_offset = (0, 0)
        self.zoom_reference_size = (100, 100)
        self.last_zoom_time = time.time()

        # Check compatability
        if not self.document.content.usable:
            raise UnusableContent(self.document.content)

        self.loading_rect = pe.Rect(
            0, 0,
            parent.ratios.document_viewer_loading_square,
            parent.ratios.document_viewer_loading_square
        )
        self.loading_rect.center = parent.center

        split = self.loading_rect.width // 3
        self.first_dot = self.loading_rect.x + split * 0.95
        self.second_dot = self.loading_rect.x + split * 1.5
        self.third_dot = self.loading_rect.x + split * 2.05

        self.draggable = pe.Draggable((0, 0))
        self.pos = (0, 0)

        if parent.config.debug:
            self.debug_display = pe.Text(
                'DEBUG', Defaults.DEBUG_FONT, parent.ratios.debug_text_size,
                colors=(pe.colors.white, pe.colors.darkorange)
            )

        self.loading_timer = time.time()

        self.mode = 'nocontent'
        self.last_opened_uuid = self.document.content.c_pages.last_opened.value
        self.current_page_index = self.document.content.c_pages.get_index_from_uuid(self.last_opened_uuid) or 0
        self.renderer = None
        super().__init__(parent)
        if self.config.notebook_render_mode == 'rm_lines_svg_inker':
            self.notebook_renderer = Notebook_rM_Lines_Renderer(self)
        else:
            self.close()
            print(f"{Fore.RED}Notebook render mode `{self.config.notebook_render_mode}` unavailable{Fore.RESET}")

    @property
    def zoom(self):
        return self.base_zoom * self._zoom

    @property
    def zoom_ready(self):
        return time.time() - self.last_zoom_time > self.ZOOM_WAIT

    @property
    def center_x(self):
        return self.pos[0] + self.width // 2

    @property
    def center_y(self):
        return self.pos[1] + self.height // 2

    @property
    def center(self):
        return self.center_x, self.center_y

    @property
    def error(self):
        return self._error

    @error.setter
    def error(self, value):
        self._error = pe.Text(
            value,
            Defaults.DOCUMENT_ERROR_FONT,
            self.ratios.document_viewer_error_font_size,
            pe.Rect(0, 0, *self.size).center,
            Defaults.TEXT_COLOR
        )
        self.loading = 0

    def handle_navigation(self, event: pe.pygame.event.Event):
        if self.ctrl_hold and event.type == pe.pygame.MOUSEWHEEL:
            zoom_before = self.zoom
            self._zoom += event.y * self.ZOOM_SENSITIVITY * self.delta_time
            self._zoom = max(0.2, min(3, self._zoom))
            zoom_delta = zoom_before - self.zoom

            if zoom_delta:
                # Handle proper panning offset
                # noinspection PyTypeChecker
                self.draggable.pos = self.pos = tuple(
                    int(
                        pos -  # Finally subtract the offset from the current position
                        ((
                                 (mp - center) /  # How offset the mouse is from the center
                                 (reference_size / 2)  # Half of size of the page
                         )  # The influence from the center that the zoom offset should be
                         * offset * zoom_delta  # Finally multiply by the offset and the zoom delta
                         )
                    )  # Ensure the final value is an integer
                    for pos, mp, center, reference_size, offset in
                    zip(
                        self.pos,
                        pe.mouse.pos(),
                        self.center,
                        self.zoom_reference_size,
                        self.zoom_scaling_offset
                    )  # Zip all required positional values
                )
                self.last_zoom_time = time.time()

        if not self.hold_timer:
            if any([
                pe.event.key_DOWN(key)
                for key in Defaults.NAVIGATION_KEYS['next']
            ]):
                self.hold_next = True
                self.hold_timer = time.time() + self.PAGE_NAVIGATION_DELAY
                self.do_next()
            if any([
                pe.event.key_DOWN(key)
                for key in Defaults.NAVIGATION_KEYS['previous']
            ]):
                self.hold_previous = True
                self.hold_timer = time.time() + self.PAGE_NAVIGATION_DELAY
                self.do_previous()
        else:
            if any([
                pe.event.key_UP(key)
                for key in Defaults.NAVIGATION_KEYS['next'] + Defaults.NAVIGATION_KEYS['previous']
            ]):
                self.hold_next = False
                self.hold_previous = False
                self.hold_timer = None

    @property
    def can_do_next(self):
        # Technically if there are no more pages
        # we can make a new blank page
        # TODO: Implement creating new blank pages on next
        return self.current_page_index < len(self.document.content.c_pages.pages) - 1

    @property
    def can_do_previous(self):
        return self.current_page_index > 0

    def do_next(self):
        if self.can_do_next:
            self.current_page_index += 1

    def do_previous(self):
        if self.can_do_previous:
            self.current_page_index -= 1

    def handle_event(self, event):
        if self.loading:
            self.hold_next = False
            self.hold_previous = False
            self.hold_timer = None
            return
        if self.renderer:
            self.renderer.handle_event(event)
        self.handle_navigation(event)

    def load(self):
        if self.document.content.file_type in ('pdf', 'epub'):
            if self.config.pdf_render_mode == 'cef' and CEFpygame:
                self.loading += 1
                self.renderer = PDF_CEF_Viewer(self)
            elif self.config.pdf_render_mode == 'pymupdf':
                self.loading += 1
                self.renderer = PDF_PyMuPDF_Viewer(self)
            elif self.config.pdf_render_mode == 'none':
                self.error = 'Could not render PDF'
            elif self.config.pdf_render_mode == 'retry':
                self.error = 'Could not render PDF. Check your configuration'
            else:
                self.error = 'Could not render PDF. Make sure you have a compatible PDF renderer'

        elif self.document.content.file_type == 'notebook':
            pass
        else:
            self.error = 'Unknown format. Could not render document'
        if self.renderer:
            self.renderer.load()
        self.loading += 1
        self.notebook_renderer.load()

    def pre_loop(self):
        if not self.began_loading:
            self.load()
            self.began_loading = True
        if self.config.debug:
            pe.fill.transparency(pe.colors.black, 25)
        # Draw the loading icon
        if self.loading:
            pe.draw.rect(pe.colors.black, self.loading_rect)
            section = (time.time() - self.loading_timer) / self.DOT_TIME
            if section > 0.5:
                pe.draw.circle(pe.colors.white, (self.first_dot, self.loading_rect.centery),
                               self.ratios.document_viewer_loading_circle_radius)
            if section > 2:
                pe.draw.circle(pe.colors.white, (self.second_dot, self.loading_rect.centery),
                               self.ratios.document_viewer_loading_circle_radius)
            if section > 3:
                pe.draw.circle(pe.colors.white, (self.third_dot, self.loading_rect.centery),
                               self.ratios.document_viewer_loading_circle_radius)
            if section > 3.5:
                self.loading_timer = time.time()

    def loop(self):
        page = self.document.content.c_pages.pages[self.current_page_index]
        self.last_opened_uuid = page.id

        if self.loading:
            return

        if self.renderer:
            self.renderer.render(page.id)
        self.notebook_renderer.render(page.id)

    def close(self):
        if self.renderer:
            self.renderer.close()

    def post_loop(self):
        if self.error:
            self.error.display()
        if self.hold_timer and time.time() > self.hold_timer:
            if self.hold_next:
                self.do_next()
            elif self.hold_previous:
                self.do_previous()
            self.hold_timer = time.time() + self.PAGE_NAVIGATION_SPEED
        _, self.pos = self.draggable.check()  # Check if user is panning
        if self.config.debug:
            pe.draw.circle(pe.colors.red, self.pos, 5)
            self.debug_display.text = self.debug_text
            self.debug_display.init()
            self.debug_display.rect.bottomright = self.size
            self.debug_display.display()

    @property
    def debug_text(self):
        if self.notebook_renderer and self.notebook_renderer.expanded_notebook:
            rm_position = tuple(
                (
                        (
                                (mp - center) +  # Get the offset from the center
                                (reference_size / 2)  # Add half of size of the page
                        )
                        / reference_size  # Divide to get a 0-1 coordinate
                ) * frame_size  # Multiply by the frame size to get the real position
                for mp, center, reference_size, frame_size in zip(
                    pe.mouse.pos(),
                    self.center,
                    self.zoom_reference_size,
                    self.notebook_renderer.expanded_notebook.frame_size,
                )  # Zip all required positional values
            )
        else:
            rm_position = (0, 0)
        return (
            f"Zoom: {self.base_zoom:.2f} * {self._zoom:.2f} | "
            f"Center: {self.center} | "
            f"Page: {self.current_page_index} | "
            f"RM Pos: {rm_position[0]:.2f}, {rm_position[1]:.2f}"
        )


class DocumentViewerUI(pe.ChildContext):
    LAYER = pe.BEFORE_POST_LAYER

    def __init__(self, parent: 'GUI', viewer: 'DocumentViewer'):
        self.viewer = viewer
        self.document = viewer.document
        self.x_rect = pe.Rect(0, 0, parent.ratios.document_viewer_x_width, parent.ratios.document_viewer_x_height)
        self.x_icon = parent.icons['x_small']
        self.x_icon_rect = pe.Rect(0, 0, *self.x_icon.size)
        super().__init__(parent)
        self.align_x_rect()

    def loop(self):
        pe.draw.rect(Defaults.BUTTON_DISABLED_LIGHT_COLOR, self.x_rect,
                     edge_rounding=self.ratios.document_viewer_x_rounding)
        pe.draw.rect(Defaults.SELECTED, self.x_rect, self.ratios.document_viewer_x_outline,
                     edge_rounding=self.ratios.document_viewer_x_rounding - self.ratios.document_viewer_x_outline)
        self.x_icon.display(self.x_icon_rect.topleft)
        pe.button.action(
            self.x_rect, name=f'document_viewer_x<{id(self.viewer)}>',
            action_set={
                'l_click': {
                    'action': self.viewer.close
                },
                'hover_draw': {
                    'action': pe.draw.rect,
                    'args': (Defaults.BUTTON_ACTIVE_COLOR, self.x_rect),
                    'kwargs': {
                        'edge_rounding': self.ratios.document_viewer_x_rounding
                    }
                }
            }
        )

    def align_x_rect(self):
        self.x_rect.topright = (self.width, 0)
        self.x_rect.move_ip(-self.ratios.document_viewer_x_margin, self.ratios.document_viewer_x_margin)
        self.x_icon_rect.center = self.x_rect.center


class DocumentViewer(pe.ChildContext):
    LAYER = pe.AFTER_LOOP_LAYER

    screens: 'Queue'
    icons: Dict[str, pe.Image]
    PROBLEMATIC_DOCUMENTS = set()
    EVENT_HOOK_NAME = 'document_viewer_resize_check<{0}>'

    document: 'Document'
    top_puller: DraggablePuller
    ui: DocumentViewerUI
    document_renderer: DocumentRenderer

    def __init__(self, parent: 'GUI', document_uuid: str):
        super().__init__(parent)
        top_rect = pe.Rect(
            0, 0,
            parent.width,
            parent.ratios.document_viewer_top_draggable_height
        )
        self.document: Document = parent.api.documents[document_uuid]
        self.document.check()

        self.top_puller = DraggablePuller(
            parent, top_rect,
            detect_y=-top_rect.height, callback_y=self.close,
            draw_callback_y=self.draw_close_indicator
        )
        self.ui = DocumentViewerUI(parent, self)
        try:
            self.document_renderer = DocumentRenderer(parent, self.document)
        except UnusableContent:
            self.PROBLEMATIC_DOCUMENTS.add(document_uuid)
            raise CannotRenderDocument(self.document)

        self.api.add_hook(self.EVENT_HOOK_NAME.format(id(self)), self.resize_check_hook)

    def loop(self):
        self.document_renderer()
        self.top_puller()
        self.ui()

    def handle_event(self, event):
        self.document_renderer.handle_event(event)
        if pe.event.key_DOWN(pe.K_ESCAPE):
            self.close()

    def resize_check_hook(self, event):
        if isinstance(event, ResizeEvent):
            self.top_puller.rect.width = event.new_size[0]
            self.top_puller.draggable.area = (event.new_size[0], self.top_puller.draggable.area[1])
            self.ui.align_x_rect()

    def close(self):
        self.document_renderer.close()
        self.api.remove_hook(self.EVENT_HOOK_NAME.format(id(self)))
        if self.config.save_after_close:
            self.document.content.c_pages.last_opened.value = self.document_renderer.last_opened_uuid
            self.document.metadata.last_opened_page = self.document_renderer.current_page_index
            self.document.metadata.last_opened = models.now_time()
            threading.Thread(target=self.api.upload, args=(self.document,), kwargs={'unload': True}).start()
        else:
            self.document.unload_files()
        del self.screens.queue[-1]

    def draw_close_indicator(self):
        # Handles the closing indicator when pulling down
        icon = self.icons['chevron_down']
        icon_rect = pe.Rect(0, 0, *icon.size)
        top = self.top_puller.rect.centery
        bottom = min(self.height // 4, pe.mouse.pos()[1])  # Limit the bottom to 1/4 of the screen

        # Calculate the center of the icon
        icon_rect.centerx = self.top_puller.rect.centerx
        icon_rect.centery = top + (bottom - top) * .5
        # Lerp to half of the length between the top and the bottom points

        # Make a rect between the top puller and the bottom icon rect
        outline_rect = pe.Rect(0, 0, icon_rect.width, icon_rect.bottom - self.top_puller.rect.centery)
        outline_rect.midbottom = icon_rect.midbottom

        # Inflate the rect to make it an outline
        outline_rect.inflate_ip(self.ratios.pixel(5), self.ratios.pixel(5))

        # Draw the outline, the line and the arrow icon
        pe.draw.rect(
            Defaults.BACKGROUND, outline_rect,
            edge_rounding_topleft=0,
            edge_rounding_topright=0,
            edge_rounding_bottomleft=self.ratios.document_viewer_top_arrow_rounding,
            edge_rounding_bottomright=self.ratios.document_viewer_top_arrow_rounding
        )
        pe.draw.line(Defaults.LINE_GRAY,
                     (x_pos := self.top_puller.rect.centerx - self.ratios.pixel(2), self.top_puller.rect.centery),
                     (x_pos, icon_rect.centery), self.ratios.pixel(3))
        icon.display(icon_rect.topleft)
