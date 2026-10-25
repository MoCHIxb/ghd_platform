import os
from uuid import uuid4
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from flask_jwt_extended import create_access_token, get_jwt_identity
import bcrypt
from datetime import datetime
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from extensions import db
from models import MembershipRequest, User, Role
from utils.auth_helper import require_auth, get_current_user
from utils.file_helper import sanitize_original_name

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

ALLOWED_AVATAR_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def _make_reset_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='password-reset')


def _generate_reset_token(user: User) -> str:
    serializer = _make_reset_serializer()
    payload = {'uid': user.user_id, 'ph': user.password_hash[:16]}
    return serializer.dumps(payload)


def _verify_reset_token(token: str, max_age_seconds: int = 1800):
    serializer = _make_reset_serializer()
    payload = serializer.loads(token, max_age=max_age_seconds)
    uid = payload.get('uid')
    pw_mark = payload.get('ph')
    user = User.query.get(uid)
    if not user:
        return None
    if user.password_hash[:16] != pw_mark:
        return None
    return user


@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data:
        return jsonify(msg='缺少请求体'), 400

    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    email    = (data.get('email') or '').strip()
    student_no = (data.get('student_no') or '').strip() or None

    if not username or not password or not email:
        return jsonify(msg='用户名、密码和邮箱不能为空'), 400
    if len(username) < 3 or len(username) > 50:
        return jsonify(msg='用户名长度需在 3~50 个字符之间'), 400
    if len(password) < 6:
        return jsonify(msg='密码不能少于 6 个字符'), 400

    if User.query.filter_by(username=username).first():
        return jsonify(msg='用户名已存在'), 409
    if User.query.filter_by(email=email).first():
        return jsonify(msg='邮箱已被注册'), 409
    if student_no and User.query.filter_by(student_no=student_no).first():
        return jsonify(msg='学号已被使用'), 409

    pw_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user = User(username=username, password_hash=pw_hash, email=email,
                real_name=(data.get('real_name') or '').strip() or None,
                student_no=student_no,
                department_id=None, status=2)
    # 新注册账号默认赋予普通社员角色
    user_role = Role.query.filter_by(role_name='member').first()
    if user_role:
        user.roles.append(user_role)
    db.session.add(user)
    db.session.flush()
    db.session.add(MembershipRequest(
        request_type='注册', user_id=user.user_id,
        reason=(data.get('reason') or '').strip() or None,
    ))
    db.session.commit()
    return jsonify(msg='注册申请已提交，请等待队长审核', user_id=user.user_id), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return jsonify(msg='缺少请求体'), 400

    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify(msg='用户名或密码错误'), 401
    if not bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
        return jsonify(msg='用户名或密码错误'), 401
    if user.status == 0:
        return jsonify(msg='账号已注销或被停用，请联系队长'), 403
    if user.status == 2:
        return jsonify(msg='注册申请仍在等待队长审核'), 403

    user.last_login = datetime.now()
    db.session.commit()

    # PyJWT/Flask-JWT-Extended 新版本对 sub 类型更严格，使用字符串 identity 更稳妥
    token = create_access_token(identity=str(user.user_id))
    return jsonify(token=token, user=user.to_dict()), 200


@auth_bp.route('/profile', methods=['GET'])
@require_auth
def get_profile():
    user = get_current_user()
    return jsonify(user=user.to_dict()), 200


@auth_bp.route('/profile', methods=['PUT'])
@require_auth
def update_profile():
    user = get_current_user()
    data = request.get_json() or {}

    if 'email' in data:
        email = data['email'].strip()
        existing = User.query.filter_by(email=email).first()
        if existing and existing.user_id != user.user_id:
            return jsonify(msg='邮箱已被使用'), 409
        user.email = email
    if 'phone' in data:
        user.phone = data['phone'].strip() or None
    if 'avatar_url' in data:
        user.avatar_url = data['avatar_url'].strip() or None

    db.session.commit()
    return jsonify(msg='个人资料已更新', user=user.to_dict()), 200


@auth_bp.route('/password', methods=['PUT'])
@require_auth
def change_password():
    user = get_current_user()
    data = request.get_json() or {}

    old_pw  = data.get('old_password') or ''
    new_pw  = data.get('new_password') or ''

    if not old_pw or not new_pw:
        return jsonify(msg='旧密码和新密码不能为空'), 400
    if len(new_pw) < 6:
        return jsonify(msg='新密码不能少于 6 个字符'), 400
    if not bcrypt.checkpw(old_pw.encode('utf-8'), user.password_hash.encode('utf-8')):
        return jsonify(msg='旧密码错误'), 401

    user.password_hash = bcrypt.hashpw(new_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    db.session.commit()
    return jsonify(msg='密码已修改'), 200


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()

    if not username or not email:
        return jsonify(msg='用户名和邮箱不能为空'), 400

    user = User.query.filter_by(username=username, email=email).first()
    if not user:
        # 避免账号枚举，返回统一提示
        return jsonify(msg='如信息匹配，重置凭证已生成'), 200

    reset_token = _generate_reset_token(user)
    # 课程项目默认直接返回 token，便于前端演示；生产环境应改为邮件发送
    return jsonify(msg='重置凭证已生成（30分钟有效）', reset_token=reset_token), 200


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json() or {}
    token = (data.get('token') or '').strip()
    new_pw = data.get('new_password') or ''

    if not token or not new_pw:
        return jsonify(msg='重置凭证和新密码不能为空'), 400
    if len(new_pw) < 6:
        return jsonify(msg='新密码不能少于 6 个字符'), 400

    try:
        user = _verify_reset_token(token)
    except SignatureExpired:
        return jsonify(msg='重置凭证已过期，请重新发起找回'), 401
    except BadSignature:
        return jsonify(msg='重置凭证无效'), 401

    if not user:
        return jsonify(msg='重置凭证无效'), 401

    user.password_hash = bcrypt.hashpw(new_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    db.session.commit()
    return jsonify(msg='密码重置成功，请重新登录'), 200


@auth_bp.route('/avatar', methods=['POST'])
@require_auth
def upload_avatar():
    user = get_current_user()
    file = request.files.get('avatar')
    if not file or not file.filename:
        return jsonify(msg='请选择头像文件'), 400

    # 不使用 secure_filename：它会把 '头像.png' 压成 'png'，导致合法图片被判为格式错误。
    _, ext = sanitize_original_name(file.filename)
    if ext not in ALLOWED_AVATAR_EXTS:
        return jsonify(msg='仅支持 png/jpg/jpeg/gif/webp'), 400

    avatar_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'avatars')
    os.makedirs(avatar_dir, exist_ok=True)

    new_name = f"u{user.user_id}_{uuid4().hex}.{ext}"
    target = os.path.join(avatar_dir, new_name)
    file.save(target)

    old_url = user.avatar_url or ''
    if old_url.startswith('/api/auth/avatar/'):
        old_name = old_url.rsplit('/', 1)[-1]
        old_path = os.path.join(avatar_dir, old_name)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    user.avatar_url = f'/api/auth/avatar/{new_name}'
    db.session.commit()
    return jsonify(msg='头像上传成功', avatar_url=user.avatar_url, user=user.to_dict()), 200


@auth_bp.route('/avatar/<path:filename>', methods=['GET'])
def get_avatar(filename):
    avatar_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'avatars')
    return send_from_directory(avatar_dir, filename)
