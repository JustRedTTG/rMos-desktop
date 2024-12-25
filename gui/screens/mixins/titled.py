from typing import TYPE_CHECKING

import pygameextra as pe

from gui.defaults import Defaults

if TYPE_CHECKING:
    from gui.aspect_ratio import Ratios


class TitledMixin:
    TITLE = "Title"
    ratios: 'Ratios'
    TITLE_COLORS = Defaults.TEXT_COLOR
    
    def handle_title(self, title: str = None):
        self.title = pe.Text(title or self.TITLE, Defaults.MAIN_MENU_FONT, self.ratios.titled_mixin_title_size,
                             colors=self.TITLE_COLORS)

        self.title.rect.topleft = (
            self.ratios.titled_mixin_title_padding,
            self.ratios.titled_mixin_title_padding
        )

    @property
    def title_bottom(self):
        return self.title.rect.bottom + self.ratios.main_menu_top_padding