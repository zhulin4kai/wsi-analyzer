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
    """A single inference patch in WSI Level-0 coordinates.

    Fields:
        x, y:             Top-left origin in Level-0 pixels.
        level0_size:      Side length of the physical region covered on Level-0.
        model_input_size: Side length of the image tensor fed to the model.
        read_level:       OpenSlide pyramid level for I/O.
        read_downsample:  Downsample factor of read_level vs Level-0.
    """

    x: int
    y: int
    level0_size: int
    model_input_size: int
    read_level: int
    read_downsample: float

    @property
    def level0_origin(self) -> tuple[int, int]:
        return self.x, self.y

    @property
    def level0_box(self) -> Level0Box:
        return Level0Box(
            x1=float(self.x),
            y1=float(self.y),
            x2=float(self.x + self.level0_size),
            y2=float(self.y + self.level0_size),
        )

    @property
    def local_to_level0_scale(self) -> float:
        return self.level0_size / self.model_input_size

    # ----- backward-compat aliases for code that still uses old field names -----

    @property
    def size(self) -> int:
        """Deprecated: use level0_size or model_input_size explicitly."""
        return self.level0_size

    @property
    def level(self) -> int:
        """Deprecated: use read_level."""
        return self.read_level

    @property
    def downsample(self) -> float:
        """Deprecated: use read_downsample."""
        return self.read_downsample

    def level0_width(self) -> float:
        return float(self.level0_size)

    def level0_height(self) -> float:
        return float(self.level0_size)
