import base64
import io
import json
import mimetypes
import os
import secrets
import sqlite3
from datetime import date, datetime
from hashlib import pbkdf2_hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
MODELS_DIR = BASE_DIR / "models"
LEGACY_SQLITE_PATH = BASE_DIR / "pet_homecoming.db"
HOST = "127.0.0.1"
PORT = 8000
DB_HOST = os.environ.get("PET_HOME_DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PET_HOME_DB_PORT", "3306"))
DB_USER = os.environ.get("PET_HOME_DB_USER", "root")
DB_PASSWORD = os.environ.get("PET_HOME_DB_PASSWORD", "")
DB_NAME = os.environ.get("PET_HOME_DB_NAME", "pet_homecoming")
DB_CHARSET = "utf8mb4"
YOLO_CLASS_MAP = {
    "dog": "鐘被",
    "cat": "鐚被",
    "bird": "楦熺被",
}
YOLO_LABELS = {
    "dog": "犬类",
    "cat": "猫类",
    "bird": "鸟类",
}
CATEGORY_LABELS = {
    "閻橆剛琚?": "犬类",
    "閻氼偆琚?": "猫类",
    "妤︾喓琚?": "鸟类",
    "灏忓瀷瀹犵墿": "小型宠物",
    "寰呬汉宸ョ‘璁?": "待人工确认",
}
YOLO_RUNTIME = {
    "attempted": False,
    "model": None,
    "source": os.environ.get("PET_HOME_YOLO_MODEL") or str(MODELS_DIR / "yolov8n.pt"),
    "error": "",
}
DB_RUNTIME = {"database_ready": False}


def now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def json_safe(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    return value


def convert_sql_placeholders(sql: str) -> str:
    return sql.replace("?", "%s")


class MySQLCursorCompat:
    def __init__(self, raw_cursor):
        self.raw_cursor = raw_cursor

    def execute(self, sql: str, params: tuple | list | None = None):
        self.raw_cursor.execute(convert_sql_placeholders(sql), params or ())
        return self

    def fetchone(self):
        return self.raw_cursor.fetchone()

    def fetchall(self):
        return self.raw_cursor.fetchall()

    @property
    def lastrowid(self) -> int:
        return self.raw_cursor.lastrowid

    def close(self) -> None:
        self.raw_cursor.close()


class MySQLConnectionCompat:
    def __init__(self, raw_connection):
        self.raw_connection = raw_connection

    def execute(self, sql: str, params: tuple | list | None = None) -> MySQLCursorCompat:
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def cursor(self) -> MySQLCursorCompat:
        return MySQLCursorCompat(self.raw_connection.cursor())

    def executescript(self, script: str) -> None:
        statements = [statement.strip() for statement in script.split(";") if statement.strip()]
        for statement in statements:
            cursor = self.cursor()
            try:
                cursor.execute(statement)
            finally:
                cursor.close()

    def commit(self) -> None:
        self.raw_connection.commit()

    def rollback(self) -> None:
        self.raw_connection.rollback()

    def close(self) -> None:
        self.raw_connection.close()


def open_mysql_connection(database: str | None = None):
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError as error:
        raise RuntimeError("PyMySQL 未安装，请先执行 `pip install -r backend/requirements.txt`。") from error

    options: dict[str, Any] = {
        "host": DB_HOST,
        "port": DB_PORT,
        "user": DB_USER,
        "password": DB_PASSWORD,
        "charset": DB_CHARSET,
        "cursorclass": DictCursor,
        "autocommit": False,
    }
    if database:
        options["database"] = database
    try:
        return pymysql.connect(**options)
    except pymysql.MySQLError as error:
        target = database or "<server>"
        raise RuntimeError(
            f"MySQL 连接失败：{DB_HOST}:{DB_PORT}/{target}。"
            "请检查 PET_HOME_DB_HOST、PET_HOME_DB_PORT、PET_HOME_DB_USER、"
            "PET_HOME_DB_PASSWORD、PET_HOME_DB_NAME 配置。"
            f"原始错误：{error}"
        ) from error


def ensure_database() -> None:
    if DB_RUNTIME["database_ready"]:
        return

    connection = open_mysql_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET {DB_CHARSET} COLLATE utf8mb4_unicode_ci"
        )
        connection.commit()
        DB_RUNTIME["database_ready"] = True
    finally:
        cursor.close()
        connection.close()


def get_db() -> MySQLConnectionCompat:
    ensure_database()
    return MySQLConnectionCompat(open_mysql_connection(DB_NAME))


def is_mysql_integrity_error(error: Exception) -> bool:
    try:
        import pymysql
    except ImportError:
        return False
    return isinstance(error, pymysql.err.IntegrityError)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, digest = stored.split("$", 1)
    return hash_password(password, salt) == f"{salt}${digest}"


def parse_data_url(data_url: str) -> tuple[str, bytes]:
    header, encoded = data_url.split(",", 1)
    mime_type = header.split(";")[0].split(":")[1]
    extension = mimetypes.guess_extension(mime_type) or ".jpg"
    return extension, base64.b64decode(encoded)


def save_image(data_url: str, prefix: str) -> str | None:
    if not data_url:
        return None
    extension, raw = parse_data_url(data_url)
    return save_binary_file(raw, prefix, extension)


def save_binary_file(raw: bytes, prefix: str, extension: str = ".jpg") -> str:
    file_name = f"{prefix}_{secrets.token_hex(8)}{extension}"
    target = UPLOAD_DIR / file_name
    target.write_bytes(raw)
    return f"/uploads/{file_name}"


def load_yolo_model():
    if YOLO_RUNTIME["attempted"]:
        return YOLO_RUNTIME["model"]

    YOLO_RUNTIME["attempted"] = True
    model_source = Path(YOLO_RUNTIME["source"])
    source = str(model_source)

    try:
        from ultralytics import YOLO

        if model_source.exists():
            YOLO_RUNTIME["model"] = YOLO(source)
        else:
            previous_cwd = Path.cwd()
            os.chdir(model_source.parent)
            try:
                YOLO_RUNTIME["model"] = YOLO(model_source.name)
            finally:
                os.chdir(previous_cwd)
        YOLO_RUNTIME["source"] = source
        YOLO_RUNTIME["error"] = ""
    except Exception as error:
        YOLO_RUNTIME["model"] = None
        YOLO_RUNTIME["error"] = str(error)

    return YOLO_RUNTIME["model"]


def build_yolo_overlay(image: Image.Image, detections: list[dict]) -> bytes:
    canvas = image.copy().convert("RGB")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    for detection in detections:
        left, top, right, bottom = detection["bbox"]
        label = f"{detection['model_label']} {detection['confidence']:.2f}"
        draw.rectangle((left, top, right, bottom), outline="#ff7a00", width=4)
        text_box = draw.textbbox((left, top), label, font=font)
        box_left, box_top, box_right, box_bottom = text_box
        badge_top = max(0, top - (box_bottom - box_top) - 8)
        badge = (left, badge_top, left + (box_right - box_left) + 12, badge_top + (box_bottom - box_top) + 8)
        draw.rectangle(badge, fill="#ff7a00")
        draw.text((badge[0] + 6, badge[1] + 4), label, fill="white", font=font)

    buffer = io.BytesIO()
    canvas.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def detect_with_yolo(image_bytes: bytes) -> dict:
    payload = {
        "provider": "ultralytics",
        "model": "",
        "status": "skipped",
        "error": "",
        "detections": [],
        "annotated_image_path": None,
    }

    if not image_bytes:
        return payload

    model = load_yolo_model()
    payload["model"] = Path(str(YOLO_RUNTIME["source"])).name
    if not model:
        payload["status"] = "unavailable"
        payload["error"] = YOLO_RUNTIME["error"] or "YOLO model is unavailable"
        return payload

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        result = model(image, verbose=False, conf=0.25, classes=[14, 15, 16], imgsz=960)[0]
        names = result.names
        detections: list[dict] = []

        for box in result.boxes or []:
            class_id = int(box.cls[0].item())
            confidence = round(float(box.conf[0].item()), 4)
            model_label = names[class_id] if isinstance(names, list) else names.get(class_id, str(class_id))
            model_label = str(model_label).lower()
            if model_label not in YOLO_CLASS_MAP:
                continue

            detections.append(
                {
                    "model_label": model_label,
                    "category": YOLO_CLASS_MAP[model_label],
                    "label": YOLO_LABELS.get(model_label, model_label),
                    "confidence": confidence,
                    "bbox": [round(float(value), 2) for value in box.xyxy[0].tolist()],
                }
            )

        detections.sort(key=lambda item: item["confidence"], reverse=True)
        payload["detections"] = detections

        if detections:
            overlay = build_yolo_overlay(image, detections)
            payload["annotated_image_path"] = save_binary_file(overlay, "pet_yolo", ".jpg")
            payload["status"] = "detected"
        else:
            payload["status"] = "no_target"
    except Exception as error:
        payload["status"] = "error"
        payload["error"] = str(error)

    return payload


def build_instant_recognition(yolo_result: dict) -> tuple[dict, str]:
    detections = yolo_result.get("detections") or []
    if detections:
        top_detection = detections[0]
        recognition = {
            "recognized_category": top_detection.get("category", ""),
            "recognized_category_label": top_detection.get("label", top_detection.get("model_label", "")),
            "recognized_state": "",
            "recognized_state_label": "待填写",
            "category_confidence": round(float(top_detection.get("confidence", 0)), 2),
            "state_confidence": 0,
            "category_source": "yolo",
            "notes": [
                "本地上传后已完成 YOLO 即时识别。",
                f"检测结果：{top_detection.get('label', top_detection.get('model_label', 'unknown'))}",
            ],
            "recommendations": ["请继续补全名称、状态、联系电话等信息后再提交。"],
            "yolo": {
                "provider": yolo_result.get("provider", "ultralytics"),
                "model": yolo_result.get("model", ""),
                "status": yolo_result.get("status", "skipped"),
                "error": yolo_result.get("error", ""),
                "detections": detections,
                "annotated_image_path": yolo_result.get("annotated_image_path"),
            },
        }
        return recognition, top_detection.get("model_label", "")

    if yolo_result.get("status") == "no_target":
        recognition = {
            "recognized_category": "other",
            "recognized_category_label": "其他",
            "recognized_state": "",
            "recognized_state_label": "待填写",
            "category_confidence": 0,
            "state_confidence": 0,
            "category_source": "yolo",
            "notes": ["YOLO 未检测到猫、狗或鸟，已归入“其他”。"],
            "recommendations": ["如果识别不对，可以手动改分类，再补全其余信息后提交。"],
            "yolo": {
                "provider": yolo_result.get("provider", "ultralytics"),
                "model": yolo_result.get("model", ""),
                "status": yolo_result.get("status", "no_target"),
                "error": yolo_result.get("error", ""),
                "detections": [],
                "annotated_image_path": yolo_result.get("annotated_image_path"),
            },
        }
        return recognition, "other"

    recognition = {
        "recognized_category": "",
        "recognized_category_label": "",
        "recognized_state": "",
        "recognized_state_label": "待填写",
        "category_confidence": 0,
        "state_confidence": 0,
        "category_source": "yolo",
        "notes": [f"YOLO 即时识别失败：{yolo_result.get('error', 'unknown error')}"],
        "recommendations": ["请稍后重试，或手动选择分类后继续填写。"],
        "yolo": {
            "provider": yolo_result.get("provider", "ultralytics"),
            "model": yolo_result.get("model", ""),
            "status": yolo_result.get("status", "error"),
            "error": yolo_result.get("error", ""),
            "detections": detections,
            "annotated_image_path": yolo_result.get("annotated_image_path"),
        },
    }
    return recognition, ""


def classify_type(name: str, description: str, hint: str, manual: str) -> tuple[str, float]:
    text = " ".join(filter(None, [name, description, hint, manual])).lower()
    if any(word in text for word in ["狗", "犬", "dog", "金毛", "拉布拉多", "泰迪"]):
        return "犬类", 0.91
    if any(word in text for word in ["猫", "cat", "英短", "布偶", "橘猫"]):
        return "猫类", 0.91
    if any(word in text for word in ["鸟", "bird", "鹦鹉"]):
        return "鸟类", 0.82
    if any(word in text for word in ["兔", "仓鼠", "hamster", "rabbit"]):
        return "小型宠物", 0.77
    if manual:
        return manual, 0.72
    return "待人工确认", 0.45


def classify_state(description: str, health: str, status: str, vision: dict | None) -> tuple[str, list[str], float]:
    text = " ".join(filter(None, [description, health, status])).lower()
    notes: list[str] = []
    score = 0.58

    if any(word in text for word in ["受伤", "流血", "骨折", "生病", "伤口", "虚弱", "呕吐"]):
        notes.append("文本包含受伤或生病信息，建议优先救治。")
        return "需救治", notes, 0.9

    if any(word in text for word in ["走失", "丢失", "拾获", "流浪", "found"]):
        notes.append("描述更接近走失或拾获场景。")
        state = "待寻主"
        score = 0.82
    elif any(word in text for word in ["领养", "adoption"]):
        notes.append("描述中包含领养信息。")
        state = "待领养"
        score = 0.84
    elif any(word in text for word in ["已归家", "已找到主人", "reunited"]):
        notes.append("描述显示宠物已归家。")
        state = "已归家"
        score = 0.88
    else:
        state = "待确认"

    if vision:
        brightness = float(vision.get("brightness", 0))
        contrast = float(vision.get("contrast", 0))
        if brightness < 70:
            notes.append("图片偏暗，建议补拍。")
            score -= 0.06
        if contrast < 20:
            notes.append("图片对比度较低，主体可能不够清晰。")
            score -= 0.04

    return state, notes, max(0.35, min(score, 0.95))


def build_recognition(payload: dict, yolo_result: dict | None = None) -> dict:
    category, category_confidence = classify_type(
        payload.get("name", ""),
        payload.get("description", ""),
        payload.get("recognition_hint", ""),
        payload.get("manual_category", ""),
    )
    state, notes, state_confidence = classify_state(
        payload.get("description", ""),
        payload.get("health_note", ""),
        payload.get("status", ""),
        payload.get("vision_report"),
    )
    recommendations = [
        "补充正面和侧面照片，便于人工复核。",
        "补充发现地点、时间和明显特征。",
    ]
    if state == "需救治":
        recommendations.insert(0, "建议优先联系救治人员并记录伤情。")
    if state == "待领养":
        recommendations.insert(0, "建议补充疫苗、绝育和性格信息。")
    yolo_result = yolo_result or {}
    detections = yolo_result.get("detections") or []
    category_source = "rule"
    category_label = CATEGORY_LABELS.get(category, category)
    state_label = state
    if detections:
        top_detection = detections[0]
        category = top_detection["category"]
        category_confidence = top_detection["confidence"]
        category_source = "yolo"
        category_label = top_detection.get("label", CATEGORY_LABELS.get(category, category))
        detection_summary = "；".join(
            f"{item.get('label', item['model_label'])} {item['confidence']:.2f}" for item in detections[:3]
        )
        notes.insert(0, f"YOLO 检测结果: {detection_summary}")
        if len(detections) > 1:
            recommendations.insert(0, "检测到多个候选目标，建议人工确认主目标。")
    elif yolo_result.get("status") == "no_target":
        notes.append("YOLO 未检测到猫、狗或鸟，已回退到规则识别。")
        recommendations.append("请上传包含宠物主体的正面或全身照片。")
    elif yolo_result.get("status") == "unavailable":
        notes.append("YOLO 当前不可用，已回退到规则识别。")
    elif yolo_result.get("status") == "error":
        notes.append(f"YOLO 推理失败，已回退到规则识别: {yolo_result.get('error', 'unknown error')}")

    return {
        "recognized_category": category,
        "recognized_category_label": category_label,
        "recognized_state": state,
        "recognized_state_label": state_label,
        "category_confidence": round(category_confidence, 2),
        "state_confidence": round(state_confidence, 2),
        "category_source": category_source,
        "notes": notes,
        "recommendations": recommendations,
        "yolo": {
            "provider": yolo_result.get("provider", "ultralytics"),
            "model": yolo_result.get("model", ""),
            "status": yolo_result.get("status", "skipped"),
            "error": yolo_result.get("error", ""),
            "detections": detections,
            "annotated_image_path": yolo_result.get("annotated_image_path"),
        },
    }


def mysql_table_has_rows(connection: MySQLConnectionCompat, table_name: str) -> bool:
    row = connection.execute(f"SELECT 1 AS has_row FROM {table_name} LIMIT 1").fetchone()
    return bool(row)


def migrate_legacy_sqlite_data(connection: MySQLConnectionCompat) -> None:
    if not LEGACY_SQLITE_PATH.exists():
        return

    if any(
        mysql_table_has_rows(connection, table_name)
        for table_name in ["users", "sessions", "pets", "comments", "contacts"]
    ):
        return

    legacy = sqlite3.connect(LEGACY_SQLITE_PATH)
    legacy.row_factory = sqlite3.Row

    table_columns = {
        "users": [
            "id",
            "username",
            "password_hash",
            "full_name",
            "phone",
            "email",
            "address",
            "id_card",
            "role",
            "review_status",
            "review_note",
            "created_at",
        ],
        "sessions": ["token", "user_id", "created_at"],
        "pets": [
            "id",
            "creator_id",
            "name",
            "manual_category",
            "recognized_category",
            "breed",
            "age_desc",
            "status",
            "recognized_state",
            "found_location",
            "description",
            "health_note",
            "contact_phone",
            "adoption_status",
            "recognition_hint",
            "vision_report_json",
            "recognition_json",
            "image_path",
            "processed_image_path",
            "created_at",
        ],
        "comments": ["id", "pet_id", "user_id", "content", "created_at"],
        "contacts": ["id", "pet_id", "user_id", "contact_type", "phone", "message", "status", "created_at"],
    }

    try:
        cursor = connection.cursor()
        for table_name, columns in table_columns.items():
            rows = legacy.execute(f"SELECT {', '.join(columns)} FROM {table_name}").fetchall()
            if not rows:
                continue
            placeholders = ", ".join(["%s"] * len(columns))
            sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
            for row in rows:
                cursor.execute(sql, tuple(row[column] for column in columns))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        legacy.close()


def init_db() -> None:
    ensure_database()
    connection = get_db()
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            username VARCHAR(191) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            full_name VARCHAR(191) NOT NULL,
            phone VARCHAR(64) NOT NULL,
            email VARCHAR(191),
            address VARCHAR(255),
            id_card VARCHAR(191),
            role VARCHAR(32) NOT NULL DEFAULT 'user',
            review_status VARCHAR(32) NOT NULL DEFAULT 'pending',
            review_note TEXT,
            created_at DATETIME NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token VARCHAR(64) PRIMARY KEY,
            user_id BIGINT NOT NULL,
            created_at DATETIME NOT NULL,
            INDEX idx_sessions_user_id (user_id)
        );

        CREATE TABLE IF NOT EXISTS pets (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            creator_id BIGINT NOT NULL,
            name VARCHAR(191) NOT NULL,
            manual_category VARCHAR(64),
            recognized_category VARCHAR(64),
            breed VARCHAR(191),
            age_desc VARCHAR(191),
            status VARCHAR(64) NOT NULL,
            recognized_state VARCHAR(64),
            found_location VARCHAR(255),
            description TEXT,
            health_note TEXT,
            contact_phone VARCHAR(64) NOT NULL,
            adoption_status TEXT,
            recognition_hint TEXT,
            vision_report_json LONGTEXT,
            recognition_json LONGTEXT,
            image_path VARCHAR(255),
            processed_image_path VARCHAR(255),
            created_at DATETIME NOT NULL,
            INDEX idx_pets_creator_id (creator_id),
            INDEX idx_pets_created_at (created_at)
        );

        CREATE TABLE IF NOT EXISTS comments (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            pet_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            INDEX idx_comments_pet_id (pet_id),
            INDEX idx_comments_user_id (user_id)
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            pet_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            contact_type VARCHAR(32) NOT NULL,
            phone VARCHAR(64) NOT NULL,
            message TEXT NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'open',
            created_at DATETIME NOT NULL,
            INDEX idx_contacts_pet_id (pet_id),
            INDEX idx_contacts_user_id (user_id)
        );
        """
    )

    migrate_legacy_sqlite_data(connection)

    admin = connection.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    if not admin:
        connection.execute(
            """
            INSERT INTO users (
                username, password_hash, full_name, phone, email, address, id_card,
                role, review_status, review_note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "admin",
                hash_password("admin123"),
                "系统管理员",
                "13800000000",
                "admin@pet-homecoming.local",
                "管理中心",
                "ADMIN-0001",
                "admin",
                "approved",
                "系统默认管理员账号",
                now(),
            ),
        )

    connection.commit()
    connection.close()


class ApiHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_common_headers("application/json; charset=utf-8")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed)
            return
        if parsed.path.startswith("/uploads/"):
            self.serve_upload(parsed.path)
            return
        self.write_json(404, {"error": "资源不存在。"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.write_json(404, {"error": "接口不存在。"})
            return
        self.handle_api_post(parsed.path)

    def send_common_headers(self, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def write_json(self, status: int, payload: dict) -> None:
        self.send_response(status)
        self.send_common_headers("application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(json_safe(payload), ensure_ascii=False).encode("utf-8"))

    def read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def serve_upload(self, route_path: str) -> None:
        target = BASE_DIR / route_path.lstrip("/")
        if not target.exists() or not target.is_file():
            self.write_json(404, {"error": "文件不存在。"})
            return
        self.send_response(200)
        self.send_common_headers(mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def current_user(self, required: bool = False) -> dict | None:
        token = self.headers.get("Authorization", "").replace("Bearer ", "", 1).strip()
        if not token:
            if required:
                self.write_json(401, {"error": "请先登录。"})
            return None

        connection = get_db()
        user = connection.execute(
            """
            SELECT users.*
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        ).fetchone()
        connection.close()
        if not user and required:
            self.write_json(401, {"error": "登录状态已失效。"})
        return user

    def require_admin(self) -> dict | None:
        user = self.current_user(required=True)
        if not user:
            return None
        if user["role"] != "admin":
            self.write_json(403, {"error": "需要管理员权限。"})
            return None
        return user

    def serialize_user(self, row: dict) -> dict:
        return {key: row[key] for key in row.keys() if key != "password_hash"}

    def serialize_pet(self, row: dict) -> dict:
        item = dict(row)
        item["recognition"] = json.loads(row["recognition_json"] or "{}")
        item["vision_report"] = json.loads(row["vision_report_json"] or "{}")
        item.pop("recognition_json", None)
        item.pop("vision_report_json", None)
        return item

    def handle_api_get(self, parsed) -> None:
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/health":
            self.write_json(200, {"ok": True, "time": now()})
            return

        if path == "/api/config":
            self.write_json(
                200,
                {
                    "app_name": "Pet Homecoming Backend",
                    "api_base": f"http://{HOST}:{PORT}",
                    "upload_base": f"http://{HOST}:{PORT}/uploads",
                },
            )
            return

        if path == "/api/me":
            user = self.current_user(required=True)
            if user:
                self.write_json(200, {"user": self.serialize_user(user)})
            return

        if path == "/api/users/pending":
            if not self.require_admin():
                return
            connection = get_db()
            users = connection.execute(
                "SELECT * FROM users WHERE role = 'user' AND review_status = 'pending' ORDER BY created_at ASC"
            ).fetchall()
            connection.close()
            self.write_json(200, {"users": [self.serialize_user(user) for user in users]})
            return

        if path == "/api/pets":
            sql = """
                SELECT pets.*, users.full_name AS creator_name
                FROM pets
                JOIN users ON users.id = pets.creator_id
                WHERE 1 = 1
            """
            params: list[str] = []

            category = query.get("category", [""])[0]
            state = query.get("state", [""])[0]
            keyword = query.get("keyword", [""])[0]

            if category:
                sql += " AND (pets.manual_category = ? OR pets.recognized_category = ?)"
                params.extend([category, category])
            if state:
                sql += " AND (pets.status = ? OR pets.recognized_state = ?)"
                params.extend([state, state])
            if keyword:
                pattern = f"%{keyword}%"
                sql += " AND (pets.name LIKE ? OR pets.description LIKE ? OR pets.found_location LIKE ?)"
                params.extend([pattern, pattern, pattern])

            sql += " ORDER BY pets.created_at DESC"

            connection = get_db()
            pets = connection.execute(sql, params).fetchall()
            counts = {
                row["pet_id"]: row["total"]
                for row in connection.execute(
                    "SELECT pet_id, COUNT(*) AS total FROM comments GROUP BY pet_id"
                ).fetchall()
            }
            connection.close()

            payload = []
            for pet in pets:
                item = self.serialize_pet(pet)
                item["comment_count"] = counts.get(pet["id"], 0)
                payload.append(item)

            self.write_json(200, {"pets": payload})
            return

        if path.startswith("/api/pets/"):
            pet_id = path.replace("/api/pets/", "", 1)
            if not pet_id.isdigit():
                self.write_json(404, {"error": "宠物不存在。"})
                return

            connection = get_db()
            pet = connection.execute(
                """
                SELECT pets.*, users.full_name AS creator_name
                FROM pets
                JOIN users ON users.id = pets.creator_id
                WHERE pets.id = ?
                """,
                (pet_id,),
            ).fetchone()
            if not pet:
                connection.close()
                self.write_json(404, {"error": "宠物不存在。"})
                return

            comments = connection.execute(
                """
                SELECT comments.*, users.full_name
                FROM comments
                JOIN users ON users.id = comments.user_id
                WHERE comments.pet_id = ?
                ORDER BY comments.created_at DESC
                """,
                (pet_id,),
            ).fetchall()

            contacts = connection.execute(
                """
                SELECT contacts.*, users.full_name
                FROM contacts
                JOIN users ON users.id = contacts.user_id
                WHERE contacts.pet_id = ?
                ORDER BY contacts.created_at DESC
                """,
                (pet_id,),
            ).fetchall()
            connection.close()

            self.write_json(
                200,
                {
                    "pet": self.serialize_pet(pet),
                    "comments": [dict(comment) for comment in comments],
                    "contacts": [dict(contact) for contact in contacts],
                },
            )
            return

        self.write_json(404, {"error": "接口不存在。"})

    def handle_api_post(self, path: str) -> None:
        if path == "/api/register":
            payload = self.read_json()
            required = [field for field in ["username", "password", "full_name", "phone"] if not payload.get(field)]
            if required:
                self.write_json(400, {"error": f"缺少字段: {', '.join(required)}"})
                return

            connection = get_db()
            try:
                connection.execute(
                    """
                    INSERT INTO users (
                        username, password_hash, full_name, phone, email, address, id_card, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["username"].strip(),
                        hash_password(payload["password"]),
                        payload["full_name"].strip(),
                        payload["phone"].strip(),
                        payload.get("email", "").strip(),
                        payload.get("address", "").strip(),
                        payload.get("id_card", "").strip(),
                        now(),
                    ),
                )
                connection.commit()
            except Exception as error:
                connection.close()
                if is_mysql_integrity_error(error):
                    self.write_json(409, {"error": "用户名已存在。"})
                    return
                raise
            connection.close()
            self.write_json(201, {"message": "注册成功，请等待管理员审核。"})
            return

        if path == "/api/login":
            payload = self.read_json()
            connection = get_db()
            user = connection.execute(
                "SELECT * FROM users WHERE username = ?",
                (payload.get("username", ""),),
            ).fetchone()
            if not user or not verify_password(payload.get("password", ""), user["password_hash"]):
                connection.close()
                self.write_json(401, {"error": "用户名或密码错误。"})
                return
            if user["review_status"] != "approved":
                connection.close()
                self.write_json(403, {"error": f"当前审核状态为 {user['review_status']}，暂不可登录。"})
                return

            token = secrets.token_hex(24)
            connection.execute(
                "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                (token, user["id"], now()),
            )
            connection.commit()
            connection.close()
            self.write_json(200, {"token": token, "user": self.serialize_user(user)})
            return

        if path == "/api/logout":
            token = self.headers.get("Authorization", "").replace("Bearer ", "", 1).strip()
            if token:
                connection = get_db()
                connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
                connection.commit()
                connection.close()
            self.write_json(200, {"message": "已退出登录。"})
            return

        if path == "/api/pets/analyze":
            payload = self.read_json()
            image_data_url = payload.get("image_data_url", "")
            if not image_data_url:
                self.write_json(400, {"error": "请先上传图片。"})
                return
            try:
                _, raw_bytes = parse_data_url(image_data_url)
            except ValueError as error:
                self.write_json(400, {"error": str(error)})
                return

            yolo_result = detect_with_yolo(raw_bytes)
            recognition, category_key = build_instant_recognition(yolo_result)
            self.write_json(
                200,
                {
                    "category_key": category_key,
                    "recognition": recognition,
                    "processed_image_path": yolo_result.get("annotated_image_path"),
                },
            )
            return

        if path.startswith("/api/users/") and path.endswith("/review"):
            if not self.require_admin():
                return
            user_id = path.split("/")[3]
            payload = self.read_json()
            status = payload.get("status", "")
            if status not in {"approved", "rejected"}:
                self.write_json(400, {"error": "审核状态不合法。"})
                return

            connection = get_db()
            connection.execute(
                "UPDATE users SET review_status = ?, review_note = ? WHERE id = ?",
                (status, payload.get("review_note", "").strip(), user_id),
            )
            connection.commit()
            connection.close()
            self.write_json(200, {"message": "审核结果已保存。"})
            return

        if path == "/api/pets":
            user = self.current_user(required=True)
            if not user:
                return

            payload = self.read_json()
            required = [field for field in ["name", "status", "contact_phone"] if not payload.get(field)]
            if required:
                self.write_json(400, {"error": f"缺少字段: {', '.join(required)}"})
                return

            raw_image_path = None
            processed_image_path = None
            yolo_result = None
            try:
                image_data_url = payload.get("image_data_url", "")
                if image_data_url:
                    extension, raw_bytes = parse_data_url(image_data_url)
                    raw_image_path = save_binary_file(raw_bytes, "pet", extension)
                    yolo_result = detect_with_yolo(raw_bytes)
                    processed_image_path = yolo_result.get("annotated_image_path")
                if not processed_image_path:
                    processed_image_path = save_image(payload.get("processed_image_data_url", ""), "pet_processed")
            except ValueError as error:
                self.write_json(400, {"error": str(error)})
                return

            recognition = build_recognition(payload, yolo_result)
            connection = get_db()
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO pets (
                    creator_id, name, manual_category, recognized_category, breed, age_desc,
                    status, recognized_state, found_location, description, health_note, contact_phone,
                    adoption_status, recognition_hint, vision_report_json, recognition_json,
                    image_path, processed_image_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    payload["name"].strip(),
                    payload.get("manual_category", "").strip(),
                    recognition["recognized_category"],
                    payload.get("breed", "").strip(),
                    payload.get("age_desc", "").strip(),
                    payload["status"].strip(),
                    recognition["recognized_state"],
                    payload.get("found_location", "").strip(),
                    payload.get("description", "").strip(),
                    payload.get("health_note", "").strip(),
                    payload["contact_phone"].strip(),
                    payload.get("adoption_status", "").strip(),
                    payload.get("recognition_hint", "").strip(),
                    json.dumps(payload.get("vision_report", {}), ensure_ascii=False),
                    json.dumps(recognition, ensure_ascii=False),
                    raw_image_path,
                    processed_image_path,
                    now(),
                ),
            )
            pet_id = cursor.lastrowid
            connection.commit()
            connection.close()
            self.write_json(
                201,
                {
                    "message": "宠物档案已创建。",
                    "pet_id": pet_id,
                    "recognition": recognition,
                    "image_path": raw_image_path,
                    "processed_image_path": processed_image_path,
                },
            )
            return
            self.write_json(201, {"message": "宠物档案已创建。", "pet_id": pet_id, "recognition": recognition})
            return

        if path.startswith("/api/pets/") and path.endswith("/comments"):
            user = self.current_user(required=True)
            if not user:
                return
            pet_id = path.split("/")[3]
            payload = self.read_json()
            if not payload.get("content", "").strip():
                self.write_json(400, {"error": "评论不能为空。"})
                return

            connection = get_db()
            connection.execute(
                "INSERT INTO comments (pet_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
                (pet_id, user["id"], payload["content"].strip(), now()),
            )
            connection.commit()
            connection.close()
            self.write_json(201, {"message": "评论已发布。"})
            return

        if path.startswith("/api/pets/") and path.endswith("/contacts"):
            user = self.current_user(required=True)
            if not user:
                return
            pet_id = path.split("/")[3]
            payload = self.read_json()
            if payload.get("contact_type") not in {"rescue", "adoption", "claim"}:
                self.write_json(400, {"error": "联系类型不合法。"})
                return
            if not payload.get("phone", "").strip() or not payload.get("message", "").strip():
                self.write_json(400, {"error": "联系电话和留言不能为空。"})
                return

            connection = get_db()
            connection.execute(
                """
                INSERT INTO contacts (pet_id, user_id, contact_type, phone, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    pet_id,
                    user["id"],
                    payload["contact_type"],
                    payload["phone"].strip(),
                    payload["message"].strip(),
                    now(),
                ),
            )
            connection.commit()
            connection.close()
            self.write_json(201, {"message": "联系申请已提交。"})
            return

        self.write_json(404, {"error": "接口不存在。"})


def main() -> None:
    UPLOAD_DIR.mkdir(exist_ok=True)
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), ApiHandler)
    print(f"Pet Homecoming backend running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
