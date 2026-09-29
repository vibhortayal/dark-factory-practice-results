"""
Pocketful Stage 1: HTTP payment and settlement service
"""
import os
import json
import re
import uuid
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Body
from fastapi.responses import JSONResponse
from passlib.context import CryptContext

# ============================================================================
# Configuration
# ============================================================================

DATABASE_PATH = "/tmp/pocketful.db"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ============================================================================
# Database Functions
# ============================================================================

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute("DROP TABLE IF EXISTS idempotency_keys")
    c.execute("DROP TABLE IF EXISTS payments")
    c.execute("DROP TABLE IF EXISTS requests")
    c.execute("DROP TABLE IF EXISTS tokens")
    c.execute("DROP TABLE IF EXISTS users")
    c.execute("DROP TABLE IF EXISTS global_state")
    
    c.execute("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            handle TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            balance INTEGER NOT NULL
        )
    """)
    
    c.execute("""
        CREATE TABLE tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    c.execute("""
        CREATE TABLE payments (
            id TEXT PRIMARY KEY,
            from_user_id TEXT NOT NULL,
            to_user_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            note TEXT NOT NULL,
            visibility TEXT NOT NULL,
            request_id TEXT,
            settlement_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (from_user_id) REFERENCES users(id),
            FOREIGN KEY (to_user_id) REFERENCES users(id)
        )
    """)
    
    c.execute("""
        CREATE TABLE requests (
            id TEXT PRIMARY KEY,
            requester_id TEXT NOT NULL,
            payer_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            note TEXT NOT NULL,
            status TEXT NOT NULL,
            payment_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (requester_id) REFERENCES users(id),
            FOREIGN KEY (payer_id) REFERENCES users(id)
        )
    """)
    
    c.execute("""
        CREATE TABLE idempotency_keys (
            key TEXT NOT NULL,
            user_id TEXT NOT NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            response_status INTEGER NOT NULL,
            response_body TEXT NOT NULL,
            PRIMARY KEY (key, user_id)
        )
    """)
    
    c.execute("""
        CREATE TABLE global_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()

# ============================================================================
# Utility Functions
# ============================================================================

def now_iso() -> str:
    """Get current timestamp in RFC 3339 format"""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def gen_id(prefix: str) -> str:
    """Generate ID with prefix"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def derive_handle(email: str) -> str:
    """Derive handle from email"""
    local = email.split('@')[0].lower()
    handle = re.sub(r'[^a-z0-9_]', '_', local)
    return handle[:20]

def hash_pwd(pwd: str) -> str:
    """Hash password"""
    return pwd_context.hash(pwd)

def verify_pwd(pwd: str, hsh: str) -> bool:
    """Verify password"""
    return pwd_context.verify(pwd, hsh)

def gen_token() -> str:
    """Generate bearer token"""
    return secrets.token_urlsafe(32)

def get_user_from_auth(auth: Optional[str]) -> Optional[Dict]:
    """Get user from Authorization header"""
    if not auth or not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM tokens WHERE token = ?", (token,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    user_id = row[0]
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return dict(user) if user else None

def get_currency(conn: sqlite3.Connection) -> str:
    """Get currency from global state"""
    c = conn.cursor()
    c.execute("SELECT value FROM global_state WHERE key = 'currency'")
    row = c.fetchone()
    return row[0] if row else "EUR"

def validate_amount(val: Any) -> int:
    """Validate amount is integer in valid range"""
    if not isinstance(val, int) or isinstance(val, bool):
        raise ValueError("amount must be integer")
    if val < 1 or val > 1000000000:
        raise ValueError("amount out of range")
    return val

def validate_note(val: Any) -> str:
    """Validate note"""
    if not isinstance(val, str):
        raise ValueError("note must be string")
    if len(val) > 200:
        raise ValueError("note too long")
    return val

def validate_visibility(val: Any) -> str:
    """Validate visibility"""
    if val not in ["public", "private"]:
        raise ValueError("visibility must be public or private")
    return val

def validate_handle(val: Any) -> str:
    """Validate handle format"""
    if not isinstance(val, str) or not re.match(r'^[a-z0-9_]{1,20}$', val):
        raise ValueError("invalid handle")
    return val

# ============================================================================
# FastAPI Setup
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown"""
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

# ============================================================================
# Health & Test Endpoints
# ============================================================================

@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})

def make_error(code: str, msg: str, status: int) -> tuple:
    """Create error response"""
    return JSONResponse(
        {"error": {"code": code, "message": msg}},
        status_code=status
    )

@app.post("/_test/reset")
async def reset(body: Dict = Body(...)):
    """Reset service state with fixture"""
    try:
        currency = body.get("currency")
        minor_units = body.get("minor_units")
        
        if minor_units not in [0, 2, 3]:
            return make_error("validation_failed", "Invalid minor_units", 422)
        
        # Clear and reinit
        init_db()
        
        conn = get_db()
        c = conn.cursor()
        
        # Store global state
        c.execute("INSERT INTO global_state VALUES (?, ?)", ("currency", currency))
        c.execute("INSERT INTO global_state VALUES (?, ?)", ("minor_units", str(minor_units)))
        
        operators = body.get("settlement_operator_ids", [])
        c.execute("INSERT INTO global_state VALUES (?, ?)", ("operators", json.dumps(operators)))
        
        # Insert users
        for user in body.get("users", []):
            if user["balance"] < 0:
                conn.close()
                return make_error("validation_failed", "Negative balance", 422)
            
            c.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
                (user["id"], user["email"], user["handle"], user["display_name"],
                 hash_pwd(user["password"]), user["balance"])
            )
        
        # Insert payments
        for payment in body.get("payments", []):
            c.execute(
                "INSERT INTO payments (id, from_user_id, to_user_id, amount, note, visibility, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (payment["id"], payment["from_user_id"], payment["to_user_id"],
                 payment["amount"], payment["note"], payment["visibility"], now_iso())
            )
        
        # Insert requests
        for req in body.get("requests", []):
            c.execute(
                "INSERT INTO requests (id, requester_id, payer_id, amount, note, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (req["id"], req["requester_id"], req["payer_id"], req["amount"],
                 req["note"], req["status"], now_iso())
            )
        
        conn.commit()
        conn.close()
        return JSONResponse(status_code=204, content=None)
    except Exception as e:
        return make_error("validation_failed", str(e), 422)

@app.get("/_test/export")
async def export_state():
    """Export service state"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT value FROM global_state WHERE key = 'currency'")
    currency = c.fetchone()[0]
    
    c.execute("SELECT value FROM global_state WHERE key = 'minor_units'")
    minor_units = int(c.fetchone()[0])
    
    c.execute("SELECT * FROM users")
    users = [dict(row) for row in c.fetchall()]
    
    c.execute("SELECT * FROM payments ORDER BY created_at")
    payments = [dict(row) for row in c.fetchall()]
    
    c.execute("SELECT * FROM requests ORDER BY created_at")
    requests = [dict(row) for row in c.fetchall()]
    
    c.execute("SELECT value FROM global_state WHERE key = 'operators'")
    operators = json.loads(c.fetchone()[0])
    
    conn.close()
    
    return JSONResponse({
        "track": "pocketful",
        "format_version": 1,
        "state": {
            "currency": currency,
            "minor_units": minor_units,
            "users": users,
            "payments": payments,
            "requests": requests,
            "settlement_operator_ids": operators
        }
    })

@app.post("/_test/import")
async def import_state(body: Dict = Body(...)):
    """Import service state"""
    # Same as reset with the fixture from state
    fixture = body.get("state", {})
    fixture.setdefault("settlement_operator_ids", [])
    return await reset(fixture)

# ============================================================================
# Auth Endpoints
# ============================================================================

@app.post("/auth/signup")
async def signup(body: Dict = Body(...)):
    """Sign up new user"""
    email = body.get("email")
    password = body.get("password")
    display_name = body.get("display_name")
    
    # Validate email format
    if not email or "@" not in email or email.count("@") != 1:
        return make_error("validation_failed", "Invalid email format", 422)
    
    # Validate password
    if not password or len(password) < 8:
        return make_error("validation_failed", "Password too short", 422)
    
    if not display_name:
        return make_error("validation_failed", "Missing display_name", 422)
    
    handle = derive_handle(email)
    
    conn = get_db()
    c = conn.cursor()
    
    # Check email exists
    c.execute("SELECT id FROM users WHERE email = ?", (email,))
    if c.fetchone():
        conn.close()
        return make_error("email_taken", "Email already registered", 409)
    
    # Check handle exists
    c.execute("SELECT id FROM users WHERE handle = ?", (handle,))
    if c.fetchone():
        conn.close()
        return make_error("handle_taken", "Handle taken", 409)
    
    # Create user
    user_id = gen_id("u")
    token = gen_token()
    
    c.execute(
        "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, email, handle, display_name, hash_pwd(password), 0)
    )
    c.execute("INSERT INTO tokens VALUES (?, ?)", (token, user_id))
    
    conn.commit()
    conn.close()
    
    return JSONResponse({
        "user_id": user_id,
        "display_name": display_name,
        "token": token
    }, status_code=201)

@app.post("/auth/login")
async def login(body: Dict = Body(...)):
    """Log in user"""
    email = body.get("email")
    password = body.get("password")
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = c.fetchone()
    
    if not user or not verify_pwd(password, user["password_hash"]):
        conn.close()
        return make_error("unauthenticated", "Invalid credentials", 401)
    
    token = gen_token()
    c.execute("INSERT INTO tokens VALUES (?, ?)", (token, user["id"]))
    conn.commit()
    conn.close()
    
    return JSONResponse({
        "user_id": user["id"],
        "display_name": user["display_name"],
        "token": token
    })

# ============================================================================
# User Endpoint
# ============================================================================

@app.get("/me")
async def me(authorization: Optional[str] = Header(None)):
    """Get current user info"""
    user = get_user_from_auth(authorization)
    if not user:
        return make_error("unauthenticated", "Missing/invalid token", 401)
    
    conn = get_db()
    return JSONResponse({
        "user_id": user["id"],
        "display_name": user["display_name"],
        "handle": user["handle"],
        "balance": user["balance"],
        "currency": get_currency(conn),
        "minor_units": int(conn.cursor().execute("SELECT value FROM global_state WHERE key = 'minor_units'").fetchone()[0])
    })

# ============================================================================
# Idempotency Helper
# ============================================================================

def check_idempotency(key: str, user_id: str, method: str, path: str, body: Dict) -> Optional[tuple]:
    """Check and record idempotency key"""
    if not key or len(key) < 1 or len(key) > 255:
        return make_error("missing_idempotency_key", "Missing/invalid Idempotency-Key", 400)
    
    body_hash = json.dumps(body, sort_keys=True)
    
    conn = get_db()
    c = conn.cursor()
    
    # Check if key exists with same body
    c.execute(
        "SELECT response_status, response_body FROM idempotency_keys WHERE key = ? AND user_id = ?",
        (key, user_id)
    )
    existing = c.fetchone()
    
    if existing:
        resp_body = json.loads(existing["response_body"])
        conn.close()
        # If original was 201, replay returns 200
        status = 200 if existing["response_status"] == 201 else existing["response_status"]
        return JSONResponse(resp_body, status_code=status)
    
    # Check if key used with different body
    c.execute(
        "SELECT * FROM idempotency_keys WHERE key = ? AND user_id = ? AND body_hash != ?",
        (key, user_id, body_hash)
    )
    if c.fetchone():
        conn.close()
        return make_error("idempotency_key_reuse", "Key used with different body", 409)
    
    conn.close()
    return None

def record_idempotency(key: str, user_id: str, method: str, path: str, body: Dict, status: int, response: Dict):
    """Record idempotency key"""
    body_hash = json.dumps(body, sort_keys=True)
    response_body = json.dumps(response)
    
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO idempotency_keys VALUES (?, ?, ?, ?, ?, ?, ?)",
        (key, user_id, method, path, body_hash, status, response_body)
    )
    conn.commit()
    conn.close()

# ============================================================================
# Payment Endpoints
# ============================================================================

@app.post("/payments")
async def create_payment(
    authorization: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None),
    body: Dict = Body(...)
):
    """Create payment"""
    user = get_user_from_auth(authorization)
    if not user:
        return make_error("unauthenticated", "Missing/invalid token", 401)
    
    # Check idempotency
    idem_result = check_idempotency(idempotency_key, user["id"], "POST", "/payments", body)
    if idem_result:
        return idem_result
    
    # Validate
    try:
        to_handle = validate_handle(body.get("to_handle"))
        amount = validate_amount(body.get("amount"))
        note = validate_note(body.get("note", ""))
        visibility = validate_visibility(body.get("visibility", "public"))
    except ValueError as e:
        return make_error("validation_failed", str(e), 422)
    
    conn = get_db()
    c = conn.cursor()
    
    # Check self-payment
    if user["handle"] == to_handle:
        conn.close()
        return make_error("self_payment", "Cannot pay yourself", 422)
    
    # Find recipient
    c.execute("SELECT id FROM users WHERE handle = ?", (to_handle,))
    recipient = c.fetchone()
    if not recipient:
        conn.close()
        return make_error("not_found", "Recipient not found", 404)
    
    # Check balance
    if user["balance"] < amount:
        conn.close()
        return make_error("insufficient_funds", "Insufficient balance", 409)
    
    # Create payment
    payment_id = gen_id("p")
    created_at = now_iso()
    to_user_id = recipient[0]
    
    c.execute(
        "INSERT INTO payments (id, from_user_id, to_user_id, amount, note, visibility, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (payment_id, user["id"], to_user_id, amount, note, visibility, created_at)
    )
    
    # Update balances
    c.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, user["id"]))
    c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, to_user_id))
    
    conn.commit()
    conn.close()
    
    response = {
        "payment_id": payment_id,
        "from_user_id": user["id"],
        "from_handle": user["handle"],
        "to_user_id": to_user_id,
        "to_handle": to_handle,
        "amount": amount,
        "currency": "EUR",  # TODO from global
        "note": note,
        "visibility": visibility,
        "request_id": None,
        "created_at": created_at
    }
    
    record_idempotency(idempotency_key, user["id"], "POST", "/payments", body, 201, response)
    
    return JSONResponse(response, status_code=201)

@app.get("/activity")
async def activity(
    authorization: Optional[str] = Header(None),
    limit: int = 50,
    offset: int = 0
):
    """Get activity feed"""
    user = get_user_from_auth(authorization)
    if not user:
        return make_error("unauthenticated", "Missing/invalid token", 401)
    
    # Validate pagination
    if limit < 1 or limit > 200 or offset < 0:
        return make_error("validation_failed", "Invalid pagination", 422)
    
    conn = get_db()
    c = conn.cursor()
    
    # Get all payments sorted by created_at DESC
    c.execute("SELECT * FROM payments ORDER BY created_at DESC")
    all_payments = [dict(row) for row in c.fetchall()]
    
    # Filter by visibility rules
    visible = []
    for p in all_payments:
        if p["visibility"] == "public" or p["from_user_id"] == user["id"] or p["to_user_id"] == user["id"]:
            visible.append(p)
    
    # Paginate
    paginated = visible[offset:offset+limit]
    currency = get_currency(conn)
    conn.close()
    
    # Enrich
    enriched = []
    for p in paginated:
        conn2 = get_db()
        c2 = conn2.cursor()
        c2.execute("SELECT handle FROM users WHERE id = ?", (p["from_user_id"],))
        from_h = c2.fetchone()[0]
        c2.execute("SELECT handle FROM users WHERE id = ?", (p["to_user_id"],))
        to_h = c2.fetchone()[0]
        conn2.close()
        
        enriched.append({
            "payment_id": p["id"],
            "from_user_id": p["from_user_id"],
            "from_handle": from_h,
            "to_user_id": p["to_user_id"],
            "to_handle": to_h,
            "amount": p["amount"],
            "currency": currency,
            "note": p["note"],
            "visibility": p["visibility"],
            "request_id": p["request_id"],
            "settlement_id": p["settlement_id"],
            "created_at": p["created_at"]
        })
    
    return JSONResponse({
        "payments": enriched,
        "has_more": (offset + limit) < len(visible)
    })

# ============================================================================
# Request Endpoints
# ============================================================================

@app.post("/requests")
async def create_request(
    authorization: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None),
    body: Dict = Body(...)
):
    """Create money request"""
    user = get_user_from_auth(authorization)
    if not user:
        return make_error("unauthenticated", "Missing/invalid token", 401)
    
    # Check idempotency
    idem_result = check_idempotency(idempotency_key, user["id"], "POST", "/requests", body)
    if idem_result:
        return idem_result
    
    # Validate
    try:
        payer_handle = validate_handle(body.get("payer_handle"))
        amount = validate_amount(body.get("amount"))
        note = validate_note(body.get("note", ""))
    except ValueError as e:
        return make_error("validation_failed", str(e), 422)
    
    conn = get_db()
    c = conn.cursor()
    
    # Check self-request
    if user["handle"] == payer_handle:
        conn.close()
        return make_error("self_request", "Cannot request from yourself", 422)
    
    # Find payer
    c.execute("SELECT id FROM users WHERE handle = ?", (payer_handle,))
    payer = c.fetchone()
    if not payer:
        conn.close()
        return make_error("not_found", "Payer not found", 404)
    
    # Create request
    request_id = gen_id("rq")
    created_at = now_iso()
    
    c.execute(
        "INSERT INTO requests (id, requester_id, payer_id, amount, note, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (request_id, user["id"], payer[0], amount, note, "pending", created_at)
    )
    
    conn.commit()
    
    currency = get_currency(conn)
    conn.close()
    
    response = {
        "request_id": request_id,
        "requester_id": user["id"],
        "requester_handle": user["handle"],
        "payer_id": payer[0],
        "payer_handle": payer_handle,
        "amount": amount,
        "currency": currency,
        "note": note,
        "status": "pending",
        "payment_id": None,
        "created_at": created_at
    }
    
    record_idempotency(idempotency_key, user["id"], "POST", "/requests", body, 201, response)
    
    return JSONResponse(response, status_code=201)

@app.post("/requests/{request_id}/pay")
async def pay_request(
    request_id: str,
    authorization: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None),
    body: Dict = Body(...)
):
    """Pay a money request"""
    user = get_user_from_auth(authorization)
    if not user:
        return make_error("unauthenticated", "Missing/invalid token", 401)
    
    # Check idempotency
    idem_result = check_idempotency(idempotency_key, user["id"], "POST", f"/requests/{request_id}/pay", body)
    if idem_result:
        return idem_result
    
    # Validate visibility
    try:
        visibility = validate_visibility(body.get("visibility", "public"))
    except ValueError as e:
        return make_error("validation_failed", str(e), 422)
    
    conn = get_db()
    c = conn.cursor()
    
    # Get request
    c.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
    req = c.fetchone()
    if not req:
        conn.close()
        return make_error("not_found", "Request not found", 404)
    
    # Check payer
    if req["payer_id"] != user["id"]:
        conn.close()
        return make_error("forbidden", "Not the payer", 403)
    
    # Check status
    if req["status"] != "pending":
        conn.close()
        return make_error("request_not_pending", "Request not pending", 409)
    
    # Check balance
    if user["balance"] < req["amount"]:
        conn.close()
        return make_error("insufficient_funds", "Insufficient balance", 409)
    
    # Create payment
    payment_id = gen_id("p")
    created_at = now_iso()
    
    c.execute(
        "INSERT INTO payments (id, from_user_id, to_user_id, amount, note, visibility, request_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (payment_id, user["id"], req["requester_id"], req["amount"], req["note"], visibility, request_id, created_at)
    )
    
    # Update request
    c.execute("UPDATE requests SET status = ?, payment_id = ? WHERE id = ?", ("paid", payment_id, request_id))
    
    # Update balances
    c.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (req["amount"], user["id"]))
    c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (req["amount"], req["requester_id"]))
    
    conn.commit()
    
    # Get handles
    c.execute("SELECT handle FROM users WHERE id = ?", (user["id"],))
    payer_h = c.fetchone()[0]
    c.execute("SELECT handle FROM users WHERE id = ?", (req["requester_id"],))
    requester_h = c.fetchone()[0]
    
    currency = get_currency(conn)
    conn.close()
    
    response = {
        "payment_id": payment_id,
        "from_user_id": user["id"],
        "from_handle": payer_h,
        "to_user_id": req["requester_id"],
        "to_handle": requester_h,
        "amount": req["amount"],
        "currency": currency,
        "note": req["note"],
        "visibility": visibility,
        "request_id": request_id,
        "created_at": created_at
    }
    
    record_idempotency(idempotency_key, user["id"], "POST", f"/requests/{request_id}/pay", body, 201, response)
    
    return JSONResponse(response, status_code=201)

@app.post("/requests/{request_id}/decline")
async def decline_request(
    request_id: str,
    authorization: Optional[str] = Header(None)
):
    """Decline money request"""
    user = get_user_from_auth(authorization)
    if not user:
        return make_error("unauthenticated", "Missing/invalid token", 401)
    
    conn = get_db()
    c = conn.cursor()
    
    # Get request
    c.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
    req = c.fetchone()
    if not req:
        conn.close()
        return make_error("not_found", "Request not found", 404)
    
    # Check payer
    if req["payer_id"] != user["id"]:
        conn.close()
        return make_error("forbidden", "Not the payer", 403)
    
    # Check status
    if req["status"] not in ["pending", "declined"]:
        conn.close()
        return make_error("request_not_pending", "Request not pending", 409)
    
    # Update
    c.execute("UPDATE requests SET status = ? WHERE id = ?", ("declined", request_id))
    conn.commit()
    
    # Get handles
    c.execute("SELECT handle FROM users WHERE id = ?", (req["requester_id"],))
    req_h = c.fetchone()[0]
    c.execute("SELECT handle FROM users WHERE id = ?", (req["payer_id"],))
    payer_h = c.fetchone()[0]
    
    currency = get_currency(conn)
    conn.close()
    
    return JSONResponse({
        "request_id": req["id"],
        "requester_id": req["requester_id"],
        "requester_handle": req_h,
        "payer_id": req["payer_id"],
        "payer_handle": payer_h,
        "amount": req["amount"],
        "currency": currency,
        "note": req["note"],
        "status": "declined",
        "payment_id": None,
        "created_at": req["created_at"]
    })

@app.post("/requests/{request_id}/cancel")
async def cancel_request(
    request_id: str,
    authorization: Optional[str] = Header(None)
):
    """Cancel money request"""
    user = get_user_from_auth(authorization)
    if not user:
        return make_error("unauthenticated", "Missing/invalid token", 401)
    
    conn = get_db()
    c = conn.cursor()
    
    # Get request
    c.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
    req = c.fetchone()
    if not req:
        conn.close()
        return make_error("not_found", "Request not found", 404)
    
    # Check requester
    if req["requester_id"] != user["id"]:
        conn.close()
        return make_error("forbidden", "Not the requester", 403)
    
    # Check status
    if req["status"] not in ["pending", "cancelled"]:
        conn.close()
        return make_error("request_not_pending", "Request not pending", 409)
    
    # Update
    c.execute("UPDATE requests SET status = ? WHERE id = ?", ("cancelled", request_id))
    conn.commit()
    
    # Get handles
    c.execute("SELECT handle FROM users WHERE id = ?", (req["requester_id"],))
    req_h = c.fetchone()[0]
    c.execute("SELECT handle FROM users WHERE id = ?", (req["payer_id"],))
    payer_h = c.fetchone()[0]
    
    currency = get_currency(conn)
    conn.close()
    
    return JSONResponse({
        "request_id": req["id"],
        "requester_id": req["requester_id"],
        "requester_handle": req_h,
        "payer_id": req["payer_id"],
        "payer_handle": payer_h,
        "amount": req["amount"],
        "currency": currency,
        "note": req["note"],
        "status": "cancelled",
        "payment_id": None,
        "created_at": req["created_at"]
    })

@app.get("/requests")
async def list_requests(
    authorization: Optional[str] = Header(None),
    direction: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """List money requests"""
    user = get_user_from_auth(authorization)
    if not user:
        return make_error("unauthenticated", "Missing/invalid token", 401)
    
    # Validate
    if direction and direction not in ["incoming", "outgoing"]:
        return make_error("validation_failed", "Invalid direction", 422)
    
    if status and status not in ["pending", "paid", "declined", "cancelled"]:
        return make_error("validation_failed", "Invalid status", 422)
    
    if limit < 1 or limit > 200 or offset < 0:
        return make_error("validation_failed", "Invalid pagination", 422)
    
    conn = get_db()
    c = conn.cursor()
    
    # Build query
    where = "(requester_id = ? OR payer_id = ?)"
    params = [user["id"], user["id"]]
    
    if direction == "incoming":
        where = "payer_id = ?"
        params = [user["id"]]
    elif direction == "outgoing":
        where = "requester_id = ?"
        params = [user["id"]]
    
    if status:
        where += " AND status = ?"
        params.append(status)
    
    # Get count and requests
    c.execute(f"SELECT COUNT(*) as cnt FROM requests WHERE {where}", params)
    total = c.fetchone()["cnt"]
    
    c.execute(
        f"SELECT * FROM requests WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset]
    )
    requests = [dict(row) for row in c.fetchall()]
    
    currency = get_currency(conn)
    conn.close()
    
    # Enrich
    enriched = []
    for req in requests:
        conn2 = get_db()
        c2 = conn2.cursor()
        c2.execute("SELECT handle FROM users WHERE id = ?", (req["requester_id"],))
        req_h = c2.fetchone()[0]
        c2.execute("SELECT handle FROM users WHERE id = ?", (req["payer_id"],))
        payer_h = c2.fetchone()[0]
        conn2.close()
        
        enriched.append({
            "request_id": req["id"],
            "requester_id": req["requester_id"],
            "requester_handle": req_h,
            "payer_id": req["payer_id"],
            "payer_handle": payer_h,
            "amount": req["amount"],
            "currency": currency,
            "note": req["note"],
            "status": req["status"],
            "payment_id": req["payment_id"],
            "created_at": req["created_at"]
        })
    
    return JSONResponse({
        "requests": enriched,
        "has_more": (offset + limit) < total
    })

# ============================================================================
# Split Endpoints
# ============================================================================

@app.post("/splits")
async def create_split(
    authorization: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None),
    body: Dict = Body(...)
):
    """Create bill split"""
    user = get_user_from_auth(authorization)
    if not user:
        return make_error("unauthenticated", "Missing/invalid token", 401)
    
    # Check idempotency
    idem_result = check_idempotency(idempotency_key, user["id"], "POST", "/splits", body)
    if idem_result:
        return idem_result
    
    # Validate
    try:
        amount = validate_amount(body.get("amount"))
        handles = body.get("participant_handles")
        if not isinstance(handles, list) or len(handles) == 0 or len(handles) != len(set(handles)):
            raise ValueError("Invalid participant_handles")
        for h in handles:
            validate_handle(h)
        note = validate_note(body.get("note", ""))
    except ValueError as e:
        return make_error("validation_failed", str(e), 422)
    
    conn = get_db()
    c = conn.cursor()
    
    # Verify all handles exist
    for h in handles:
        c.execute("SELECT id FROM users WHERE handle = ?", (h,))
        if not c.fetchone():
            conn.close()
            return make_error("not_found", f"Handle {h} not found", 404)
    
    # Calculate shares
    n = len(handles)
    base = amount // n
    remainder = amount % n
    shares = [base + (1 if i < remainder else 0) for i in range(n)]
    
    # Create requests for each participant except caller
    split_id = gen_id("sp")
    created_at = now_iso()
    created_requests = []
    
    for i, h in enumerate(handles):
        c.execute("SELECT id FROM users WHERE handle = ?", (h,))
        user_id = c.fetchone()[0]
        
        if user_id != user["id"]:
            request_id = gen_id("rq")
            c.execute(
                "INSERT INTO requests (id, requester_id, payer_id, amount, note, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (request_id, user["id"], user_id, shares[i], note, "pending", created_at)
            )
            created_requests.append({
                "request_id": request_id,
                "requester_id": user["id"],
                "requester_handle": user["handle"],
                "payer_id": user_id,
                "payer_handle": h,
                "amount": shares[i],
                "currency": "EUR",
                "note": note,
                "status": "pending",
                "payment_id": None,
                "created_at": created_at
            })
    
    conn.commit()
    currency = get_currency(conn)
    conn.close()
    
    response = {
        "split_id": split_id,
        "amount": amount,
        "currency": currency,
        "note": note,
        "shares": [{"handle": h, "amount": shares[i]} for i, h in enumerate(handles)],
        "requests": created_requests,
        "created_at": created_at
    }
    
    record_idempotency(idempotency_key, user["id"], "POST", "/splits", body, 201, response)
    
    return JSONResponse(response, status_code=201)

# ============================================================================
# Settlement Endpoints
# ============================================================================

@app.post("/settlements")
async def create_settlement(
    authorization: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None),
    body: Dict = Body(...)
):
    """Execute atomic settlement"""
    user = get_user_from_auth(authorization)
    if not user:
        return make_error("unauthenticated", "Missing/invalid token", 401)
    
    # Check idempotency
    idem_result = check_idempotency(idempotency_key, user["id"], "POST", "/settlements", body)
    if idem_result:
        return idem_result
    
    conn = get_db()
    c = conn.cursor()
    
    # Check operator
    c.execute("SELECT value FROM global_state WHERE key = 'operators'")
    ops_row = c.fetchone()
    ops = json.loads(ops_row[0]) if ops_row else []
    
    if user["id"] not in ops:
        conn.close()
        return make_error("forbidden", "Not an operator", 403)
    
    # Validate transfers
    transfers = body.get("transfers")
    if not isinstance(transfers, list) or len(transfers) < 1 or len(transfers) > 32:
        conn.close()
        return make_error("validation_failed", "Invalid transfers count", 422)
    
    # Pre-validate all transfers
    for xfer in transfers:
        try:
            from_h = validate_handle(xfer.get("from_handle"))
            to_h = validate_handle(xfer.get("to_handle"))
            amt = validate_amount(xfer.get("amount"))
            note = validate_note(xfer.get("note", ""))
            vis = validate_visibility(xfer.get("visibility", "public"))
        except ValueError as e:
            conn.close()
            return make_error("validation_failed", str(e), 422)
        
        if from_h == to_h:
            conn.close()
            return make_error("self_payment", "Cannot transfer to self", 422)
        
        # Check handles exist
        c.execute("SELECT id FROM users WHERE handle = ?", (from_h,))
        if not c.fetchone():
            conn.close()
            return make_error("not_found", f"Handle {from_h} not found", 404)
        
        c.execute("SELECT id FROM users WHERE handle = ?", (to_h,))
        if not c.fetchone():
            conn.close()
            return make_error("not_found", f"Handle {to_h} not found", 404)
    
    # Check affordability
    balances = {}
    for xfer in transfers:
        c.execute("SELECT balance FROM users WHERE handle = ?", (xfer["from_handle"],))
        from_id_row = c.execute("SELECT id FROM users WHERE handle = ?", (xfer["from_handle"],)).fetchone()
        from_id = from_id_row[0]
        if from_id not in balances:
            balances[from_id] = c.execute("SELECT balance FROM users WHERE id = ?", (from_id,)).fetchone()[0]
        
        c.execute("SELECT id FROM users WHERE handle = ?", (xfer["to_handle"],))
        to_id_row = c.fetchone()
        to_id = to_id_row[0]
        if to_id not in balances:
            balances[to_id] = c.execute("SELECT balance FROM users WHERE id = ?", (to_id,)).fetchone()[0]
        
        balances[from_id] -= xfer["amount"]
        balances[to_id] += xfer["amount"]
    
    for bid, bal in balances.items():
        if bal < 0:
            conn.close()
            return make_error("insufficient_funds", "Insufficient funds", 409)
    
    # Execute
    settlement_id = gen_id("st")
    created_at = now_iso()
    payments = []
    
    for xfer in transfers:
        payment_id = gen_id("p")
        
        c.execute("SELECT id FROM users WHERE handle = ?", (xfer["from_handle"],))
        from_id = c.fetchone()[0]
        c.execute("SELECT id FROM users WHERE handle = ?", (xfer["to_handle"],))
        to_id = c.fetchone()[0]
        
        c.execute(
            "INSERT INTO payments (id, from_user_id, to_user_id, amount, note, visibility, settlement_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (payment_id, from_id, to_id, xfer["amount"], xfer.get("note", ""), xfer.get("visibility", "public"), settlement_id, created_at)
        )
        
        c.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (xfer["amount"], from_id))
        c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (xfer["amount"], to_id))
        
        payments.append({
            "payment_id": payment_id,
            "from_user_id": from_id,
            "from_handle": xfer["from_handle"],
            "to_user_id": to_id,
            "to_handle": xfer["to_handle"],
            "amount": xfer["amount"],
            "currency": "EUR",
            "note": xfer.get("note", ""),
            "visibility": xfer.get("visibility", "public"),
            "request_id": None,
            "settlement_id": settlement_id,
            "created_at": created_at
        })
    
    conn.commit()
    conn.close()
    
    response = {
        "settlement_id": settlement_id,
        "committed_at": created_at,
        "payments": payments
    }
    
    record_idempotency(idempotency_key, user["id"], "POST", "/settlements", body, 201, response)
    
    return JSONResponse(response, status_code=201)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
