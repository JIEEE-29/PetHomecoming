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
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "pet_homecoming.db"


def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    salt, digest = stored.split("$", 1)
    return hash_password(password, salt) == f"{salt}${digest}"


def save_image(data_url, prefix):
    if not data_url:
        return None
    header, encoded = data_url.split(",", 1)
    mime_type = header.split(";")[0].split(":")[1]
    ext = mimetypes.guess_extension(mime_type) or ".jpg"
    name = f"{prefix}_{secrets.token_hex(8)}{ext}"
    path = UPLOAD_DIR / name
    path.write_bytes(base64.b64decode(encoded))
    return f"/uploads/{name}"


def classify_type(name, desc, hint, manual):
    text = " ".join(filter(None, [name, desc, hint, manual])).lower()
    if any(word in text for word in ["狗", "犬", "dog", "金毛", "拉布拉多", "泰迪"]):
        return "犬类", 0.91
    if any(word in text for word in ["猫", "cat", "英短", "布偶", "橘猫"]):
        return "猫类", 0.91
    if any(word in text for word in ["鸟", "bird", "鹦鹉"]):
        return "鸟类", 0.82
    if any(word in text for word in ["兔", "仓鼠", "hamster", "rabbit"]):
        return "小型宠物", 0.77
    return (manual or "待人工确认"), 0.45 if not manual else 0.72


def classify_state(desc, health, status, vision):
    text = " ".join(filter(None, [desc, health, status])).lower()
    notes = []
    score = 0.58
    if any(word in text for word in ["受伤", "流血", "骨折", "生病", "伤口", "虚弱", "呕吐"]):
        notes.append("文本包含受伤或生病信息，建议优先救治。")
        return "需救治", notes, 0.9
    if any(word in text for word in ["走失", "丢失", "拾获", "流浪", "found"]):
        notes.append("更接近走失或拾获场景。")
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
            notes.append("图像偏暗，建议补拍。")
            score -= 0.06
        if contrast < 20:
            notes.append("图像对比度较低，主体可能不够清晰。")
            score -= 0.04
    return state, notes, max(0.35, min(score, 0.95))


def recognition(payload):
    category, category_conf = classify_type(
        payload.get("name", ""),
        payload.get("description", ""),
        payload.get("recognition_hint", ""),
        payload.get("manual_category", ""),
    )
    state, notes, state_conf = classify_state(
        payload.get("description", ""),
        payload.get("health_note", ""),
        payload.get("status", ""),
        payload.get("vision_report"),
    )
    recs = [
        "补充正面和侧面照片，便于人工复核。",
        "补充发现地点、时间和明显特征。",
    ]
    if state == "需救治":
        recs.insert(0, "建议先联系救治人员并记录伤情。")
    if state == "待领养":
        recs.insert(0, "建议补充疫苗、绝育和性格信息。")
    return {
        "recognized_category": category,
        "recognized_state": state,
        "category_confidence": round(category_conf, 2),
        "state_confidence": round(state_conf, 2),
        "notes": notes,
        "recommendations": recs,
    }


def init_db():
    conn = db()
    conn.executescript(
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
            contact_phone TEXT,
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
    exists = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    if not exists:
        conn.execute(
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
    conn.commit()
    conn.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        return

    def do_OPTIONS(self):
        self.send_response(204)
        self.headers_common("application/json; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.api_get(parsed)
        else:
            self.serve_file(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.api_post(parsed.path)
        else:
            self.send_error(404)

    def headers_common(self, content_type):
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def json(self, code, payload):
        self.send_response(code)
        self.headers_common("application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode())

    def body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode() or "{}")

    def current_user(self, required=False):
        token = self.headers.get("Authorization", "").replace("Bearer ", "", 1).strip()
        if not token:
            if required:
                self.json(401, {"error": "请先登录。"})
            return None
        conn = db()
        user = conn.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        ).fetchone()
        conn.close()
        if not user and required:
            self.json(401, {"error": "登录状态已失效。"})
        return user

    def require_admin(self):
        user = self.current_user(True)
        if not user:
            return None
        if user["role"] != "admin":
            self.json(403, {"error": "需要管理员权限。"})
            return None
        return user

    def serve_file(self, route):
        routes = {
            "/": STATIC_DIR / "index.html",
            "/auth": STATIC_DIR / "auth.html",
            "/publish": STATIC_DIR / "publish.html",
            "/pets": STATIC_DIR / "pets.html",
            "/admin": STATIC_DIR / "admin.html",
        }
        if route in routes:
            path = routes[route]
        elif route.startswith("/static/") or route.startswith("/uploads/"):
            path = BASE_DIR / route.lstrip("/")
        else:
            path = STATIC_DIR / "index.html"
        if not path.exists():
            self.send_error(404)
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.headers_common(mime)
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def serialize_user(self, row):
        return {key: row[key] for key in row.keys() if key != "password_hash"}

    def serialize_pet(self, row):
        data = dict(row)
        data["recognition"] = json.loads(row["recognition_json"] or "{}")
        data["vision_report"] = json.loads(row["vision_report_json"] or "{}")
        data.pop("recognition_json", None)
        data.pop("vision_report_json", None)
        return data

    def api_get(self, parsed):
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path == "/api/health":
            self.json(200, {"ok": True, "time": now()})
            return
        if path == "/api/me":
            user = self.current_user(True)
            if user:
                self.json(200, {"user": self.serialize_user(user)})
            return
        if path == "/api/users/pending":
            if not self.require_admin():
                return
            conn = db()
            users = conn.execute(
                "SELECT * FROM users WHERE role='user' AND review_status='pending' ORDER BY created_at ASC"
            ).fetchall()
            conn.close()
            self.json(200, {"users": [self.serialize_user(x) for x in users]})
            return
        if path == "/api/pets":
            sql = """
                SELECT pets.*, users.full_name AS creator_name
                FROM pets JOIN users ON users.id = pets.creator_id
                WHERE 1=1
            """
            params = []
            if qs.get("category", [""])[0]:
                sql += " AND (manual_category=? OR recognized_category=?)"
                params += [qs["category"][0], qs["category"][0]]
            if qs.get("state", [""])[0]:
                sql += " AND (status=? OR recognized_state=?)"
                params += [qs["state"][0], qs["state"][0]]
            if qs.get("keyword", [""])[0]:
                key = f"%{qs['keyword'][0]}%"
                sql += " AND (name LIKE ? OR description LIKE ? OR found_location LIKE ?)"
                params += [key, key, key]
            sql += " ORDER BY pets.created_at DESC"
            conn = db()
            pets = conn.execute(sql, params).fetchall()
            counts = {x["pet_id"]: x["c"] for x in conn.execute("SELECT pet_id, COUNT(*) c FROM comments GROUP BY pet_id").fetchall()}
            conn.close()
            data = []
            for pet in pets:
                item = self.serialize_pet(pet)
                item["comment_count"] = counts.get(pet["id"], 0)
                data.append(item)
            self.json(200, {"pets": data})
            return
        if path.startswith("/api/pets/"):
            pet_id = path.replace("/api/pets/", "", 1)
            if not pet_id.isdigit():
                self.json(404, {"error": "宠物不存在。"})
                return
            conn = db()
            pet = conn.execute(
                """
                SELECT pets.*, users.full_name AS creator_name
                FROM pets JOIN users ON users.id = pets.creator_id
                WHERE pets.id = ?
                """,
                (pet_id,),
            ).fetchone()
            if not pet:
                conn.close()
                self.json(404, {"error": "宠物不存在。"})
                return
            comments = conn.execute(
                """
                SELECT comments.*, users.full_name
                FROM comments JOIN users ON users.id = comments.user_id
                WHERE pet_id = ? ORDER BY comments.created_at DESC
                """,
                (pet_id,),
            ).fetchall()
            contacts = conn.execute(
                """
                SELECT contacts.*, users.full_name
                FROM contacts JOIN users ON users.id = contacts.user_id
                WHERE pet_id = ? ORDER BY contacts.created_at DESC
                """,
                (pet_id,),
            ).fetchall()
            conn.close()
            self.json(
                200,
                {
                    "pet": self.serialize_pet(pet),
                    "comments": [dict(x) for x in comments],
                    "contacts": [dict(x) for x in contacts],
                },
            )
            return
        self.json(404, {"error": "接口不存在。"})

    def api_post(self, path):
        if path == "/api/register":
            payload = self.body()
            required = [x for x in ["username", "password", "full_name", "phone"] if not payload.get(x)]
            if required:
                self.json(400, {"error": f"缺少字段: {', '.join(required)}"})
                return
            conn = db()
            try:
                conn.execute(
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
                conn.commit()
            except sqlite3.IntegrityError:
                conn.close()
                self.json(409, {"error": "用户名已存在。"})
                return
            conn.close()
            self.json(201, {"message": "注册成功，请等待管理员审核。"})
            return
        if path == "/api/login":
            payload = self.body()
            conn = db()
            user = conn.execute("SELECT * FROM users WHERE username=?", (payload.get("username", ""),)).fetchone()
            if not user or not verify_password(payload.get("password", ""), user["password_hash"]):
                conn.close()
                self.json(401, {"error": "用户名或密码错误。"})
                return
            if user["review_status"] != "approved":
                conn.close()
                self.json(403, {"error": f"当前审核状态为 {user['review_status']}，暂不可登录。"})
                return
            token = secrets.token_hex(24)
            conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, user["id"], now()))
            conn.commit()
            conn.close()
            self.json(200, {"token": token, "user": self.serialize_user(user)})
            return
        if path.startswith("/api/users/") and path.endswith("/review"):
            if not self.require_admin():
                return
            user_id = path.split("/")[3]
            payload = self.body()
            status = payload.get("status", "")
            if status not in {"approved", "rejected"}:
                self.json(400, {"error": "审核状态不合法。"})
                return
            conn = db()
            conn.execute(
                "UPDATE users SET review_status=?, review_note=? WHERE id=?",
                (status, payload.get("review_note", "").strip(), user_id),
            )
            conn.commit()
            conn.close()
            self.json(200, {"message": "审核结果已保存。"})
            return
        if path == "/api/pets":
            user = self.current_user(True)
            if not user:
                return
            payload = self.body()
            required = [x for x in ["name", "status", "contact_phone"] if not payload.get(x)]
            if required:
                self.json(400, {"error": f"缺少字段: {', '.join(required)}"})
                return
            recog = recognition(payload)
            conn = db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO pets (
                    creator_id, name, manual_category, recognized_category, breed, age_desc,
                    status, recognized_state, found_location, description, health_note,
                    contact_phone, adoption_status, recognition_hint, vision_report_json,
                    recognition_json, image_path, processed_image_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    payload["name"].strip(),
                    payload.get("manual_category", "").strip(),
                    recog["recognized_category"],
                    payload.get("breed", "").strip(),
                    payload.get("age_desc", "").strip(),
                    payload["status"].strip(),
                    recog["recognized_state"],
                    payload.get("found_location", "").strip(),
                    payload.get("description", "").strip(),
                    payload.get("health_note", "").strip(),
                    payload["contact_phone"].strip(),
                    payload.get("adoption_status", "").strip(),
                    payload.get("recognition_hint", "").strip(),
                    json.dumps(payload.get("vision_report", {}), ensure_ascii=False),
                    json.dumps(recog, ensure_ascii=False),
                    save_image(payload.get("image_data_url", ""), "pet"),
                    save_image(payload.get("processed_image_data_url", ""), "pet_processed"),
                    now(),
                ),
            )
            pet_id = cur.lastrowid
            conn.commit()
            conn.close()
            self.json(201, {"message": "宠物档案已创建。", "pet_id": pet_id, "recognition": recog})
            return
        if path.startswith("/api/pets/") and path.endswith("/comments"):
            user = self.current_user(True)
            if not user:
                return
            pet_id = path.split("/")[3]
            payload = self.body()
            if not payload.get("content", "").strip():
                self.json(400, {"error": "评论不能为空。"})
                return
            conn = db()
            conn.execute(
                "INSERT INTO comments (pet_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
                (pet_id, user["id"], payload["content"].strip(), now()),
            )
            conn.commit()
            conn.close()
            self.json(201, {"message": "评论已发布。"})
            return
        if path.startswith("/api/pets/") and path.endswith("/contacts"):
            user = self.current_user(True)
            if not user:
                return
            pet_id = path.split("/")[3]
            payload = self.body()
            if payload.get("contact_type") not in {"rescue", "adoption", "claim"}:
                self.json(400, {"error": "联系类型不合法。"})
                return
            if not payload.get("phone", "").strip() or not payload.get("message", "").strip():
                self.json(400, {"error": "联系电话和留言不能为空。"})
                return
            conn = db()
            conn.execute(
                """
                INSERT INTO contacts (pet_id, user_id, contact_type, phone, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pet_id, user["id"], payload["contact_type"], payload["phone"].strip(), payload["message"].strip(), now()),
            )
            conn.commit()
            conn.close()
            self.json(201, {"message": "联系申请已提交。"})
            return
        self.json(404, {"error": "接口不存在。"})


def main():
    STATIC_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Pet Homecoming server running at http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
