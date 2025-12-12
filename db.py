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
                -- label: lo que ve el encuestado (nombre/enunciado). Si es NULL, usar `text`.
                label TEXT NULL,
                -- text: descripción larga / respaldo (también se usa como fallback de label)
                text TEXT NOT NULL,
                -- ayuda opcional debajo del enunciado
                help_text TEXT NULL,
                qtype TEXT NOT NULL,
                required BOOLEAN NOT NULL DEFAULT FALSE,
                sort_order INTEGER NOT NULL DEFAULT 1,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                config JSONB NOT NULL DEFAULT '{}'::jsonb
            );
            """)
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_questions_code ON questions(version_id, code) WHERE code IS NOT NULL;")

            # Migración ligera (para BD existentes): agregar columnas si faltan.
            cur.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS label TEXT NULL;")
            cur.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS help_text TEXT NULL;")
            # Rellenar label cuando esté vacío (para que siempre haya un enunciado editable).
            cur.execute("UPDATE questions SET label = text WHERE label IS NULL;")
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
                            """
                            INSERT INTO questions(
                                version_id, group_id, code,
                                label, text, help_text,
                                qtype, required, sort_order, is_active, config
                            )
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s)
                            RETURNING id;
                            """,
                            (
                                version_id,
                                grp_id,
                                q.get("code"),
                                (q.get("label") or q.get("text")),
                                q["text"],
                                (q.get("help_text") or q.get("help") or q.get("description")),
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




def ensure_initial_identity_questions(version_id: int):
    """Asegura que existan las preguntas de identificación en 'PREGUNTAS INICIALES'.
    Se usa para BD ya sembradas (no depende del seed).
    """
    import unicodedata, re as _re

    def _norm(x: str) -> str:
        x = unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode("ascii")
        x = x.lower()
        x = _re.sub(r"[^a-z0-9]+", "", x)
        return x

    # Buscar sección "PREGUNTAS INICIALES"
    sections = fetchall("SELECT id, name FROM sections WHERE version_id=%s;", (version_id,))
    sec_id = None
    for s in sections:
        if _norm(s["name"]) == _norm("PREGUNTAS INICIALES"):
            sec_id = s["id"]
            break
    if not sec_id:
        return

    # Definición de grupo + preguntas
    group_title = "Identificación"
    questions_def = [
        {"code": "full_name", "label": "NOMBRE COMPLETO", "text": "NOMBRE COMPLETO", "qtype": "text", "sort_order": 1},
        {
            "code": "doc_type",
            "label": "TIPO DE DOCUMENTO",
            "text": "TIPO DE DOCUMENTO",
            "qtype": "single_choice",
            "sort_order": 2,
            "options": [
                ("RC - REGISTRO CIVIL", "RC", 1),
                ("TI - TARJETA DE IDENTIDAD", "TI", 2),
                ("CC - CÉDULA DE CIUDADANÍA", "CC", 3),
                ("CE - CÉDULA DE EXTRANJERÍA", "CE", 4),
                ("PEP - PERMISO ESPECIAL DE PERMANENCIA", "PEP", 5),
                ("DNI - DOCUMENTO NACIONAL DE IDENTIDAD", "DNI", 6),
                ("PA - PASAPORTE", "PA", 7),
            ],
        },
        {"code": "doc_number", "label": "NÚMERO DE DOCUMENTO", "text": "NÚMERO DE DOCUMENTO", "qtype": "text", "sort_order": 3},
        {"code": "phone", "label": "NÚMERO DE CELULAR", "text": "NÚMERO DE CELULAR", "qtype": "text", "sort_order": 4},
        {"code": "email", "label": "CORREO ELECTRÓNICO", "text": "CORREO ELECTRÓNICO", "qtype": "text", "sort_order": 5},
        {"code": "role", "label": "¿CUÁL ES SU CARGO O ROL?", "text": "¿CUÁL ES SU CARGO O ROL?", "qtype": "text", "sort_order": 6},
    ]

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Asegurar grupo Identificación en esa sección
            cur.execute(
                """
                SELECT id, sort_order FROM question_groups
                WHERE version_id=%s AND section_id=%s AND lower(title)=lower(%s)
                LIMIT 1;
                """,
                (version_id, sec_id, group_title),
            )
            g = cur.fetchone()
            if g:
                grp_id = g["id"]
                cur.execute(
                    "UPDATE question_groups SET sort_order=%s, is_active=TRUE WHERE id=%s;",
                    (2, grp_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO question_groups(version_id, section_id, title, sort_order, is_active)
                    VALUES(%s,%s,%s,%s,TRUE) RETURNING id;
                    """,
                    (version_id, sec_id, group_title, 2),
                )
                grp_id = cur.fetchone()["id"]

            # Si existe el grupo "Conocimiento y participación PIC" con sort_order=2, moverlo a 3
            cur.execute(
                """
                UPDATE question_groups
                SET sort_order=3
                WHERE version_id=%s AND section_id=%s AND lower(title)=lower(%s) AND sort_order=2;
                """,
                (version_id, sec_id, "Conocimiento y participación PIC"),
            )

            # Upsert preguntas por code
            for qd in questions_def:
                cur.execute(
                    "SELECT id FROM questions WHERE version_id=%s AND code=%s LIMIT 1;",
                    (version_id, qd["code"]),
                )
                existing = cur.fetchone()
                if existing:
                    qid = existing["id"]
                    cur.execute(
                        """
                        UPDATE questions
                        SET group_id=%s, label=%s, text=%s, qtype=%s, required=FALSE,
                            sort_order=%s, is_active=TRUE
                        WHERE id=%s AND version_id=%s;
                        """,
                        (grp_id, qd["label"], qd["text"], qd["qtype"], qd["sort_order"], qid, version_id),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO questions(version_id, group_id, code, label, text, qtype, required, sort_order, is_active, config)
                        VALUES(%s,%s,%s,%s,%s,%s,FALSE,%s,TRUE,'{}'::jsonb)
                        RETURNING id;
                        """,
                        (version_id, grp_id, qd["code"], qd["label"], qd["text"], qd["qtype"], qd["sort_order"]),
                    )
                    qid = cur.fetchone()["id"]

                # Opciones para tipo documento
                if qd.get("options"):
                    cur.execute("DELETE FROM question_options WHERE question_id=%s;", (qid,))
                    for (lbl, val, order) in qd["options"]:
                        cur.execute(
                            """
                            INSERT INTO question_options(question_id, label, value, sort_order, meta)
                            VALUES(%s,%s,%s,%s,'{}'::jsonb);
                            """,
                            (qid, lbl, val, order),
                        )

        conn.commit()


def ensure_core_question_codes(version_id: int):
    """Para BD ya sembradas: asegura que preguntas clave tengan los `code` esperados.

    Esto arregla exportación (Provincia/Municipio/Identificación) cuando la BD fue sembrada
    con versiones anteriores donde esas preguntas existían pero sin `code`.
    """
    import unicodedata as _ud
    import re as _re

    def _norm(x: str) -> str:
        x = x or ""
        x = _ud.normalize("NFKD", x).encode("ascii", "ignore").decode("ascii")
        x = x.lower().strip()
        x = _re.sub(r"[^a-z0-9]+", "", x)
        return x

    # Targets by *meaning* (codes) rather than by exact text.
    # Text matching is used as a first pass, but we also have a robust fallback
    # based on section/group/order to survive manual edits of the question text.
    targets = [
        ("province", "Provincia a la cual pertenece"),
        ("municipality", "Municipio al que pertenece"),
        ("full_name", "NOMBRE COMPLETO"),
        ("doc_type", "TIPO DE DOCUMENTO"),
        ("doc_number", "NÚMERO DE DOCUMENTO"),
        ("phone", "NÚMERO DE CELULAR"),
        ("email", "CORREO ELECTRÓNICO"),
        ("role", "¿CUÁL ES SU CARGO O ROL?"),
    ]

    rows = fetchall(
        """
        SELECT q.id, q.group_id, q.sort_order AS q_sort, q.code, q.label, q.text, q.config,
               s.name AS section_name,
               g.id AS grp_id, g.title AS group_title, g.sort_order AS grp_sort
        FROM questions q
        JOIN question_groups g ON g.id=q.group_id
        JOIN sections s ON s.id=g.section_id
        WHERE q.version_id=%s
        ORDER BY q.id;
        """,
        (version_id,),
    )

    by_id = {r["id"]: r for r in rows}

    # helper: find candidate by normalized label/text (prefer in PREGUNTAS INICIALES)
    def find_candidate(target_text: str):
        nt = _norm(target_text)
        candidates = []
        for r in rows:
            if _norm(r.get("label") or "") == nt or _norm(r.get("text") or "") == nt:
                # prefer initial section
                score = 0
                if _norm(r.get("section_name") or "") == _norm("PREGUNTAS INICIALES"):
                    score += 10
                if r.get("code") is None:
                    score += 5
                candidates.append((score, r["id"]))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

    def _find_by_group_order(section_name: str, group_title_contains: str, pos_1based: int):
        """Fallback selector: pick the N-th question inside a given section/group."""
        sn = _norm(section_name)
        gn = _norm(group_title_contains)
        bucket = []
        for r in rows:
            if _norm(r.get("section_name") or "") != sn:
                continue
            if gn not in _norm(r.get("group_title") or ""):
                continue
            bucket.append(r)
        if not bucket:
            return None
        # Deterministic order: group order, question order, then id.
        bucket.sort(key=lambda x: (int(x.get("grp_sort") or 0), int(x.get("q_sort") or 0), int(x["id"])))
        idx = max(0, pos_1based - 1)
        if idx >= len(bucket):
            return None
        return int(bucket[idx]["id"])

    # If a code exists but is attached to a different question than our best candidate,
    # we *move* the code to the best candidate (prefer PREGUNTAS INICIALES).
    # This fixes cases where older versions created duplicates and the code ended up on
    # the wrong record (export then shows None for Provincia/Municipio/etc.).
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for code, ttext in targets:
                cand_id = find_candidate(ttext)
                # Robust fallback if the question text was edited.
                if cand_id is None:
                    if code in ("province", "municipality"):
                        # Ubicación group in PREGUNTAS INICIALES: first=provincia, second=municipio
                        cand_id = _find_by_group_order("PREGUNTAS INICIALES", "Ubic", 1 if code == "province" else 2)
                    elif code in ("full_name", "doc_type", "doc_number", "phone", "email", "role"):
                        # Identificación group: fixed order
                        order_map = {
                            "full_name": 1,
                            "doc_type": 2,
                            "doc_number": 3,
                            "phone": 4,
                            "email": 5,
                            "role": 6,
                        }
                        cand_id = _find_by_group_order("PREGUNTAS INICIALES", "Ident", order_map.get(code, 1))
                if cand_id is None:
                    continue

                cur.execute(
                    "SELECT id FROM questions WHERE version_id=%s AND code=%s LIMIT 1;",
                    (version_id, code),
                )
                existing = cur.fetchone()

                if existing and int(existing["id"]) == int(cand_id):
                    continue

                # Free the code if it is currently attached elsewhere
                if existing and int(existing["id"]) != int(cand_id):
                    cur.execute(
                        "UPDATE questions SET code=NULL WHERE id=%s AND version_id=%s;",
                        (existing["id"], version_id),
                    )

                # Attach the code to the best candidate
                cur.execute(
                    "UPDATE questions SET code=%s WHERE id=%s AND version_id=%s;",
                    (code, cand_id, version_id),
                )

        conn.commit()

    # Optional: deactivate obvious duplicates for core fields inside PREGUNTAS INICIALES
    # (keeps the coded one active). This reduces confusion in UI and ensures answers
    # land on the right question.
    try:
        sec_norm = _norm("PREGUNTAS INICIALES")
        init_ids = [r for r in rows if _norm(r.get("section_name") or "") == sec_norm]
        for code, ttext in targets:
            # Find the coded question id
            coded = fetchone(
                "SELECT id FROM questions WHERE version_id=%s AND code=%s LIMIT 1;",
                (version_id, code),
            )
            if not coded:
                continue
            coded_id = int(coded["id"])
            nt = _norm(ttext)
            dup_ids = []
            for r in init_ids:
                if int(r["id"]) == coded_id:
                    continue
                if _norm(r.get("label") or "") == nt or _norm(r.get("text") or "") == nt:
                    dup_ids.append(int(r["id"]))
            if dup_ids:
                execute(
                    "UPDATE questions SET is_active=FALSE WHERE version_id=%s AND id = ANY(%s);",
                    (version_id, dup_ids),
                )
    except Exception:
        pass

    # Ensure municipality has dependency config
    mun = fetchone("SELECT id, config FROM questions WHERE version_id=%s AND code='municipality' LIMIT 1;", (version_id,))
    if mun:
        cfg = mun.get("config") or {}
        # cfg may come as dict already (jsonb) with RealDictCursor
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        changed = False
        if cfg.get("depends_on") != "province":
            cfg["depends_on"] = "province"
            changed = True
        if cfg.get("filter_option_meta_key") != "province":
            cfg["filter_option_meta_key"] = "province"
            changed = True
        if changed:
            execute("UPDATE questions SET config=%s WHERE id=%s AND version_id=%s;", (json.dumps(cfg), mun["id"], version_id))
def set_required_for_sections(version_id: int, section_names: list[str], required: bool = False):
    """Marca como obligatorias (o no) todas las preguntas de las secciones indicadas.

    Esta función hace match de nombres de sección de forma tolerante (ignora tildes,
    guiones y espacios) para evitar problemas de escritura como '-' vs '–'.
    """
    if not section_names:
        return

    # Traer secciones reales del version_id
    rows = fetchall(
        """
        SELECT id, name
        FROM sections
        WHERE version_id = %s
        """,
        (version_id,),
    )

    def _norm(x: str) -> str:
        import unicodedata, re as _re
        x = unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode("ascii")
        x = x.lower()
        x = _re.sub(r"[^a-z0-9]+", "", x)
        return x

    wanted = {_norm(n) for n in section_names}
    section_ids = [r["id"] for r in rows if _norm(r["name"]) in wanted]

    if not section_ids:
        return

    execute(
        """
        UPDATE questions q
        SET required = %s
        FROM question_groups g
        WHERE q.group_id = g.id
          AND q.version_id = %s
          AND g.section_id = ANY(%s);
        """,
        (required, version_id, section_ids),
    )

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
    """Retorna DataFrame (1 fila por encuesta, 1 columna por pregunta).

    Importante:
    - Siempre incluye las columnas clave (Provincia/Municipio/Identificación) aunque estén vacías.
    - Siempre incluye todas las preguntas activas de la versión (aunque todas estén en blanco),
      para que el Excel tenga estructura estable.
    """
    import pandas as pd

    # 1) Traer todas las respuestas (pueden tener valores NULL)
    rows = fetchall("""
        SELECT r.id AS response_id, r.created_at, r.metadata,
               s.name AS section_name, g.title AS group_title,
               q.id AS question_id, q.code AS code, COALESCE(q.label, q.text) AS question_text, q.qtype,
               a.value_text, a.value_bool, a.value_number, a.value_json
        FROM survey_responses r
        JOIN survey_answers a ON a.response_id = r.id
        JOIN questions q ON q.id = a.question_id
        JOIN question_groups g ON g.id = q.group_id
        JOIN sections s ON s.id = g.section_id
        WHERE r.version_id=%s
        ORDER BY r.id, q.id;
    """, (version_id,))

    # Si no hay ninguna encuesta, retorna vacío
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
            try:
                return json.loads(row["value_json"])
            except Exception:
                return row["value_json"]
        return None

    df["answer"] = df.apply(answer_to_str, axis=1)
    df["col"] = df.apply(lambda r: f'{r["section_name"]} | {r["group_title"]} | {r["question_text"]}', axis=1)

    # 2) Metadata por encuesta
    meta = df[["response_id", "created_at", "metadata"]].drop_duplicates("response_id").set_index("response_id")

    # 3) Columnas explícitas para ubicación / identificación (más fácil para análisis)
    key_map = {
        "province": "Provincia",
        "municipality": "Municipio",
        "full_name": "Nombre completo",
        "doc_type": "Tipo de documento",
        "doc_number": "Número de documento",
        "phone": "Número de celular",
        "email": "Correo electrónico",
        "role": "Cargo o rol",
    }

    # Creamos el pivot por código, pero garantizando columnas aunque estén vacías
    code_cols = list(key_map.keys())
    code_pivot = pd.DataFrame(index=meta.index, columns=code_cols)
    df_code = df[df["code"].isin(code_cols)].copy()
    if not df_code.empty:
        tmp = df_code.pivot_table(index="response_id", columns="code", values="answer", aggfunc="first")
        code_pivot.loc[tmp.index, tmp.columns] = tmp
    code_pivot = code_pivot.rename(columns=key_map)

    # Fallback: si por alguna razón los `code` no quedaron asignados en la BD (o el encuestador
    # respondió una pregunta duplicada sin code), intentamos completar estas columnas buscando
    # por texto y por ubicación en la encuesta.
    def _norm_txt(x: str) -> str:
        x = (x or "").lower().strip()
        import re as _re, unicodedata as _ud
        x = _ud.normalize("NFKD", x).encode("ascii", "ignore").decode("ascii")
        x = _re.sub(r"[^a-z0-9]+", "", x)
        return x

    df_fallback = df.copy()
    df_fallback["sec_n"] = df_fallback["section_name"].map(_norm_txt)
    df_fallback["grp_n"] = df_fallback["group_title"].map(_norm_txt)
    df_fallback["q_n"] = df_fallback["question_text"].map(_norm_txt)

    def _fill_from_match(out_col: str, sec_contains: str, grp_contains: str, q_contains: str):
        # Solo llena donde está vacío
        if out_col not in code_pivot.columns:
            return
        mask_empty = code_pivot[out_col].isna()
        if not mask_empty.any():
            return
        m = (
            df_fallback["sec_n"].str.contains(_norm_txt(sec_contains))
            & df_fallback["grp_n"].str.contains(_norm_txt(grp_contains))
            & df_fallback["q_n"].str.contains(_norm_txt(q_contains))
        )
        sub = df_fallback[m]
        if sub.empty:
            return
        tmp = sub.pivot_table(index="response_id", values="answer", aggfunc="first")
        # Escribimos solo en filas vacías
        for rid, val in tmp["answer"].items():
            if rid in code_pivot.index and pd.isna(code_pivot.at[rid, out_col]):
                code_pivot.at[rid, out_col] = val

    _fill_from_match("Provincia", "preguntas iniciales", "ubic", "provincia")
    _fill_from_match("Municipio", "preguntas iniciales", "ubic", "municip")
    _fill_from_match("Nombre completo", "preguntas iniciales", "ident", "nombre")
    _fill_from_match("Tipo de documento", "preguntas iniciales", "ident", "tipodedocument")
    _fill_from_match("Número de documento", "preguntas iniciales", "ident", "numerodedocument")
    _fill_from_match("Número de celular", "preguntas iniciales", "ident", "celular")
    _fill_from_match("Correo electrónico", "preguntas iniciales", "ident", "correo")
    _fill_from_match("Cargo o rol", "preguntas iniciales", "ident", "cargo")

    # 4) Pivot general por texto de pregunta
    pivot = df.pivot_table(index="response_id", columns="col", values="answer", aggfunc="first")

    # 5) Asegurar que el Excel incluya TODAS las preguntas activas de la versión (aunque estén vacías)
    qrows = fetchall("""
        SELECT s.sort_order AS sec_order, g.sort_order AS grp_order, q.sort_order AS q_order,
               s.name AS section_name, g.title AS group_title, COALESCE(q.label, q.text) AS question_text
        FROM questions q
        JOIN question_groups g ON g.id = q.group_id
        JOIN sections s ON s.id = g.section_id
        WHERE q.version_id=%s AND q.is_active=TRUE AND g.is_active=TRUE AND s.is_active=TRUE
        ORDER BY s.sort_order, g.sort_order, q.sort_order, q.id;
    """, (version_id,))

    all_question_cols = [f'{r["section_name"]} | {r["group_title"]} | {r["question_text"]}' for r in qrows]

    # Reindex: agrega columnas faltantes con NaN y respeta el orden del formulario
    pivot = pivot.reindex(columns=all_question_cols)

    out = meta.join(code_pivot, how="left").join(pivot, how="left").reset_index()
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

def upsert_question(
    version_id: int,
    question_id,
    group_id: int,
    code,
    label: str,
    text: str,
    help_text: str | None,
    qtype: str,
    required: bool,
    sort_order: int,
    is_active: bool,
    config: dict,
):
    if question_id:
        execute(
            """UPDATE questions
               SET group_id=%s, code=%s, label=%s, text=%s, help_text=%s,
                   qtype=%s, required=%s, sort_order=%s, is_active=%s, config=%s
               WHERE id=%s AND version_id=%s;""",
            (
                group_id,
                code or None,
                label,
                text,
                help_text,
                qtype,
                required,
                sort_order,
                is_active,
                json.dumps(config or {}),
                question_id,
                version_id,
            ),
        )
    else:
        execute(
            """INSERT INTO questions(
                   version_id,group_id,code,label,text,help_text,qtype,required,sort_order,is_active,config
               )
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);""",
            (
                version_id,
                group_id,
                code or None,
                label,
                text,
                help_text,
                qtype,
                required,
                sort_order,
                is_active,
                json.dumps(config or {}),
            ),
        )

def delete_options_for_question(question_id: int):
    execute("DELETE FROM question_options WHERE question_id=%s;", (question_id,))

def insert_option(question_id: int, label: str, value: str, sort_order: int, meta: dict):
    execute("INSERT INTO question_options(question_id,label,value,sort_order,meta) VALUES(%s,%s,%s,%s,%s);",
            (question_id, label, value, sort_order, json.dumps(meta or {})))
