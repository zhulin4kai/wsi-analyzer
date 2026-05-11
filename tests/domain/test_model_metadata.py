import pytest
from wsi_analyzer.domain.model.model_metadata import ModelMetadata


class TestModelMetadata:
    def test_from_dict_basic(self):
        data = {
            "model_name": "test_model",
            "backend": "ultralytics_yolo",
            "task": "detect",
            "model_input_size": 768,
            "target_mpp": 0.1725,
            "classes": {0: "micropapillary"},
        }
        m = ModelMetadata.from_dict(data)
        assert m.model_name == "test_model"
        assert m.model_input_size == 768
        assert m.target_mpp == 0.1725
        assert m.classes == {0: "micropapillary"}

    def test_from_dict_list_classes(self):
        data = {
            "model_name": "m",
            "backend": "yolo",
            "task": "detect",
            "model_input_size": 512,
            "target_mpp": 2.0,
            "classes": ["benign", "malignant"],
        }
        m = ModelMetadata.from_dict(data)
        assert m.classes == {0: "benign", 1: "malignant"}

    def test_from_dict_nested_training_patch(self):
        data = {
            "model_name": "m",
            "backend": "yolo",
            "task": "detect",
            "training_patch": {
                "model_input_size": 640,
                "source_mpp": 1.0,
            },
        }
        m = ModelMetadata.from_dict(data)
        assert m.model_input_size == 640
        assert m.target_mpp == 1.0

    def test_from_dict_dataset_fields(self):
        data = {
            "model_name": "m",
            "backend": "yolo",
            "task": "detect",
            "model_input_size": 512,
            "target_mpp": 0.5,
            "dataset": {
                "name": "hospital_x",
                "slide_mpp": 0.25,
            },
        }
        m = ModelMetadata.from_dict(data)
        assert m.dataset_name == "hospital_x"

    def test_from_dict_missing_model_input_size_raises(self):
        with pytest.raises(ValueError, match="model_input_size"):
            ModelMetadata.from_dict({
                "model_name": "m", "backend": "yolo", "task": "detect",
                "target_mpp": 1.0,
            })

    def test_from_dict_missing_target_mpp_raises(self):
        with pytest.raises(ValueError, match="target_mpp"):
            ModelMetadata.from_dict({
                "model_name": "m", "backend": "yolo", "task": "detect",
                "model_input_size": 512,
            })

    def test_from_dict_source_mpp(self):
        data = {
            "model_name": "m", "backend": "yolo", "task": "detect",
            "model_input_size": 512, "target_mpp": 2.0,
            "source_mpp": 0.5,
        }
        m = ModelMetadata.from_dict(data)
        assert m.source_mpp == 0.5

    def test_from_dict_defaults(self):
        data = {
            "model_name": "m", "backend": "yolo", "task": "detect",
            "model_input_size": 512, "target_mpp": 1.0,
        }
        m = ModelMetadata.from_dict(data)
        assert m.coordinate_system == "level0"
        assert m.trained_level == 0

    def test_to_dict_roundtrip(self):
        data = {
            "model_name": "m", "backend": "yolo", "task": "detect",
            "model_input_size": 768, "target_mpp": 0.1725,
            "classes": {0: "micropapillary"},
            "dataset_name": "hosp_x",
            "source_mpp": 0.1725,
        }
        m = ModelMetadata.from_dict(data)
        d = m.to_dict()
        assert d["model_input_size"] == 768
        assert d["target_mpp"] == 0.1725
        assert d["dataset_name"] == "hosp_x"

    def test_invalid_model_input_size(self):
        with pytest.raises(ValueError):
            ModelMetadata(
                model_name="m", backend="yolo", task="detect",
                model_input_size=0, target_mpp=1.0,
            )

    def test_invalid_target_mpp(self):
        with pytest.raises(ValueError):
            ModelMetadata(
                model_name="m", backend="yolo", task="detect",
                model_input_size=512, target_mpp=0,
            )

    def test_rejects_bool_model_input_size(self):
        """bool is silently cast to int (True→1, False→0) by int().
        _resolve_int must reject it to prevent metadata misparse.
        """
        data = {
            "model_name": "m", "backend": "yolo", "task": "detect",
            "model_input_size": True, "target_mpp": 1.0,
        }
        with pytest.raises(ValueError, match="model_input_size"):
            ModelMetadata.from_dict(data)

    def test_rejects_bool_target_mpp(self):
        data = {
            "model_name": "m", "backend": "yolo", "task": "detect",
            "model_input_size": 512, "target_mpp": False,
        }
        with pytest.raises(ValueError, match="target_mpp"):
            ModelMetadata.from_dict(data)

    def test_string_model_input_size_accepted(self):
        data = {
            "model_name": "m", "backend": "yolo", "task": "detect",
            "model_input_size": "768", "target_mpp": 0.5,
        }
        m = ModelMetadata.from_dict(data)
        assert m.model_input_size == 768

    def test_string_target_mpp_accepted(self):
        data = {
            "model_name": "m", "backend": "yolo", "task": "detect",
            "model_input_size": 512, "target_mpp": "0.1725",
        }
        m = ModelMetadata.from_dict(data)
        assert m.target_mpp == 0.1725
