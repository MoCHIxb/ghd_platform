from datetime import datetime, timedelta

import bcrypt
from flask import Blueprint, jsonify, request

from extensions import db
from models import (
    Department, DepartmentApplication, ForumComment, ForumPost,
    LeadershipTransfer, MembershipRequest, OperationRecord, Role,
    TemporaryDepartmentGrant, User,
)
from utils.auth_helper import get_current_user, require_auth


governance_bp = Blueprint('governance', __name__, url_prefix='/api/governance')


def _is_captain(user):
    return bool(user and (user.has_role('captain') or user.has_role('admin')))


def _is_minister(user, department_id=None):
    return bool(user and user.has_role('minister') and user.department_id and
                (department_id is None or user.department_id == department_id))


def _deny(condition, message='权限不足'):
    return None if condition else (jsonify(msg=message), 403)


def _record(user, action, target_type, target_id=None, target_name=None, detail=None):
    db.session.add(OperationRecord(
        module='organization', action=action, target_type=target_type,
        target_id=target_id, target_name=target_name,
        operator_id=user.user_id if user else None, detail=detail,
        occurred_at=datetime.now(),
    ))


@governance_bp.route('/dashboard', methods=['GET'])
@require_auth
def dashboard():
    user = get_current_user()
    membership = []
    if _is_captain(user):
        membership = MembershipRequest.query.filter_by(status='待审核').order_by(
            MembershipRequest.created_at).all()
        department_query = DepartmentApplication.query.filter_by(status='待审核')
        grants = TemporaryDepartmentGrant.query.order_by(
            TemporaryDepartmentGrant.created_at.desc()).limit(100).all()
    elif _is_minister(user):
        department_query = DepartmentApplication.query.filter_by(
            status='待审核', department_id=user.department_id)
        grants = TemporaryDepartmentGrant.query.filter_by(
            department_id=user.department_id).order_by(
            TemporaryDepartmentGrant.created_at.desc()).limit(100).all()
    else:
        department_query = DepartmentApplication.query.filter_by(user_id=user.user_id)
        grants = TemporaryDepartmentGrant.query.filter_by(user_id=user.user_id).order_by(
            TemporaryDepartmentGrant.created_at.desc()).limit(30).all()
    transfers = LeadershipTransfer.query.filter(
        (LeadershipTransfer.from_user_id == user.user_id) |
        (LeadershipTransfer.to_user_id == user.user_id)
    ).order_by(LeadershipTransfer.created_at.desc()).all()
    return jsonify(
        membership_requests=[row.to_dict() for row in membership],
        department_applications=[row.to_dict() for row in department_query.order_by(
            DepartmentApplication.created_at.desc()).all()],
        grants=[row.to_dict() for row in grants],
        transfers=[row.to_dict() for row in transfers],
    ), 200


@governance_bp.route('/membership-requests/<int:request_id>/review', methods=['PUT'])
@require_auth
def review_membership(request_id):
    captain = get_current_user()
    denied = _deny(_is_captain(captain), '仅队长可审核入队和注销申请')
    if denied:
        return denied
    row = MembershipRequest.query.get_or_404(request_id)
    if row.status != '待审核':
        return jsonify(msg='该申请已经处理'), 409
    data = request.get_json() or {}
    approved = bool(data.get('approved'))
    row.status = '已通过' if approved else '已驳回'
    row.reviewed_by = captain.user_id
    row.reviewed_at = datetime.now()
    row.review_comment = (data.get('comment') or '').strip() or None
    if row.request_type == '注册':
        row.user.status = 1 if approved else 0
    else:
        row.user.status = 0 if approved else 1
    _record(captain, f'{row.request_type}申请{row.status}', 'membership_request',
            row.request_id, row.user.real_name or row.user.username, row.review_comment)
    db.session.commit()
    return jsonify(msg=f'{row.request_type}申请已{row.status}', request=row.to_dict()), 200


@governance_bp.route('/deactivation-request', methods=['POST'])
@require_auth
def request_deactivation():
    user = get_current_user()
    if _is_captain(user):
        return jsonify(msg='队长需先完成职务交接，不能直接申请注销'), 409
    existing = MembershipRequest.query.filter_by(
        user_id=user.user_id, request_type='注销', status='待审核').first()
    if existing:
        return jsonify(msg='已有待审核的注销申请'), 409
    data = request.get_json() or {}
    row = MembershipRequest(
        request_type='注销', user_id=user.user_id,
        reason=(data.get('reason') or '').strip() or None,
    )
    user.status = 3
    db.session.add(row)
    db.session.commit()
    return jsonify(msg='注销申请已提交，请等待队长审核', request=row.to_dict()), 201


@governance_bp.route('/accounts', methods=['POST'])
@require_auth
def create_account():
    captain = get_current_user()
    denied = _deny(_is_captain(captain), '仅队长可直接创建账户')
    if denied:
        return denied
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    email = (data.get('email') or '').strip()
    role_name = data.get('role_name', 'member')
    if not username or not email or len(password) < 6:
        return jsonify(msg='请填写用户名、邮箱和不少于 6 位的密码'), 400
    if role_name not in ('member', 'minister'):
        return jsonify(msg='队长账户只能通过职务交接产生'), 400
    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify(msg='用户名或邮箱已存在'), 409
    student_no = (data.get('student_no') or '').strip() or None
    if student_no and User.query.filter_by(student_no=student_no).first():
        return jsonify(msg='学号已被使用'), 409
    department_id = data.get('department_id')
    if role_name == 'minister' and not department_id:
        return jsonify(msg='创建部长账户必须指定部门'), 400
    if department_id and not db.session.get(Department, department_id):
        return jsonify(msg='部门不存在'), 404
    role = Role.query.filter_by(role_name=role_name).first()
    member_role = Role.query.filter_by(role_name='member').first()
    if role_name == 'minister':
        existing_minister = User.query.join(User.roles).filter(
            Role.role_name == 'minister', User.department_id == department_id,
            User.status == 1).first()
        if existing_minister:
            return jsonify(msg='该部门已有部长，请使用部长交接流程'), 409
    user = User(
        username=username, email=email,
        password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        real_name=(data.get('real_name') or '').strip() or None,
        student_no=student_no,
        department_id=department_id, status=1,
    )
    if member_role:
        user.roles.append(member_role)
    if role and role not in user.roles:
        user.roles.append(role)
    db.session.add(user)
    db.session.flush()
    _record(captain, '队长创建账户', 'user', user.user_id,
            user.real_name or user.username, role_name)
    db.session.commit()
    return jsonify(msg='账户已创建', user=user.to_dict()), 201


@governance_bp.route('/accounts/<int:user_id>', methods=['DELETE'])
@require_auth
def deactivate_account(user_id):
    captain = get_current_user()
    denied = _deny(_is_captain(captain), '仅队长可删除账户')
    if denied:
        return denied
    target = User.query.get_or_404(user_id)
    if target.user_id == captain.user_id or target.has_role('captain'):
        return jsonify(msg='队长账户必须先完成交接，不能直接删除'), 409
    target.status = 0
    _record(captain, '队长注销账户', 'user', target.user_id,
            target.real_name or target.username, (request.get_json(silent=True) or {}).get('reason'))
    db.session.commit()
    return jsonify(msg='账户已注销并禁止登录'), 200


@governance_bp.route('/department-applications', methods=['POST'])
@require_auth
def apply_department():
    user = get_current_user()
    if _is_captain(user):
        return jsonify(msg='队长为独立职务，不加入部门'), 409
    data = request.get_json() or {}
    department = db.session.get(Department, data.get('department_id'))
    if not department:
        return jsonify(msg='部门不存在'), 404
    if user.department_id == department.department_id:
        return jsonify(msg='你已经属于该部门'), 409
    existing = DepartmentApplication.query.filter_by(user_id=user.user_id, status='待审核').first()
    if existing:
        return jsonify(msg='已有待审核的部门申请'), 409
    row = DepartmentApplication(
        user_id=user.user_id, department_id=department.department_id,
        reason=(data.get('reason') or '').strip() or None,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(msg='部门加入申请已提交，需队长和对应部长共同通过',
                   application=row.to_dict()), 201


@governance_bp.route('/department-applications/<int:application_id>/review', methods=['PUT'])
@require_auth
def review_department(application_id):
    reviewer = get_current_user()
    row = DepartmentApplication.query.get_or_404(application_id)
    if row.status != '待审核':
        return jsonify(msg='该申请已经处理'), 409
    is_captain = _is_captain(reviewer)
    is_minister = _is_minister(reviewer, row.department_id)
    denied = _deny(is_captain or is_minister, '仅队长或对应部门部长可审核')
    if denied:
        return denied
    approved = bool((request.get_json() or {}).get('approved'))
    now = datetime.now()
    if is_captain:
        row.captain_approved = approved
        row.captain_reviewer_id = reviewer.user_id
        row.captain_reviewed_at = now
    else:
        row.minister_approved = approved
        row.minister_reviewer_id = reviewer.user_id
        row.minister_reviewed_at = now
    if not approved:
        row.status = '已驳回'
        row.completed_at = now
    elif row.captain_approved is True and row.minister_approved is True:
        row.status = '已通过'
        row.completed_at = now
        row.user.department_id = row.department_id
    _record(reviewer, '审核部门加入', 'department_application', row.application_id,
            row.user.real_name or row.user.username,
            f'{row.department.department_name} · {"通过" if approved else "驳回"}')
    db.session.commit()
    return jsonify(msg='审核结果已保存', application=row.to_dict()), 200


@governance_bp.route('/grants', methods=['POST'])
@require_auth
def create_grant():
    granter = get_current_user()
    data = request.get_json() or {}
    department_id = data.get('department_id') or granter.department_id
    denied = _deny(_is_captain(granter) or _is_minister(granter, department_id),
                   '仅队长或对应部门部长可授予临时权限')
    if denied:
        return denied
    target = db.session.get(User, data.get('user_id'))
    if (not target or target.status != 1 or target.department_id != department_id or
            target.has_role('minister') or target.has_role('captain')):
        return jsonify(msg='目标用户必须是该部门的普通社员'), 400
    try:
        expires_at = datetime.fromisoformat(str(data.get('expires_at')).replace('Z', '+00:00')).replace(tzinfo=None)
    except (TypeError, ValueError):
        return jsonify(msg='请设置有效的权限截止时间'), 400
    if expires_at <= datetime.now() or expires_at > datetime.now() + timedelta(days=90):
        return jsonify(msg='临时权限须在未来 90 天内到期'), 400
    row = TemporaryDepartmentGrant(
        user_id=target.user_id, department_id=department_id,
        granted_by=granter.user_id, expires_at=expires_at,
        reason=(data.get('reason') or '').strip() or None,
    )
    db.session.add(row)
    db.session.flush()
    _record(granter, '授予临时后台权限', 'grant', row.grant_id,
            target.real_name or target.username, f'截止：{expires_at.isoformat()}')
    db.session.commit()
    return jsonify(msg='临时后台权限已授予', grant=row.to_dict()), 201


@governance_bp.route('/grants/<int:grant_id>', methods=['DELETE'])
@require_auth
def revoke_grant(grant_id):
    reviewer = get_current_user()
    row = TemporaryDepartmentGrant.query.get_or_404(grant_id)
    denied = _deny(_is_captain(reviewer) or _is_minister(reviewer, row.department_id),
                   '无权撤销该临时权限')
    if denied:
        return denied
    row.revoked_at = datetime.now()
    db.session.commit()
    return jsonify(msg='临时权限已撤销'), 200


@governance_bp.route('/transfers', methods=['POST'])
@require_auth
def propose_transfer():
    proposer = get_current_user()
    data = request.get_json() or {}
    role_name = data.get('role_name')
    target = db.session.get(User, data.get('to_user_id'))
    if not target or target.status != 1 or target.user_id == proposer.user_id:
        return jsonify(msg='目标账户无效'), 400
    if role_name == 'captain':
        denied = _deny(_is_captain(proposer), '仅现任队长可发起队长交接')
        department_id = None
    elif role_name == 'minister':
        denied = _deny(_is_minister(proposer), '仅现任部长可发起部长交接')
        department_id = proposer.department_id
        if target.department_id != department_id:
            return jsonify(msg='部长只能交接给本部门社员'), 400
    else:
        return jsonify(msg='交接职务无效'), 400
    if denied:
        return denied
    existing = LeadershipTransfer.query.filter_by(
        role_name=role_name, department_id=department_id, status='待确认').first()
    if existing:
        return jsonify(msg='该职务已有待确认的交接申请'), 409
    row = LeadershipTransfer(
        role_name=role_name, department_id=department_id,
        from_user_id=proposer.user_id, to_user_id=target.user_id,
        note=(data.get('note') or '').strip() or None,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(msg='交接申请已发送，等待目标账户确认', transfer=row.to_dict()), 201


@governance_bp.route('/transfers/<int:transfer_id>/respond', methods=['PUT'])
@require_auth
def respond_transfer(transfer_id):
    target = get_current_user()
    row = LeadershipTransfer.query.get_or_404(transfer_id)
    if row.to_user_id != target.user_id:
        return jsonify(msg='仅交接目标本人可以确认'), 403
    if row.status != '待确认':
        return jsonify(msg='该交接已经处理'), 409
    accepted = bool((request.get_json() or {}).get('accepted'))
    row.status = '已接受' if accepted else '已拒绝'
    row.responded_at = datetime.now()
    if accepted:
        role = Role.query.filter_by(role_name=row.role_name).first()
        if role in row.from_user.roles:
            row.from_user.roles.remove(role)
        if role and role not in row.to_user.roles:
            row.to_user.roles.append(role)
        if row.role_name == 'captain':
            minister_role = Role.query.filter_by(role_name='minister').first()
            if minister_role in row.to_user.roles:
                row.to_user.roles.remove(minister_role)
            row.to_user.department_id = None
    _record(target, '确认职务交接', 'leadership_transfer', row.transfer_id,
            '队长' if row.role_name == 'captain' else '部长', row.status)
    db.session.commit()
    return jsonify(msg=f'交接申请{row.status}', transfer=row.to_dict()), 200


@governance_bp.route('/forum/posts', methods=['GET', 'POST'])
@require_auth
def forum_posts():
    user = get_current_user()
    if request.method == 'GET':
        rows = ForumPost.query.filter_by(status=1).order_by(ForumPost.created_at.desc()).limit(100).all()
        return jsonify(posts=[row.to_dict() for row in rows]), 200
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    if not title or not content:
        return jsonify(msg='标题和内容不能为空'), 400
    if len(title) > 120 or len(content) > 5000:
        return jsonify(msg='帖子内容过长'), 400
    row = ForumPost(author_id=user.user_id, title=title, content=content)
    db.session.add(row)
    db.session.commit()
    return jsonify(msg='帖子已发布', post=row.to_dict()), 201


@governance_bp.route('/forum/posts/<int:post_id>/comments', methods=['POST'])
@require_auth
def create_comment(post_id):
    user = get_current_user()
    post = ForumPost.query.filter_by(post_id=post_id, status=1).first_or_404()
    content = ((request.get_json() or {}).get('content') or '').strip()
    if not content or len(content) > 1000:
        return jsonify(msg='回复内容须在 1 到 1000 字之间'), 400
    row = ForumComment(post_id=post.post_id, author_id=user.user_id, content=content)
    db.session.add(row)
    db.session.commit()
    return jsonify(msg='回复已发布', comment=row.to_dict()), 201


@governance_bp.route('/forum/posts/<int:post_id>', methods=['DELETE'])
@require_auth
def delete_post(post_id):
    user = get_current_user()
    post = ForumPost.query.get_or_404(post_id)
    denied = _deny(post.author_id == user.user_id or _is_captain(user), '只能删除自己的帖子')
    if denied:
        return denied
    post.status = 0
    db.session.commit()
    return jsonify(msg='帖子已删除'), 200
