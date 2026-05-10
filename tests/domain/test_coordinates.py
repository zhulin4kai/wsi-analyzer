from wsi_analyzer.domain.slide.coordinates import Level0Box, Level0Point, PatchCoordinate


class TestLevel0Point:
    def test_create(self):
        p = Level0Point(100.0, 200.0)
        assert p.x == 100.0
        assert p.y == 200.0

    def test_immutable(self):
        p = Level0Point(0, 0)
        try:
            setattr(p, 'x', 1)
            assert False, "should raise"
        except Exception:
            pass


class TestLevel0Box:
    def test_create(self):
        b = Level0Box(10, 20, 30, 40)
        assert b.x1 == 10
        assert b.x2 == 30
        assert b.y1 == 20
        assert b.y2 == 40

    def test_width_height(self):
        b = Level0Box(10, 20, 110, 70)
        assert b.x2 - b.x1 == 100
        assert b.y2 - b.y1 == 50

    def test_immutable(self):
        b = Level0Box(0, 0, 1, 1)
        try:
            setattr(b, 'x1', 99)
            assert False, "should raise"
        except Exception:
            pass

    def test_translate(self):
        b = Level0Box(10, 20, 30, 40)
        moved = b.translate(100, 200)
        assert moved.x1 == 110
        assert moved.y1 == 220
        assert moved.x2 == 130
        assert moved.y2 == 240


class TestPatchCoordinate:
    def test_create(self):
        pc = PatchCoordinate(x=512, y=1024, size=512, level=0, downsample=1.0)
        assert pc.x == 512
        assert pc.y == 1024
        assert pc.size == 512
        assert pc.level == 0
        assert pc.downsample == 1.0

    def test_level0_offset(self):
        pc = PatchCoordinate(x=0, y=0, size=256, level=2, downsample=4.0)
        # The Level-0 physical extent
        assert pc.level0_width() == 1024.0
        assert pc.level0_height() == 1024.0

    def test_immutable(self):
        pc = PatchCoordinate(x=0, y=0, size=512, level=0, downsample=1.0)
        try:
            setattr(pc, 'x', 99)
            assert False, "should raise"
        except Exception:
            pass
