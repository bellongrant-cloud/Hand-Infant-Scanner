"""Image loading, normalization, segmentation, enhancement and binarization
for ridge (fingerprint / palm print) images.
"""
from __future__ import annotations

import numpy as np
import cv2


def load_grayscale(path: str) -> np.ndarray:
    """Load an image from a scanner as a float64 grayscale array in [0, 255]."""
    image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Could not read image at {path!r}")
    return image.astype(np.float64)


def normalize(image: np.ndarray, target_mean: float = 100.0, target_var: float = 100.0) -> np.ndarray:
    """Normalize image mean/variance (Hong, Wan & Jain style normalization).

    This equalizes brightness/contrast differences between scanners without
    changing the ridge/valley structure.
    """
    mean = image.mean()
    var = image.var()
    if var == 0:
        return np.full_like(image, target_mean)
    normalized = target_mean + np.sign(image - mean) * np.sqrt(
        (target_var * (image - mean) ** 2) / var
    )
    return normalized


def segmentation_mask(image: np.ndarray, block_size: int = 16, threshold_ratio: float = 0.1) -> np.ndarray:
    """Estimate a foreground mask (skin/ridge area vs. blank background).

    Uses block-wise standard deviation: background regions of a scan are
    flat (low local variance) while ridged skin has texture.
    """
    h, w = image.shape
    mask = np.zeros_like(image, dtype=bool)
    stds = []
    blocks = []
    for y in range(0, h, block_size):
        for x in range(0, w, block_size):
            block = image[y : y + block_size, x : x + block_size]
            if block.size == 0:
                continue
            std = block.std()
            stds.append(std)
            blocks.append((y, x))
    if not stds:
        return np.ones_like(image, dtype=bool)
    threshold = max(np.mean(stds) * threshold_ratio, 1e-6)
    for std, (y, x) in zip(stds, blocks):
        if std >= threshold:
            mask[y : y + block_size, x : x + block_size] = True
    # Clean up the mask with morphological closing/opening to remove speckle.
    mask_u8 = (mask.astype(np.uint8)) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (block_size, block_size))
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel)
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, kernel)
    return mask_u8 > 0


def gabor_enhance(
    image: np.ndarray,
    orientation_field: np.ndarray,
    frequency_field: np.ndarray,
    block_size: int,
    kernel_size: int = 15,
) -> np.ndarray:
    """Enhance ridges by convolving each block with a Gabor kernel tuned to
    the block's local ridge orientation and frequency.
    """
    h, w = image.shape
    out = np.zeros_like(image, dtype=np.float64)
    blocks_y = orientation_field.shape[0]
    blocks_x = orientation_field.shape[1]

    pad = kernel_size // 2
    padded = cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_REFLECT)

    for by in range(blocks_y):
        for bx in range(blocks_x):
            freq = frequency_field[by, bx]
            if freq <= 0:
                continue
            theta = orientation_field[by, bx]
            wavelength = 1.0 / freq
            # cv2.getGaborKernel theta is measured from the x-axis; ridge
            # orientation is perpendicular to the Gabor stripe direction.
            kernel = cv2.getGaborKernel(
                (kernel_size, kernel_size),
                sigma=kernel_size / 3.0,
                theta=theta + np.pi / 2,
                lambd=max(wavelength, 3.0),
                gamma=0.7,
                psi=0,
                ktype=cv2.CV_64F,
            )
            y0, y1 = by * block_size, min((by + 1) * block_size, h)
            x0, x1 = bx * block_size, min((bx + 1) * block_size, w)
            if y0 >= y1 or x0 >= x1:
                continue
            region = padded[y0 : y1 + 2 * pad, x0 : x1 + 2 * pad]
            filtered = cv2.filter2D(region, cv2.CV_64F, kernel)
            out[y0:y1, x0:x1] = filtered[pad : pad + (y1 - y0), pad : pad + (x1 - x0)]
    return out


def binarize(image: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Otsu-threshold the enhanced image into a boolean ridge mask (True = ridge)."""
    img_u8 = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, binary = cv2.threshold(img_u8, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    result = binary > 0
    if mask is not None:
        result &= mask
    return result


def skeletonize(binary: np.ndarray) -> np.ndarray:
    """Thin a binary ridge mask to 1-pixel-wide ridge lines."""
    from skimage.morphology import skeletonize as sk_skeletonize

    return sk_skeletonize(binary)
