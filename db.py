\
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor

def get_conn():
    """
    Usa DATABASE_URL si existe (Heroku). Si no, usa variables locales.
    """
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url, sslmode=os.getenv("DB_SSLMODE", "require"))
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "encuesta_pic"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        sslmode=os.getenv("DB_SSLMODE", "prefer"),
    )

def fetchall(query, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params or ())
            return cur.fetchall()

def fetchone(query, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params or ())
            return cur.fetchone()

def execute(query, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            conn.commit()

def init_database():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS survey_versions (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS sections (
                id SERIAL PRIMARY KEY,
                version_id INTEGER NOT NULL REFERENCES survey_versions(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 1,
                is_active BOOLEAN NOT NULL DEFAULT TRUE
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS question_groups (
                id SERIAL PRIMARY KEY,
                version_id INTEGER NOT NULL REFERENCES survey_versions(id) ON DELETE CASCADE,
                section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 1,
                is_active BOOLEAN NOT NULL DEFAULT TRUE
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id SERIAL PRIMARY KEY,
                version_id INTEGER NOT NULL REFERENCES survey_versions(id) ON DELETE CASCADE,
                group_id INTEGER NOT NULL REFERENCES question_groups(id) ON DELETE CASCADE,
                code TEXT NULL,
                text TEXT NOT NULL,
                qtype TEXT NOT NULL,
                required BOOLEAN NOT NULL DEFAULT FALSE,
                sort_order INTEGER NOT NULL DEFAULT 1,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                config JSONB NOT NULL DEFAULT '{}'::jsonb
            );
            """)
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_questions_code ON questions(version_id, code) WHERE code IS NOT NULL;")
            cur.execute("""
            CREATE TABLE IF NOT EXISTS question_options (
                id SERIAL PRIMARY KEY,
                question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                value TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 1,
                meta JSONB NOT NULL DEFAULT '{}'::jsonb
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin','editor')),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS survey_responses (
                id BIGSERIAL PRIMARY KEY,
                version_id INTEGER NOT NULL REFERENCES survey_versions(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS survey_answers (
                id BIGSERIAL PRIMARY KEY,
                response_id BIGINT NOT NULL REFERENCES survey_responses(id) ON DELETE CASCADE,
                question_id INTEGER NOT NULL REFERENCES questions(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                value_text TEXT NULL,
                value_bool BOOLEAN NULL,
                value_number DOUBLE PRECISION NULL,
                value_json JSONB NULL
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_answers_response ON survey_answers(response_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_answers_question ON survey_answers(question_id);")
            conn.commit()

def get_active_version():
    v = fetchone("SELECT * FROM survey_versions WHERE is_active = TRUE ORDER BY id DESC LIMIT 1;")
    return v

def ensure_seed(seed_path: str):
    """
    Crea la versión activa + secciones/grupos/preguntas si la BD está vacía.
    """
    v = get_active_version()
    if v:
        # si ya hay secciones, no reseedear
        existing = fetchone("SELECT 1 AS ok FROM sections WHERE version_id=%s LIMIT 1;", (v["id"],))
        if existing:
            return v["id"]

    with open(seed_path, "r", encoding="utf-8") as f:
        seed = json.load(f)

    version_name = seed["survey"].get("version_name") or "v1"
    execute("UPDATE survey_versions SET is_active=FALSE WHERE is_active=TRUE;")
    execute("INSERT INTO survey_versions(name,is_active) VALUES(%s,TRUE);", (version_name,))
    v = get_active_version()
    version_id = v["id"]

    # insert sections/groups/questions/options
    for sec in seed["survey"]["sections"]:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO sections(version_id,name,sort_order,is_active) VALUES(%s,%s,%s,TRUE) RETURNING id;",
                    (version_id, sec["name"], sec.get("order", 1))
                )
                sec_id = cur.fetchone()["id"]
                for grp in sec.get("groups", []):
                    cur.execute(
                        "INSERT INTO question_groups(version_id,section_id,title,sort_order,is_active) VALUES(%s,%s,%s,%s,TRUE) RETURNING id;",
                        (version_id, sec_id, grp["title"], grp.get("order", 1))
                    )
                    grp_id = cur.fetchone()["id"]
                    for q in grp.get("questions", []):
                        cur.execute(
                            "INSERT INTO questions(version_id,group_id,code,text,qtype,required,sort_order,is_active,config) VALUES(%s,%s,%s,%s,%s,%s,%s,TRUE,%s) RETURNING id;",
                            (
                                version_id,
                                grp_id,
                                q.get("code"),
                                q["text"],
                                q["type"],
                                bool(q.get("required", False)),
                                q.get("order", 1),
                                json.dumps(q.get("config", {}))
                            )
                        )
                        q_id = cur.fetchone()["id"]
                        for idx,opt in enumerate(q.get("options", []), start=1):
                            cur.execute(
                                "INSERT INTO question_options(question_id,label,value,sort_order,meta) VALUES(%s,%s,%s,%s,%s);",
                                (q_id, opt["label"], opt.get("value", opt["label"]), opt.get("order", idx), json.dumps(opt.get("meta", {})))
                            )
                conn.commit()

    return version_id

def get_form(version_id: int):
    # sections
    sections = fetchall(
        "SELECT * FROM sections WHERE version_id=%s AND is_active=TRUE ORDER BY sort_order, id;",
        (version_id,)
    )
    section_ids = [s["id"] for s in sections]
    if not section_ids:
        return []

    groups = fetchall(
        "SELECT * FROM question_groups WHERE version_id=%s AND is_active=TRUE ORDER BY section_id, sort_order, id;",
        (version_id,)
    )
    group_ids = [g["id"] for g in groups]
    questions = []
    options = []
    if group_ids:
        questions = fetchall(
            "SELECT * FROM questions WHERE version_id=%s AND is_active=TRUE ORDER BY group_id, sort_order, id;",
            (version_id,)
        )
        q_ids = [q["id"] for q in questions]
        if q_ids:
            options = fetchall(
                "SELECT * FROM question_options WHERE question_id = ANY(%s) ORDER BY question_id, sort_order, id;",
                (q_ids,)
            )

    # build nested structure
    opts_by_q = {}
    for o in options:
        opts_by_q.setdefault(o["question_id"], []).append(o)

    qs_by_group = {}
    for q in questions:
        q = dict(q)
        q["options"] = opts_by_q.get(q["id"], [])
        qs_by_group.setdefault(q["group_id"], []).append(q)

    groups_by_section = {}
    for g in groups:
        g = dict(g)
        g["questions"] = qs_by_group.get(g["id"], [])
        groups_by_section.setdefault(g["section_id"], []).append(g)

    form = []
    for s in sections:
        s = dict(s)
        s["groups"] = groups_by_section.get(s["id"], [])
        form.append(s)
    return form

def create_response(version_id: int, metadata: dict) -> int:
    row = fetchone(
        "INSERT INTO survey_responses(version_id, metadata) VALUES(%s,%s) RETURNING id;",
        (version_id, json.dumps(metadata or {}))
    )
    return int(row["id"])

def save_answer(response_id: int, question: dict, value):
    qtype = question["qtype"]
    text_val = bool_val = num_val = json_val = None

    if value is None:
        pass
    elif qtype == "yes_no":
        bool_val = True if value == "Sí" else False if value == "No" else None
        text_val = value
    elif qtype in ("text",):
        text_val = str(value)
    elif qtype in ("number",):
        try:
            num_val = float(value)
        except Exception:
            text_val = str(value)
    elif qtype in ("single_choice",):
        text_val = str(value)
    elif qtype in ("multi_choice",):
        json_val = json.dumps(list(value))
    else:
        # fallback
        json_val = json.dumps(value)

    execute(
        "INSERT INTO survey_answers(response_id, question_id, value_text, value_bool, value_number, value_json) VALUES(%s,%s,%s,%s,%s,%s);",
        (response_id, question["id"], text_val, bool_val, num_val, json_val)
    )

def list_users():
    return fetchall("SELECT id, username, role, is_active, created_at FROM users ORDER BY id;")

def get_user_by_username(username: str):
    return fetchone("SELECT * FROM users WHERE lower(username)=lower(%s) LIMIT 1;", (username,))

def insert_user(username: str, password_hash: str, role: str):
    execute("INSERT INTO users(username, password_hash, role) VALUES(%s,%s,%s);", (username, password_hash, role))

def update_user_role(user_id: int, role: str, is_active: bool):
    execute("UPDATE users SET role=%s, is_active=%s WHERE id=%s;", (role, is_active, user_id))

def delete_user(user_id: int):
    execute("DELETE FROM users WHERE id=%s;", (user_id,))

def count_responses(version_id: int) -> int:
    row = fetchone("SELECT COUNT(*) AS n FROM survey_responses WHERE version_id=%s;", (version_id,))
    return int(row["n"])

def export_answers_wide(version_id: int):
    """
    Retorna DataFrame (1 fila por encuesta, 1 columna por pregunta).
    """
    rows = fetchall("""
        SELECT r.id AS response_id, r.created_at, r.metadata,
               s.name AS section_name, g.title AS group_title, q.id AS question_id, q.text AS question_text, q.qtype,
               a.value_text, a.value_bool, a.value_number, a.value_json
        FROM survey_responses r
        JOIN survey_answers a ON a.response_id = r.id
        JOIN questions q ON q.id = a.question_id
        JOIN question_groups g ON g.id = q.group_id
        JOIN sections s ON s.id = g.section_id
        WHERE r.version_id=%s
        ORDER BY r.id, q.id;
    """, (version_id,))
    import pandas as pd

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    def answer_to_str(row):
        if row["qtype"] == "yes_no":
            if row["value_bool"] is True:
                return "Sí"
            if row["value_bool"] is False:
                return "No"
        if row["value_text"] is not None:
            return row["value_text"]
        if row["value_number"] is not None:
            return row["value_number"]
        if row["value_json"] is not None:
            return json.loads(row["value_json"])
        return None

    df["answer"] = df.apply(answer_to_str, axis=1)
    df["col"] = df.apply(lambda r: f'{r["section_name"]} | {r["group_title"]} | {r["question_text"]}', axis=1)

    meta = df[["response_id","created_at","metadata"]].drop_duplicates("response_id").set_index("response_id")
    pivot = df.pivot_table(index="response_id", columns="col", values="answer", aggfunc="first")
    out = meta.join(pivot, how="left").reset_index()
    return out

# --- CRUD básicos (secciones/grupos/preguntas/opciones) ---

def upsert_section(version_id: int, section_id, name: str, sort_order: int, is_active: bool):
    if section_id:
        execute("UPDATE sections SET name=%s, sort_order=%s, is_active=%s WHERE id=%s AND version_id=%s;",
                (name, sort_order, is_active, section_id, version_id))
    else:
        execute("INSERT INTO sections(version_id,name,sort_order,is_active) VALUES(%s,%s,%s,%s);",
                (version_id, name, sort_order, is_active))

def upsert_group(version_id: int, group_id, section_id: int, title: str, sort_order: int, is_active: bool):
    if group_id:
        execute("UPDATE question_groups SET section_id=%s, title=%s, sort_order=%s, is_active=%s WHERE id=%s AND version_id=%s;",
                (section_id, title, sort_order, is_active, group_id, version_id))
    else:
        execute("INSERT INTO question_groups(version_id,section_id,title,sort_order,is_active) VALUES(%s,%s,%s,%s,%s);",
                (version_id, section_id, title, sort_order, is_active))

def upsert_question(version_id: int, question_id, group_id: int, code, text: str, qtype: str, required: bool, sort_order: int, is_active: bool, config: dict):
    if question_id:
        execute("""UPDATE questions
                  SET group_id=%s, code=%s, text=%s, qtype=%s, required=%s, sort_order=%s, is_active=%s, config=%s
                  WHERE id=%s AND version_id=%s;""",
                (group_id, code or None, text, qtype, required, sort_order, is_active, json.dumps(config or {}), question_id, version_id))
    else:
        execute("""INSERT INTO questions(version_id,group_id,code,text,qtype,required,sort_order,is_active,config)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);""",
                (version_id, group_id, code or None, text, qtype, required, sort_order, is_active, json.dumps(config or {})))

def delete_options_for_question(question_id: int):
    execute("DELETE FROM question_options WHERE question_id=%s;", (question_id,))

def insert_option(question_id: int, label: str, value: str, sort_order: int, meta: dict):
    execute("INSERT INTO question_options(question_id,label,value,sort_order,meta) VALUES(%s,%s,%s,%s,%s);",
            (question_id, label, value, sort_order, json.dumps(meta or {})))
