"""Configuration read/write endpoints."""

import os
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["config"])
log = logging.getLogger(__name__)


def _config_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config.yaml",
    )


@router.get("/config")
async def get_config():
    with open(_config_path(), encoding="utf-8") as f:
        return {"data": f.read()}


@router.get("/config/json")
async def get_config_json():
    try:
        import yaml
        with open(_config_path(), encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cfg
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ConfigBody(BaseModel):
    data: str


@router.post("/config")
async def save_config(body: ConfigBody):
    with open(_config_path(), "w", encoding="utf-8") as f:
        f.write(body.data)
    return {"ok": True}
