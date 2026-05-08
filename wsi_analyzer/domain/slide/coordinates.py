from dataclasses import dataclass


@dataclass(frozen=True)
class Level0Point:
    x: float
    y: float


@dataclass(frozen=True)
class Level0Box:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    def translate(self, dx: float, dy: float) -> "Level0Box":
        return Level0Box(
            x1=self.x1 + dx,
            y1=self.y1 + dy,
            x2=self.x2 + dx,
            y2=self.y2 + dy,
        )


@dataclass(frozen=True)
class PatchCoordinate:
    x: int
    y: int
    size: int
    level: int
    downsample: float

    @property
    def level0_origin(self) -> tuple:
        return self.x, self.y

    def level0_width(self) -> float:
        return self.size * self.downsample

    def level0_height(self) -> float:
        return self.size * self.downsample
