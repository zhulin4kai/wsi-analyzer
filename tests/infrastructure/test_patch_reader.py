from unittest.mock import MagicMock, patch

from PIL import Image


class TestPatchReader:
    def test_level0_read(self):
        from wsi_analyzer.infrastructure.imaging.patch_reader import PatchReader

        mock_engine = MagicMock()
        mock_engine.read_region.return_value = Image.new("RGBA", (512, 512))
        reader = PatchReader(mock_engine, 0, 1.0, 512)
        img = reader.read((100, 200))

        assert img.size == (512, 512)
        assert img.mode == "RGB"
        mock_engine.read_region.assert_called_once()

    def test_level_n_read_with_resize(self):
        from wsi_analyzer.infrastructure.imaging.patch_reader import PatchReader

        mock_engine = MagicMock()
        # level-downsample=4.0, patch_size=512 → ts=128
        mock_engine.read_region.return_value = Image.new("RGBA", (128, 128))
        reader = PatchReader(mock_engine, 1, 4.0, 512)
        img = reader.read((0, 0))

        assert img.size == (512, 512)
