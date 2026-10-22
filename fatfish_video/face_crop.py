"""Local frontal-face detection; never fall back to using an entire body photo."""

from pathlib import Path


def crop_face(source: Path, destination: Path):
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ValueError('自动截脸需要 OpenCV，请执行 python -m pip install ".[web]"') from exc
    image = cv2.imdecode(np.frombuffer(source.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("无法解码脸部图片，请使用 PNG 或 JPEG")
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("请选择彩色人像图片")
    gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(40, 40))
    if not len(faces):
        raise ValueError("没有检测到清晰正脸，请换一张正面人像；不会把整张身体照片当作脸使用")
    x, y, width, height = map(int, max(faces, key=lambda face: int(face[2]) * int(face[3])))
    # Keep forehead through chin; exclude most scalp and never extend to shoulders.
    left = max(0, round(x - width * .07))
    top = max(0, round(y + height * .03))
    right = min(image.shape[1], round(x + width * 1.07))
    bottom = min(image.shape[0], round(y + height * 1.20))
    cropped = image[top:bottom, left:right]
    destination.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", cropped)
    if not ok:
        raise ValueError("截脸图片保存失败")
    destination.write_bytes(encoded.tobytes())
    return {"detected": [x, y, width, height], "crop": [left, top, right - left, bottom - top],
            "source_size": [image.shape[1], image.shape[0]], "size": [right - left, bottom - top]}
