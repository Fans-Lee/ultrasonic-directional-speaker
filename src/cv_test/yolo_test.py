import cv2
from ultralytics import YOLO

CAMERA_INDEX = 1       # 外接摄像头常见为1，但不能永久写死
CAMERA_ROTATION = 180  # 当前摄像头物理反装

cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_FPS, 30)

model = YOLO("yolo26n.pt")

while True:
    ok, frame = cap.read()
    if not ok or frame is None:
        break

    # 必须在YOLO之前校正方向
    if CAMERA_ROTATION == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)

    result = model.predict(
        frame,
        classes=[0],
        conf=0.45,
        imgsz=512,
        verbose=False,
    )[0]

    annotated = result.plot()
    cv2.imshow("person tracking", annotated)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()