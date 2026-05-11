from wsi_analyzer.domain.analysis.inference_geometry import InferenceGeometry


def _make_geom(mi=512, tm=2.0, st=400, sm=0.5, op=None, rl=1, rd=4.0):
    return InferenceGeometry.from_config_and_slide(
        model_input_size=mi, target_mpp=tm, level0_stride=st,
        slide_mpp=sm, objective_power=op, read_level=rl, read_downsample=rd,
    )


class TestInferenceGeometry:
    def test_with_slide_mpp(self):
        g = _make_geom(sm=0.5, op=None)
        assert g.model_input_size == 512
        assert g.level0_window_size == 2048
        assert g.local_to_level0_scale == 4.0
        assert g.level0_stride == 400

    def test_missing_slide_mpp(self):
        g = _make_geom(sm=None, op=None)
        assert g.level0_window_size == 512
        assert g.local_to_level0_scale == 1.0

    def test_slide_mpp_zero(self):
        g = _make_geom(sm=0.0, op=None)
        assert g.level0_window_size == 512

    def test_scale_with_different_mpp(self):
        g = _make_geom(sm=2.0, tm=1.0, st=200, rl=0, rd=1.0)
        assert g.level0_window_size == 256
        assert g.local_to_level0_scale == 0.5

    def test_minimum_window_size(self):
        g = _make_geom(sm=10.0, tm=0.001, st=1, rl=0, rd=1.0)
        assert g.level0_window_size >= 1

    def test_objective_power_fallback_40x(self):
        """40x objective => estimated MPP = 10.0/40 = 0.25"""
        g = _make_geom(tm=2.0, sm=None, op=40.0, rl=0, rd=1.0)
        assert g.slide_mpp == 0.25
        assert g.level0_window_size == 4096

    def test_objective_power_fallback_20x(self):
        """20x => estimated MPP = 0.5"""
        g = _make_geom(tm=2.0, sm=None, op=20.0, rl=0, rd=1.0)
        assert g.slide_mpp == 0.5
        assert g.level0_window_size == 2048

    def test_objective_power_does_not_override_real_mpp(self):
        """Real slide_mpp should take priority over objective_power."""
        g = _make_geom(sm=0.5, op=40.0)
        assert g.slide_mpp == 0.5  # not overridden
        assert g.level0_window_size == 2048

    def test_micropapillary_metadata_scenario(self):
        """model_input=768, target_mpp=0.1725, slide_mpp=0.25
        -> level0_window = round(768 * 0.1725 / 0.25) = 530
        """
        g = _make_geom(mi=768, tm=0.1725, sm=0.25, st=530, rl=1, rd=4.0)
        assert g.model_input_size == 768
        assert g.target_mpp == 0.1725
        assert g.slide_mpp == 0.25
        assert g.level0_window_size == 530
        assert abs(g.local_to_level0_scale - 0.690) < 0.01
        assert g.level0_stride == 530
