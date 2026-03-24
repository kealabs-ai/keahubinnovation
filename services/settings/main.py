from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sys
sys.path.insert(0, '/app')
from database import get_db

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class SettingUpsert(BaseModel):
    setting_key: str
    setting_value: str
    description: Optional[str] = None


class SettingDelete(BaseModel):
    setting_key: str


@app.get("/settings/health")
def health():
    return {"status": "ok"}


@app.get("/settings")
def list_settings():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM system_settings ORDER BY setting_key")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.get("/settings/{key}")
def get_setting(key: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM system_settings WHERE setting_key = %s", (key,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Setting not found")
        return row
    finally:
        cursor.close()
        conn.close()


@app.post("/settings/upsert")
def upsert_setting(body: SettingUpsert):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO system_settings (setting_key, setting_value, description)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value), description = VALUES(description)""",
            (body.setting_key, body.setting_value, body.description)
        )
        conn.commit()
        return {"setting_key": body.setting_key, "setting_value": body.setting_value}
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/settings/delete")
def delete_setting(body: SettingDelete):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM system_settings WHERE setting_key = %s", (body.setting_key,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Setting not found")
        return {"deleted": True, "setting_key": body.setting_key}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()
