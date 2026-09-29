from types import TracebackType

import numpy as np
from numpy.typing import NDArray
from rasterio.enums import Resampling

class DatasetReader:
    def read(self, indexes: int, *, out_shape: tuple[int, int] | None = ...,
             resampling: Resampling = ...) -> NDArray[np.float32]: ...
    def __enter__(self) -> DatasetReader: ...
    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None: ...

def open(fp: str) -> DatasetReader: ...
