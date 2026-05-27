import numpy as np


def control(left_img: np.ndarray, right_img: np.ndarray, timestamp: float) -> tuple[float, float]:
    steering = 0.0
    speed = 1.0
    return steering, speed