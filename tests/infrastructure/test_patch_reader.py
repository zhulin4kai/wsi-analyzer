from unittest.mock import MagicMock

from PIL import Image

from wsi_analyzer.domain.slide.coordinates import PatchCoordinate


class TestPatchReader:
    def test_level0_read(self):
        from wsi_analyzer.infrastructure.imaging.patch_reader import PatchReader

        mock_engine = MagicMock()
        mock_engine.read_region.return_value = Image.new("RGBA", (512, 512))
        reader = PatchReader(mock_engine, 0, 1.0, 512)
        coord = PatchCoordinate(x=100, y=200, size=512, read_level=0, read_level_downsample=1.0)
        img = reader.read(coord)

        assert img.size == (512, 512)
        assert img.mode == "RGB"
        mock_engine.read_region.assert_called_once()

    def test_level_n_read_with_resize(self):
        from wsi_analyzer.infrastructure.imaging.patch_reader import PatchReader

        mock_engine = MagicMock()
        mock_engine.read_region.return_value = Image.new("RGBA", (128, 128))
        reader = PatchReader(mock_engine, 1, 4.0, 512)
        coord = PatchCoordinate(x=0, y=0, size=512, read_level=1, read_level_downsample=4.0)
        img = reader.read(coord)

        assert img.size == (512, 512)
