from config import HUD_MARGIN
from wsi_analyzer.ui.widgets import InfoBarOverlay, ScaleBarOverlay


class HudController:
    def __init__(self, viewer, mag_widget):
        self.viewer = viewer
        self.mag_widget = mag_widget
        self.scale_bar = ScaleBarOverlay(viewer)
        self.info_bar = InfoBarOverlay(viewer)

    def bind(self):
        self.viewer.zoom_changed.connect(self.scale_bar.on_zoom_changed)
        self.viewer.mouse_scene_pos_changed.connect(self.info_bar.on_mouse_moved)
        self.viewer.zoom_changed.connect(self.mag_widget.on_zoom_changed)
        self.mag_widget.zoom_to_scale.connect(self.viewer.set_scale)

    def on_wsi_loaded(self, metadata):
        mpp = metadata.mpp
        mpp_x = mpp[0] if mpp else None
        mpp_y = mpp[1] if mpp else None

        self.scale_bar.load(mpp_x, mpp_y)
        self.info_bar.load(metadata)
        self.mag_widget.load(metadata.objective_power)

        current_scale = self.viewer.transform().m11()
        self.scale_bar.on_zoom_changed(current_scale)
        self.mag_widget.on_zoom_changed(current_scale)

        self.reposition()

    def reposition(self):
        vw = self.viewer.width()
        vh = self.viewer.height()
        margin = HUD_MARGIN

        self.scale_bar.move(margin, vh - self.scale_bar.height() - margin)
        self.info_bar.move(vw - self.info_bar.width() - margin, vh - self.info_bar.height() - margin)

    def set_scale_bar_visible(self, visible: bool):
        self.scale_bar.setVisible(visible)

    def set_info_bar_visible(self, visible: bool):
        self.info_bar.setVisible(visible)

    def set_magnification_visible(self, visible: bool):
        self.mag_widget.setVisible(visible)
