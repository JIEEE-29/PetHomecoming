import base64
import json
import mimetypes
import secrets
import sqlite3
from datetime import datetime
from hashlib import pbkdf2_hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "pet_homecoming.db"
HOST = "127.0.0.1"
PORT = 8000


def now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def get_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


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
    file_name = f"{prefix}_{secrets.token_hex(8)}{extension}"
    target = UPLOAD_DIR / file_name
    target.write_bytes(raw)
    return f"/uploads/{file_name}"


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


def build_recognition(payload: dict) -> dict:
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
    return {
        "recognized_category": category,
        "recognized_state": state,
        "category_confidence": round(category_confidence, 2),
        "state_confidence": round(state_confidence, 2),
        "notes": notes,
        "recommendations": recommendations,
    }


def init_db() -> None:
    connection = get_db()
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            address TEXT,
            id_card TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            review_status TEXT NOT NULL DEFAULT 'pending',
            review_note TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            manual_category TEXT,
            recognized_category TEXT,
            breed TEXT,
            age_desc TEXT,
            status TEXT NOT NULL,
            recognized_state TEXT,
            found_location TEXT,
            description TEXT,
            health_note TEXT,
            contact_phone TEXT NOT NULL,
            adoption_status TEXT,
            recognition_hint TEXT,
            vision_report_json TEXT,
            recognition_json TEXT,
            image_path TEXT,
            processed_image_path TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            contact_type TEXT NOT NULL,
            phone TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL
        );
        """
    )

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
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

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

    def current_user(self, required: bool = False) -> sqlite3.Row | None:
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

    def require_admin(self) -> sqlite3.Row | None:
        user = self.current_user(required=True)
        if not user:
            return None
        if user["role"] != "admin":
            self.write_json(403, {"error": "需要管理员权限。"})
            return None
        return user

    def serialize_user(self, row: sqlite3.Row) -> dict:
        return {key: row[key] for key in row.keys() if key != "password_hash"}

    def serialize_pet(self, row: sqlite3.Row) -> dict:
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
            except sqlite3.IntegrityError:
                connection.close()
                self.write_json(409, {"error": "用户名已存在。"})
                return
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

            recognition = build_recognition(payload)
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
                    save_image(payload.get("image_data_url", ""), "pet"),
                    save_image(payload.get("processed_image_data_url", ""), "pet_processed"),
                    now(),
                ),
            )
            pet_id = cursor.lastrowid
            connection.commit()
            connection.close()
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
