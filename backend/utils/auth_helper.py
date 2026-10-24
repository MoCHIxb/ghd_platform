from functools import wraps
from datetime import datetime
from flask import jsonify, request
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity, decode_token
from extensions import db


def get_current_user():
    """从 JWT 中取出当前用户对象，不存在返回 None"""
    from models import User
    try:
        # 1) 优先从 Authorization 头读取 JWT
        verify_jwt_in_request(optional=True)
        uid = get_jwt_identity()

        # 2) 若头中无 token，则兼容从 URL 查询参数 token 读取（用于 audio/video 与下载链接）
        if uid is None:
            token = request.args.get('token')
            if token:
                payload = decode_token(token)
                uid = payload.get('sub')

        if uid is None:
            return None

        return User.query.get(int(uid))
    except Exception:
        return None


def require_auth(f):
    """要求 JWT 登录的路由装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        from models import User
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify(msg='请先登录'), 401
        try:
            uid = int(get_jwt_identity())
        except Exception:
            return jsonify(msg='请先登录'), 401
        user = User.query.get(uid)
        if not user or user.status == 0:
            return jsonify(msg='账号已被禁用'), 403
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """要求 admin 角色的路由装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        from models import User
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify(msg='请先登录'), 401
        try:
            uid = int(get_jwt_identity())
        except Exception:
            return jsonify(msg='请先登录'), 401
        user = User.query.get(uid)
        if not user or user.status == 0:
            return jsonify(msg='账号已被禁用'), 403
        if not (user.has_role('admin') or user.has_role('captain')):
            return jsonify(msg='权限不足，需要管理员身份'), 403
        return f(*args, **kwargs)
    return decorated


def require_roles(*role_names):
    """要求拥有任一指定角色；队长默认拥有全部业务权限。"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            try:
                verify_jwt_in_request()
                uid = int(get_jwt_identity())
            except Exception:
                return jsonify(msg='请先登录'), 401
            from models import User
            user = User.query.get(uid)
            if not user or user.status == 0:
                return jsonify(msg='账号已被禁用'), 403
            allowed = set(role_names) | {'captain', 'admin'}
            if not any(user.has_role(name) for name in allowed):
                return jsonify(msg='权限不足'), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def check_file_access(file, user, action: str) -> bool:
    """
    判断 user 对 file 是否具有 action 权限。
    action: 'read' | 'download'
    返回 True 允许, False 拒绝
    """
    from models import FilePermission
    if file.status != 1:
        return False
    # 公开文件所有人可读（但下载需登录）
    if file.visibility == 1:
        if action == 'read':
            return True
        # download 需要登录
        return user is not None
    # 私有文件或授权文件：必须登录
    if user is None:
        return False
    # 上传者和管理员拥有所有权限
    if file.uploader_id == user.user_id or user.has_role('admin'):
        return True
    # 检查 file_permission 表中的授权记录
    if file.visibility == 2:
        fp = FilePermission.query.filter_by(file_id=file.file_id, user_id=user.user_id).first()
        if fp and fp.is_valid():
            if action == 'read':
                return True
            if action == 'download' and fp.permission_type == 'download':
                return True
    return False


def log_access(file_id: int, user_id, action: str):
    """写入访问日志"""
    from models import AccessLog
    log = AccessLog(
        file_id=file_id,
        user_id=user_id,
        action=action,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')[:200],
    )
    db.session.add(log)
    db.session.commit()
