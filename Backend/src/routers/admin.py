# -*- coding: utf-8 -*-
"""
管理路由：配置管理、日志级别、重启服务、前端日志上报
"""

import subprocess

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from config import PROJECT_ROOT, CONFIG_SCHEMA
from config_manager import get_config_manager
from dependencies import get_pipeline, apply_config_to_pipeline, get_logger
from logger import setup_logger, set_log_level as _set_log_level, get_log_level, set_trace_id

router = APIRouter()
_log = get_logger()


# ==================== 请求模型 ====================

class FrontendLogRequest(BaseModel):
    """前端日志上报请求"""
    level: str = Field(..., description="日志级别: INFO/WARNING/ERROR")
    message: str = Field(..., description="日志内容")
    trace_id: str = Field("-", description="关联的 trace_id")
    url: str = Field("", description="当前页面 URL")
    extra: dict = Field(default_factory=dict, description="额外信息")


_frontend_log = setup_logger(name="pra.frontend")


# ==================== 配置管理 ====================

@router.get("/api/config")
def get_config():
    """获取当前配置"""
    try:
        cm = get_config_manager()
        config = cm.load_config()
        return {"config": config}
    except Exception as e:
        _log.error("获取配置失败: %s", e)
        raise HTTPException(status_code=500, detail="获取配置失败")


@router.post("/api/config")
async def save_config(request: Request):
    """保存配置"""
    try:
        data = await request.json()
        config_data = data.get("config", {})
        cm = get_config_manager()
        result = cm.save_config(config_data)

        # 同步更新运行中的 Pipeline 配置，使配置立即生效
        apply_config_to_pipeline(result.get("saved", {}))

        return result
    except Exception as e:
        _log.error("保存配置失败: %s", e)
        raise HTTPException(status_code=500, detail="保存配置失败")


@router.post("/api/config/reset")
async def reset_config(request: Request):
    """恢复默认配置"""
    try:
        cm = get_config_manager()
        result = cm.reset_config()

        # 重置后同步更新 Pipeline 配置为默认值
        defaults = {item.key: item.default for item in CONFIG_SCHEMA}
        apply_config_to_pipeline(defaults)

        return result
    except Exception as e:
        _log.error("重置配置失败: %s", e)
        raise HTTPException(status_code=500, detail="重置配置失败")


# ==================== 日志级别 ====================

@router.get("/api/log-level")
def get_log_level_api():
    """获取当前日志级别"""
    return {"level": get_log_level()}


@router.post("/api/log-level")
def set_log_level_api(level: str):
    """运行时动态调整日志级别"""
    try:
        new_level = _set_log_level(level)
        return {"level": new_level, "message": f"日志级别已调整为 {new_level}"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== 重启服务 ====================

@router.post("/api/restart")
def restart_service(request: Request):
    """重启服务（调用 restart.sh）"""
    try:
        # restart.sh 在项目根目录（Backend 的上一级）
        project_dir = PROJECT_ROOT.parent
        script_path = project_dir / "restart.sh"
        if not script_path.exists():
            raise HTTPException(status_code=404, detail="重启脚本不存在")

        # 记录操作者信息
        client_ip = request.client.host if request.client else "unknown"
        _log.warning("[安全] 重启请求来自 IP=%s", client_ip)
        _log.info("收到重启请求，执行重启脚本: %s", script_path)

        # 在后台执行，避免响应超时
        subprocess.Popen(["bash", str(script_path)], cwd=str(project_dir))

        return {"message": "重启命令已发送，服务将很快重启"}
    except HTTPException:
        raise
    except Exception as e:
        _log.error("重启失败: %s", e)
        raise HTTPException(status_code=500, detail=f"重启失败: {e}")


# ==================== 前端日志上报 ====================

@router.post("/api/frontend-log")
def frontend_log(req: FrontendLogRequest):
    """接收前端日志，写入后端日志文件，实现前后端日志统一"""
    # 临时设置 trace_id，使日志格式与后端一致
    if req.trace_id and req.trace_id != "-":
        set_trace_id(req.trace_id)

    level = req.level.upper()
    msg = f"[前端] {req.message}"
    if req.url:
        msg += f" | url={req.url}"
    if req.extra:
        msg += f" | extra={req.extra}"

    if level == "ERROR":
        _frontend_log.error(msg)
    elif level == "WARNING":
        _frontend_log.warning(msg)
    else:
        _frontend_log.info(msg)

    # 恢复 trace_id
    if req.trace_id and req.trace_id != "-":
        set_trace_id("-")

    return {"ok": True}
