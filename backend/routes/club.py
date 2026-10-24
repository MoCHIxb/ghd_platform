import os
from datetime import datetime, timedelta
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request, send_from_directory
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from extensions import db
from models import (
    ActivityMedia, ActivityParticipant, ClubActivity, ClubArchive, Department,
    Equipment, EquipmentCategory, EquipmentUsage, File, OperationRecord, Role,
    SocialAccount, User,
)
from utils.auth_helper import get_current_user, require_auth


club_bp = Blueprint('club', __name__, url_prefix='/api/club')
ALLOWED_COVER_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'gif'}


def _payload():
    """同时支持 JSON 和带封面图片的 multipart/form-data。"""
    return request.form.to_dict() if request.content_type and 'multipart/form-data' in request.content_type else (request.get_json() or {})


def _save_cover(kind):
    image = request.files.get('cover')
    if not image or not image.filename:
        return None
    safe_name = secure_filename(image.filename)
    if '.' not in safe_name:
        raise ValueError('图片格式不合法')
    ext = safe_name.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED_COVER_EXTENSIONS:
        raise ValueError('仅支持 jpg、jpeg、png、webp、gif 图片')
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'covers', kind)
    os.makedirs(folder, exist_ok=True)
    filename = f'{uuid4().hex}.{ext}'
    target = os.path.join(folder, filename)
    image.save(target)
    if os.path.getsize(target) > 10 * 1024 * 1024:
        os.remove(target)
        raise ValueError('封面图片不能超过 10MB')
    return filename


@club_bp.route('/covers/<string:kind>/<path:filename>', methods=['GET'])
def get_cover(kind, filename):
    if kind not in ('activity', 'equipment'):
        return jsonify(msg='图片类型不存在'), 404
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'covers', kind)
    return send_from_directory(folder, filename)


def _parse_dt(value, required=False):
    if not value:
        if required:
            raise ValueError('缺少日期时间')
        return None
    return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)


def _is_captain(user):
    return user and (user.has_role('captain') or user.has_role('admin'))


def _is_minister(user, department_name=None):
    if not user or not user.has_role('minister'):
        return False
    return department_name is None or (user.department and user.department.department_name == department_name)


def _can_manage_activity(user, activity):
    return bool(user and (_is_captain(user) or activity.lead_instructor_id == user.user_id or
                          _is_minister(user, '教官部')))


def _deny_unless(condition, message='权限不足'):
    return None if condition else (jsonify(msg=message), 403)


def _record(user, module, action, target_type, target=None, target_name=None, detail=None):
    """在当前事务中保存统一操作时间记录。"""
    target_id = None
    if target is not None:
        target_id = getattr(target, f'{target_type}_id', None)
        if target_id is None:
            for key in ('activity_id', 'equipment_id', 'media_id', 'archive_id',
                        'usage_id', 'category_id', 'account_id', 'participant_id'):
                if hasattr(target, key):
                    target_id = getattr(target, key)
                    break
    db.session.add(OperationRecord(
        module=module, action=action, target_type=target_type,
        target_id=target_id, target_name=target_name,
        operator_id=user.user_id if user else None, detail=detail,
        occurred_at=datetime.now(),
    ))


@club_bp.route('/departments', methods=['GET'])
def departments():
    rows = Department.query.order_by(Department.sort_order).all()
    return jsonify(departments=[d.to_dict() for d in rows]), 200


@club_bp.route('/members', methods=['GET'])
@require_auth
def members():
    department_id = request.args.get('department_id', type=int)
    query = User.query.filter_by(status=1)
    if department_id:
        query = query.filter_by(department_id=department_id)
    rows = query.order_by(User.real_name, User.username).all()
    return jsonify(members=[u.to_dict() for u in rows]), 200


@club_bp.route('/overview', methods=['GET'])
@require_auth
def overview():
    now = datetime.now()
    active_borrows = EquipmentUsage.query.filter_by(status='使用中').count()
    pending_media = ActivityMedia.query.filter_by(review_status='待审阅').count()
    upcoming = ClubActivity.query.filter(ClubActivity.start_time >= now).order_by(ClubActivity.start_time).limit(4).all()
    return jsonify(
        member_count=User.query.filter_by(status=1).count(),
        activity_count=ClubActivity.query.count(),
        upcoming_count=ClubActivity.query.filter(ClubActivity.start_time >= now).count(),
        equipment_count=db.session.query(func.sum(Equipment.total_quantity)).scalar() or 0,
        active_borrows=active_borrows,
        pending_media=pending_media,
        upcoming=[a.to_dict() for a in upcoming],
    ), 200


# ── 时间中心：日程与统一操作记录 ─────────────────────────────────────────────

@club_bp.route('/time/overview', methods=['GET'])
@require_auth
def time_overview():
    now = datetime.now()
    try:
        start = _parse_dt(request.args.get('start')) or now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = _parse_dt(request.args.get('end')) or (start.replace(hour=23, minute=59, second=59) + timedelta(days=30))
    except ValueError:
        return jsonify(msg='时间范围格式错误'), 400

    events = []
    activities = ClubActivity.query.filter(
        ClubActivity.start_time >= start, ClubActivity.start_time <= end
    ).order_by(ClubActivity.start_time).all()
    for row in activities:
        events.append({
            'module': 'activity', 'event_type': '活动安排', 'target_id': row.activity_id,
            'title': row.title, 'time': row.start_time.isoformat(),
            'end_time': row.end_time.isoformat() if row.end_time else None,
            'status': row.status, 'detail': f'{row.activity_type} · {row.location or "地点待定"}',
            'is_overdue': bool(row.end_time and row.end_time < now and row.status != '已完成'),
        })

    usages = EquipmentUsage.query.filter(
        EquipmentUsage.status == '使用中', EquipmentUsage.expected_return_at.isnot(None),
        EquipmentUsage.expected_return_at >= start, EquipmentUsage.expected_return_at <= end,
    ).order_by(EquipmentUsage.expected_return_at).all()
    for row in usages:
        events.append({
            'module': 'equipment', 'event_type': '设备应归还', 'target_id': row.usage_id,
            'title': f'{row.equipment.equipment_name} × {row.quantity}',
            'time': row.expected_return_at.isoformat(), 'end_time': None,
            'status': row.status, 'detail': f'领用人：{row.user.real_name or row.user.username}',
            'is_overdue': row.expected_return_at < now,
        })

    pending_media = ActivityMedia.query.filter(
        ActivityMedia.review_status == '待审阅', ActivityMedia.submitted_at <= end
    ).order_by(ActivityMedia.submitted_at).all()
    for row in pending_media:
        if row.submitted_at >= start:
            events.append({
                'module': 'media', 'event_type': '素材待审', 'target_id': row.media_id,
                'title': row.activity.title, 'time': row.submitted_at.isoformat(),
                'end_time': None, 'status': row.review_status,
                'detail': f'提交人：{row.submitter.real_name or row.submitter.username}',
                'is_overdue': (now - row.submitted_at).days >= 3,
            })

    events.sort(key=lambda item: item['time'])
    return jsonify(
        start=start.isoformat(), end=end.isoformat(), events=events,
        activity_count=len(activities),
        return_due_count=len(usages),
        pending_media_count=len(pending_media),
        overdue_count=sum(1 for item in events if item['is_overdue']),
    ), 200


@club_bp.route('/time/records', methods=['GET'])
@require_auth
def time_records():
    module = (request.args.get('module') or '').strip()
    limit = min(max(request.args.get('limit', 50, type=int), 1), 200)
    query = OperationRecord.query
    if module:
        query = query.filter_by(module=module)
    try:
        start = _parse_dt(request.args.get('start'))
        end = _parse_dt(request.args.get('end'))
    except ValueError:
        return jsonify(msg='时间范围格式错误'), 400
    if start:
        query = query.filter(OperationRecord.occurred_at >= start)
    if end:
        query = query.filter(OperationRecord.occurred_at <= end)
    rows = query.order_by(OperationRecord.occurred_at.desc()).limit(limit).all()
    return jsonify(records=[row.to_dict() for row in rows]), 200


# ── 教官部：活动项目 ─────────────────────────────────────────────────────────

@club_bp.route('/activities', methods=['GET'])
@require_auth
def list_activities():
    status = (request.args.get('status') or '').strip()
    query = ClubActivity.query
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(ClubActivity.start_time.desc()).all()
    return jsonify(activities=[a.to_dict() for a in rows]), 200


@club_bp.route('/activities', methods=['POST'])
@require_auth
def create_activity():
    user = get_current_user()
    denied = _deny_unless(_is_captain(user) or _is_minister(user, '教官部'), '仅教官部部长或队长可开设活动')
    if denied:
        return denied
    data = _payload()
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify(msg='活动名称不能为空'), 400
    try:
        start_time = _parse_dt(data.get('start_time'), required=True)
        end_time = _parse_dt(data.get('end_time'))
    except ValueError:
        return jsonify(msg='日期时间格式错误'), 400
    lead_id = data.get('lead_instructor_id') or user.user_id
    lead = User.query.get(lead_id)
    if not lead:
        return jsonify(msg='活动主教官不存在'), 404
    try:
        cover_image = _save_cover('activity')
    except ValueError as error:
        return jsonify(msg=str(error)), 415
    activity = ClubActivity(
        title=title, activity_type=data.get('activity_type', '升旗'),
        description=data.get('description'), location=data.get('location'),
        start_time=start_time, end_time=end_time, status=data.get('status', '筹备中'),
        created_by=user.user_id, lead_instructor_id=lead.user_id,
        cover_image=cover_image,
    )
    db.session.add(activity)
    db.session.flush()
    _record(user, 'activity', '创建活动', 'activity', activity, activity.title,
            f'{activity.activity_type} · {activity.start_time.isoformat()}')
    db.session.commit()
    return jsonify(msg='活动项目已创建', activity=activity.to_dict()), 201


@club_bp.route('/activities/<int:activity_id>', methods=['GET'])
@require_auth
def activity_detail(activity_id):
    activity = ClubActivity.query.get_or_404(activity_id)
    return jsonify(activity=activity.to_dict(include_participants=True),
                   media=[m.to_dict() for m in activity.media_submissions]), 200


@club_bp.route('/activities/<int:activity_id>/transfer', methods=['PUT'])
@require_auth
def transfer_activity(activity_id):
    user = get_current_user()
    activity = ClubActivity.query.get_or_404(activity_id)
    denied = _deny_unless(_is_captain(user) or _is_minister(user, '教官部'), '仅教官部部长或队长可移交项目')
    if denied:
        return denied
    target = User.query.get((request.get_json() or {}).get('lead_instructor_id'))
    if not target or target.status != 1:
        return jsonify(msg='目标用户不存在或已停用'), 404
    activity.lead_instructor_id = target.user_id
    _record(user, 'activity', '移交主教官', 'activity', activity, activity.title,
            f'新主教官：{target.real_name or target.username}')
    db.session.commit()
    return jsonify(msg='活动主教官已移交', activity=activity.to_dict()), 200


@club_bp.route('/activities/<int:activity_id>/participants', methods=['PUT'])
@require_auth
def update_participant(activity_id):
    user = get_current_user()
    activity = ClubActivity.query.get_or_404(activity_id)
    denied = _deny_unless(_can_manage_activity(user, activity), '仅活动主教官、教官部部长或队长可登记考勤评分')
    if denied:
        return denied
    data = request.get_json() or {}
    target = User.query.get(data.get('user_id'))
    if not target:
        return jsonify(msg='社员不存在'), 404
    row = ActivityParticipant.query.filter_by(activity_id=activity_id, user_id=target.user_id).first()
    if not row:
        row = ActivityParticipant(activity_id=activity_id, user_id=target.user_id)
        db.session.add(row)
    if 'attendance_status' in data:
        row.attendance_status = data['attendance_status']
        row.checked_at = datetime.now()
    if 'score' in data:
        score = float(data['score'])
        if score < 0 or score > 100:
            return jsonify(msg='表现评分必须在 0 到 100 之间'), 400
        row.score = score
    if 'performance_comment' in data:
        row.performance_comment = data['performance_comment']
    db.session.flush()
    _record(user, 'activity', '保存考勤评分', 'participant', row,
            f'{activity.title} / {target.real_name or target.username}',
            f'{row.attendance_status} · {float(row.score) if row.score is not None else "未评分"}')
    db.session.commit()
    return jsonify(msg='考勤与表现已记录', participant=row.to_dict()), 200


@club_bp.route('/activities/<int:activity_id>/summary', methods=['PUT'])
@require_auth
def update_summary(activity_id):
    user = get_current_user()
    activity = ClubActivity.query.get_or_404(activity_id)
    denied = _deny_unless(_can_manage_activity(user, activity), '仅活动主教官可填写项目总结')
    if denied:
        return denied
    data = request.get_json() or {}
    activity.summary = (data.get('summary') or '').strip()
    if data.get('status'):
        activity.status = data['status']
    _record(user, 'activity', '保存项目总结', 'activity', activity, activity.title,
            f'项目状态：{activity.status}')
    db.session.commit()
    return jsonify(msg='项目总结已保存', activity=activity.to_dict()), 200


@club_bp.route('/activities/<int:activity_id>/media', methods=['POST'])
@require_auth
def submit_media(activity_id):
    user = get_current_user()
    activity = ClubActivity.query.get_or_404(activity_id)
    denied = _deny_unless(_can_manage_activity(user, activity), '仅项目管理人员可提交活动素材')
    if denied:
        return denied
    data = request.get_json() or {}
    media_file = File.query.get(data.get('file_id'))
    if not media_file:
        return jsonify(msg='请先上传素材文件'), 404
    row = ActivityMedia(activity_id=activity.activity_id, file_id=media_file.file_id,
                        submitter_id=user.user_id)
    db.session.add(row)
    db.session.flush()
    _record(user, 'media', '提交活动素材', 'media', row, activity.title,
            media_file.original_name)
    db.session.commit()
    return jsonify(msg='素材已提交办公室审阅', media=row.to_dict()), 201


# ── 后勤部：设备与占用 ───────────────────────────────────────────────────────

@club_bp.route('/equipment/categories', methods=['GET', 'POST'])
@require_auth
def equipment_categories():
    if request.method == 'GET':
        roots = EquipmentCategory.query.filter_by(parent_id=None).order_by(
            EquipmentCategory.sort_order, EquipmentCategory.category_id).all()
        flat = EquipmentCategory.query.order_by(EquipmentCategory.sort_order,
                                                EquipmentCategory.category_id).all()
        return jsonify(categories=[r.to_dict(include_children=True) for r in roots],
                       flat_categories=[r.to_dict() for r in flat]), 200
    user = get_current_user()
    denied = _deny_unless(_is_captain(user) or _is_minister(user, '后勤部'), '仅后勤部部长或队长可新增分类')
    if denied:
        return denied
    data = request.get_json() or {}
    name = (data.get('category_name') or '').strip()
    if not name:
        return jsonify(msg='分类名称不能为空'), 400
    parent_id = data.get('parent_id') or None
    if parent_id and not EquipmentCategory.query.get(parent_id):
        return jsonify(msg='父分类不存在'), 404
    duplicate = EquipmentCategory.query.filter_by(category_name=name, parent_id=parent_id).first()
    if duplicate:
        return jsonify(msg='同级分类名称已存在'), 409
    row = EquipmentCategory(category_name=name, description=data.get('description'),
                            parent_id=parent_id, sort_order=int(data.get('sort_order', 0)))
    db.session.add(row)
    db.session.flush()
    _record(user, 'equipment', '创建设备分类', 'category', row, row.full_name())
    db.session.commit()
    return jsonify(msg='设备分类已创建', category=row.to_dict()), 201


@club_bp.route('/equipment/categories/<int:category_id>', methods=['PUT', 'DELETE'])
@require_auth
def manage_equipment_category(category_id):
    user = get_current_user()
    denied = _deny_unless(_is_captain(user) or _is_minister(user, '后勤部'), '仅后勤部部长或队长可管理分类')
    if denied:
        return denied
    row = EquipmentCategory.query.get_or_404(category_id)
    if request.method == 'DELETE':
        if row.children or row.equipment:
            return jsonify(msg='分类下仍有子分类或设备，不能删除'), 409
        _record(user, 'equipment', '删除设备分类', 'category', row, row.full_name())
        db.session.delete(row)
        db.session.commit()
        return jsonify(msg='设备分类已删除'), 200
    data = request.get_json() or {}
    if 'category_name' in data:
        row.category_name = (data['category_name'] or '').strip() or row.category_name
    if 'description' in data:
        row.description = data['description']
    if 'sort_order' in data:
        row.sort_order = int(data['sort_order'])
    if 'parent_id' in data:
        parent_id = data['parent_id'] or None
        if parent_id == row.category_id:
            return jsonify(msg='分类不能成为自己的父分类'), 400
        row.parent_id = parent_id
    try:
        _record(user, 'equipment', '更新设备分类', 'category', row, row.full_name())
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(msg='同级分类名称已存在'), 409
    return jsonify(msg='设备分类已更新', category=row.to_dict()), 200


@club_bp.route('/equipment', methods=['GET', 'POST'])
@require_auth
def equipment_list():
    if request.method == 'GET':
        rows = Equipment.query.order_by(Equipment.equipment_name).all()
        return jsonify(equipment=[r.to_dict() for r in rows]), 200
    user = get_current_user()
    denied = _deny_unless(_is_captain(user) or _is_minister(user, '后勤部'), '仅后勤部部长或队长可登记设备')
    if denied:
        return denied
    data = _payload()
    qty = int(data.get('total_quantity', 1))
    if qty < 1:
        return jsonify(msg='设备数量至少为 1'), 400
    try:
        cover_image = _save_cover('equipment')
    except ValueError as error:
        return jsonify(msg=str(error)), 415
    row = Equipment(asset_code=(data.get('asset_code') or '').strip(),
                    equipment_name=(data.get('equipment_name') or '').strip(),
                    category_id=data.get('category_id'), total_quantity=qty,
                    available_quantity=qty, storage_location=data.get('storage_location'),
                    notes=data.get('notes'), cover_image=cover_image)
    if not row.asset_code or not row.equipment_name or not EquipmentCategory.query.get(row.category_id):
        return jsonify(msg='资产编号、设备名称和有效分类均为必填项'), 400
    db.session.add(row)
    db.session.flush()
    _record(user, 'equipment', '登记设备', 'equipment', row, row.equipment_name,
            f'资产编号：{row.asset_code} · 数量：{row.total_quantity}')
    db.session.commit()
    return jsonify(msg='设备已登记', equipment=row.to_dict()), 201


@club_bp.route('/equipment/usages', methods=['GET'])
@require_auth
def equipment_usages():
    only_active = request.args.get('active') == '1'
    query = EquipmentUsage.query
    if only_active:
        query = query.filter_by(status='使用中')
    rows = query.order_by(EquipmentUsage.borrowed_at.desc()).all()
    return jsonify(usages=[r.to_dict() for r in rows]), 200


@club_bp.route('/equipment/<int:equipment_id>/borrow', methods=['POST'])
@require_auth
def borrow_equipment(equipment_id):
    user = get_current_user()
    equipment = Equipment.query.get_or_404(equipment_id)
    data = request.get_json() or {}
    qty = int(data.get('quantity', 1))
    if qty < 1 or qty > equipment.available_quantity:
        return jsonify(msg=f'设备占用冲突：当前仅剩 {equipment.available_quantity} 件可用'), 409
    try:
        expected = _parse_dt(data.get('expected_return_at'))
    except ValueError:
        return jsonify(msg='预计归还时间格式错误'), 400
    row = EquipmentUsage(equipment_id=equipment_id, user_id=user.user_id,
                         activity_id=data.get('activity_id'), quantity=qty,
                         expected_return_at=expected, notes=data.get('notes'))
    equipment.available_quantity -= qty
    db.session.add(row)
    db.session.flush()
    _record(user, 'equipment', '领用设备', 'usage', row, equipment.equipment_name,
            f'数量：{qty} · 预计归还：{expected.isoformat() if expected else "未设置"}')
    db.session.commit()
    return jsonify(msg='设备领用成功', usage=row.to_dict(), equipment=equipment.to_dict()), 201


@club_bp.route('/equipment/usages/<int:usage_id>/return', methods=['PUT'])
@require_auth
def return_equipment(usage_id):
    user = get_current_user()
    row = EquipmentUsage.query.get_or_404(usage_id)
    denied = _deny_unless(row.user_id == user.user_id or _is_captain(user) or _is_minister(user, '后勤部'), '无权归还该设备')
    if denied:
        return denied
    if row.status != '使用中':
        return jsonify(msg='该记录已经归还'), 409
    row.status = '已归还'
    row.returned_at = datetime.now()
    row.equipment.available_quantity = min(row.equipment.total_quantity,
                                           row.equipment.available_quantity + row.quantity)
    _record(user, 'equipment', '归还设备', 'usage', row, row.equipment.equipment_name,
            f'归还数量：{row.quantity}')
    db.session.commit()
    return jsonify(msg='设备已归还', usage=row.to_dict()), 200


# ── 综合办公室：社媒、档案与素材审阅 ─────────────────────────────────────────

@club_bp.route('/office/socials', methods=['GET', 'POST'])
@require_auth
def socials():
    if request.method == 'GET':
        rows = SocialAccount.query.filter_by(status=1).all()
        return jsonify(accounts=[r.to_dict() for r in rows]), 200
    user = get_current_user()
    denied = _deny_unless(_is_captain(user) or _is_minister(user, '综合办公室'), '仅综合办公室部长或队长可维护社媒账号')
    if denied:
        return denied
    data = request.get_json() or {}
    row = SocialAccount(platform=data.get('platform'), account_name=data.get('account_name'),
                        link_url=data.get('link_url'), icon=data.get('icon'))
    if not row.platform or not row.account_name or not row.link_url:
        return jsonify(msg='平台、账号名称和链接均不能为空'), 400
    db.session.add(row)
    db.session.flush()
    _record(user, 'office', '添加社媒账号', 'account', row, row.platform,
            row.account_name)
    db.session.commit()
    return jsonify(msg='社媒账号已添加', account=row.to_dict()), 201


@club_bp.route('/office/archives', methods=['GET', 'POST'])
@require_auth
def archives():
    if request.method == 'GET':
        rows = ClubArchive.query.order_by(ClubArchive.archived_at.desc()).all()
        return jsonify(archives=[r.to_dict() for r in rows]), 200
    user = get_current_user()
    denied = _deny_unless(_is_captain(user) or _is_minister(user, '综合办公室'), '仅综合办公室部长或队长可归档文件')
    if denied:
        return denied
    data = request.get_json() or {}
    linked_file = File.query.get(data.get('file_id'))
    if not linked_file:
        return jsonify(msg='请先上传需要归档的文件'), 404
    row = ClubArchive(title=(data.get('title') or '').strip(),
                      archive_type=data.get('archive_type', '其他'), file_id=linked_file.file_id,
                      owner_id=user.user_id, description=data.get('description'))
    if not row.title:
        return jsonify(msg='档案标题不能为空'), 400
    db.session.add(row)
    db.session.flush()
    _record(user, 'archive', '保存文件档案', 'archive', row, row.title,
            row.archive_type)
    db.session.commit()
    return jsonify(msg='文件已归档', archive=row.to_dict()), 201


@club_bp.route('/office/media', methods=['GET'])
@require_auth
def review_queue():
    rows = ActivityMedia.query.order_by(ActivityMedia.submitted_at.desc()).all()
    return jsonify(media=[r.to_dict() for r in rows]), 200


@club_bp.route('/office/media/<int:media_id>/review', methods=['PUT'])
@require_auth
def review_media(media_id):
    user = get_current_user()
    denied = _deny_unless(_is_captain(user) or _is_minister(user, '综合办公室'), '仅综合办公室部长或队长可审阅素材')
    if denied:
        return denied
    data = request.get_json() or {}
    status = data.get('review_status')
    if status not in ('已通过', '需修改', '已归档'):
        return jsonify(msg='审阅状态无效'), 400
    row = ActivityMedia.query.get_or_404(media_id)
    row.review_status = status
    row.review_comment = data.get('review_comment')
    row.reviewer_id = user.user_id
    row.reviewed_at = datetime.now()
    _record(user, 'media', '审阅活动素材', 'media', row, row.activity.title,
            f'{status} · {row.review_comment or "无审阅意见"}')
    db.session.commit()
    return jsonify(msg='素材审阅结果已保存', media=row.to_dict()), 200
