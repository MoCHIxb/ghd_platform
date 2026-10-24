import os
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file, current_app
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.exc import SQLAlchemyError
from extensions import db
from models import File, Tag, Category, FilePermission, User
from utils.auth_helper import require_auth, get_current_user, check_file_access, log_access
from utils.file_helper import allowed_file, save_uploaded_file, delete_file_from_disk

files_bp = Blueprint('files', __name__, url_prefix='/api/files')


def _get_or_create_category(name: str, parent_id=None):
    q = Category.query.filter_by(category_name=name, parent_id=parent_id)
    cat = q.first()
    if cat:
        return cat
    cat = Category(category_name=name, parent_id=parent_id, sort_order=0)
    db.session.add(cat)
    db.session.flush()
    return cat


def _apply_base_media_category(media_file: File, file_type: str):
    """仅按文件类型补充基础分类：audio->音频，video->视频。"""
    if file_type not in ('audio', 'video'):
        return

    base_name = '音频' if file_type == 'audio' else '视频'
    base_cat = _get_or_create_category(base_name, None)
    if all(c.category_id != base_cat.category_id for c in media_file.categories):
        media_file.categories.append(base_cat)


def _base_category_name(file_type: str):
    if file_type == 'audio':
        return '音频'
    if file_type == 'video':
        return '视频'
    return None


def _get_allowed_child_category_ids(file_type: str):
    """返回基础分类下可手动选择的子分类ID集合（仅一级子分类）。"""
    base_name = _base_category_name(file_type)
    if not base_name:
        return set()

    base_cat = Category.query.filter_by(category_name=base_name, parent_id=None).first()
    if not base_cat:
        return set()

    rows = Category.query.with_entities(Category.category_id).filter_by(parent_id=base_cat.category_id).all()
    return {row[0] for row in rows}


@files_bp.route('', methods=['GET'])
def list_files():
    """公开文件列表，支持搜索、分类过滤、标签过滤、分页"""
    page       = request.args.get('page', 1, type=int)
    per_page   = request.args.get('per_page', 20, type=int)
    keyword    = request.args.get('keyword', '').strip()
    file_type  = request.args.get('file_type', '').strip()   # audio / video
    category_id = request.args.get('category_id', type=int)
    tag_id     = request.args.get('tag_id', type=int)
    sort_by    = request.args.get('sort_by', 'upload_time')   # upload_time/download_count/file_size
    order      = request.args.get('order', 'desc')

    query = File.query.filter_by(status=1, visibility=1)

    if keyword:
        query = query.filter(
            (File.original_name.like(f'%{keyword}%')) | (File.description.like(f'%{keyword}%'))
        )
    if file_type in ('audio', 'video'):
        query = query.filter_by(file_type=file_type)
    if category_id:
        cat = Category.query.get(category_id)
        if cat:
            query = query.filter(File.categories.contains(cat))
    if tag_id:
        tag = Tag.query.get(tag_id)
        if tag:
            query = query.filter(File.tags.contains(tag))

    sort_col = {
        'download_count': File.download_count,
        'file_size':      File.file_size,
        'view_count':     File.view_count,
    }.get(sort_by, File.upload_time)
    query = query.order_by(sort_col.desc() if order == 'desc' else sort_col.asc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(
        files=[f.to_dict() for f in pagination.items],
        total=pagination.total,
        page=page,
        pages=pagination.pages,
    ), 200


@files_bp.route('/stats/overview', methods=['GET'])
def public_overview_stats():
    """首页公开统计：公开文件数、私有文件数、用户总数。"""
    public_count = File.query.filter_by(status=1, visibility=1).count()
    # 私有统计口径：私有(0) + 授权可见(2)
    private_count = File.query.filter(
        File.status == 1,
        File.visibility.in_([0, 2]),
    ).count()
    user_count = User.query.count()
    return jsonify(
        public_file_count=public_count,
        private_file_count=private_count,
        user_count=user_count,
    ), 200


@files_bp.route('/my', methods=['GET'])
@require_auth
def my_files():
    """当前用户上传的全部文件"""
    user = get_current_user()
    page     = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    pagination = (File.query
                  .filter_by(uploader_id=user.user_id, status=1)
                  .order_by(File.upload_time.desc())
                  .paginate(page=page, per_page=per_page, error_out=False))
    return jsonify(
        files=[f.to_dict() for f in pagination.items],
        total=pagination.total,
        page=page,
        pages=pagination.pages,
    ), 200


@files_bp.route('/upload', methods=['POST'])
@require_auth
def upload_file():
    user = get_current_user()
    if 'file' not in request.files:
        return jsonify(msg='未找到文件字段'), 400

    file_storage = request.files['file']
    if not file_storage or not file_storage.filename:
        return jsonify(msg='未选择文件'), 400
    if not allowed_file(file_storage.filename):
        return jsonify(msg='不支持的文件格式'), 415

    try:
        info = save_uploaded_file(file_storage, current_app.config['UPLOAD_FOLDER'])
    except Exception:
        current_app.logger.exception('保存上传文件失败')
        return jsonify(msg='保存文件失败，请稍后重试'), 500

    try:
        visibility = int(request.form.get('visibility', 1))
    except (TypeError, ValueError):
        delete_file_from_disk(info['storage_path'])
        return jsonify(msg='visibility 参数格式错误'), 400
    if visibility not in (0, 1, 2):
        delete_file_from_disk(info['storage_path'])
        return jsonify(msg='visibility 参数必须是 0/1/2'), 400

    description = request.form.get('description', '').strip()

    try:
        media_file = File(
            filename=info['filename'],
            original_name=info['original_name'],
            file_type=info['file_type'],
            file_ext=info['file_ext'],
            file_size=info['file_size'],
            storage_path=info['storage_path'],
            uploader_id=user.user_id,
            visibility=visibility,
            description=description,
        )
        db.session.add(media_file)
        db.session.flush()  # 获取 file_id

        # 处理手动分类（仅允许当前基础分类下的子分类）
        allowed_child_ids = _get_allowed_child_category_ids(info['file_type'])
        category_ids = request.form.getlist('category_ids')
        for cid in category_ids:
            try:
                cid_int = int(cid)
            except (TypeError, ValueError):
                continue
            if cid_int not in allowed_child_ids:
                continue
            cat = Category.query.get(cid_int)
            if cat and all(c.category_id != cat.category_id for c in media_file.categories):
                media_file.categories.append(cat)

        # 处理标签（逗号分隔字符串）
        tag_names = [t.strip() for t in request.form.get('tags', '').split(',') if t.strip()]
        for tag_name in tag_names:
            tag = Tag.query.filter_by(tag_name=tag_name).first()
            if not tag:
                tag = Tag(tag_name=tag_name)
                db.session.add(tag)
                db.session.flush()
            media_file.tags.append(tag)

        # 自动补充基础媒体分类
        _apply_base_media_category(media_file, info['file_type'])

        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        delete_file_from_disk(info['storage_path'])
        current_app.logger.exception('上传元数据入库失败')
        return jsonify(msg='上传失败，数据库写入异常'), 500
    except Exception:
        db.session.rollback()
        delete_file_from_disk(info['storage_path'])
        current_app.logger.exception('上传处理失败')
        return jsonify(msg='上传失败，服务器内部错误'), 500

    log_access(media_file.file_id, user.user_id, 'upload')
    return jsonify(msg='上传成功', file=media_file.to_dict()), 201


@files_bp.route('/<int:fid>', methods=['GET'])
def get_file(fid):
    """获取文件详情，需要满足权限要求"""
    file = File.query.get_or_404(fid)
    user = get_current_user()
    if not check_file_access(file, user, 'read'):
        return jsonify(msg='无权访问该文件'), 403
    return jsonify(file=file.to_dict()), 200


@files_bp.route('/<int:fid>', methods=['PUT'])
@require_auth
def update_file(fid):
    user = get_current_user()
    file = File.query.get_or_404(fid)
    if file.status != 1:
        return jsonify(msg='文件不存在'), 404
    if file.uploader_id != user.user_id and not user.has_role('admin'):
        return jsonify(msg='无权修改此文件'), 403

    data = request.get_json() or {}
    if 'original_name' in data:
        file.original_name = data['original_name'].strip() or file.original_name
    if 'description' in data:
        file.description = data['description']
    if 'visibility' in data:
        file.visibility = int(data['visibility'])
    if 'cover_url' in data:
        file.cover_url = data['cover_url']

    # 更新手动分类
    if 'category_ids' in data:
        file.categories.clear()
        allowed_child_ids = _get_allowed_child_category_ids(file.file_type)
        for cid in data['category_ids']:
            try:
                cid_int = int(cid)
            except (TypeError, ValueError):
                cid_int = None
            if cid_int is None or cid_int not in allowed_child_ids:
                continue
            cat = Category.query.get(cid_int)
            if cat:
                file.categories.append(cat)

        # 手动分类更新后，仍补充基础媒体分类
        _apply_base_media_category(file, file.file_type)

    # 更新标签
    if 'tags' in data:
        file.tags.clear()
        for tag_name in data['tags']:
            tag_name = tag_name.strip()
            if not tag_name:
                continue
            tag = Tag.query.filter_by(tag_name=tag_name).first()
            if not tag:
                tag = Tag(tag_name=tag_name)
                db.session.add(tag)
                db.session.flush()
            file.tags.append(tag)

    db.session.commit()
    return jsonify(msg='文件信息已更新', file=file.to_dict()), 200


@files_bp.route('/<int:fid>', methods=['DELETE'])
@require_auth
def delete_file(fid):
    user = get_current_user()
    file = File.query.get_or_404(fid)
    if file.uploader_id != user.user_id and not user.has_role('admin'):
        return jsonify(msg='无权删除此文件'), 403
    file.status = 0   # 逻辑删除
    db.session.commit()
    return jsonify(msg='文件已删除'), 200


@files_bp.route('/<int:fid>/download', methods=['GET'])
def download_file(fid):
    file = File.query.get_or_404(fid)
    user = get_current_user()
    if not check_file_access(file, user, 'download'):
        return jsonify(msg='无权下载该文件'), 403
    if not os.path.exists(file.storage_path):
        return jsonify(msg='文件已丢失，请联系管理员'), 500

    file.download_count += 1
    db.session.commit()
    log_access(file.file_id, user.user_id if user else None, 'download')

    return send_file(
        file.storage_path,
        as_attachment=True,
        download_name=file.original_name,
    )


@files_bp.route('/<int:fid>/stream', methods=['GET'])
def stream_file(fid):
    """支持 Range 请求的文件流（用于在线播放）"""
    file = File.query.get_or_404(fid)
    user = get_current_user()
    if not check_file_access(file, user, 'read'):
        return jsonify(msg='无权访问该文件'), 403
    if not os.path.exists(file.storage_path):
        return jsonify(msg='文件已丢失'), 500

    file.view_count += 1
    db.session.commit()
    log_access(file.file_id, user.user_id if user else None, 'view')

    mime_map = {
        'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'flac': 'audio/flac',
        'aac': 'audio/aac',  'ogg': 'audio/ogg', 'm4a': 'audio/mp4',
        'mp4': 'video/mp4',  'webm': 'video/webm', 'mkv': 'video/x-matroska',
        'avi': 'video/x-msvideo', 'mov': 'video/quicktime',
    }
    mime = mime_map.get(file.file_ext.lower(), 'application/octet-stream')

    range_header = request.headers.get('Range')
    file_size = os.path.getsize(file.storage_path)

    if range_header:
        # 解析 Range: bytes=start-end
        byte_range = range_header.strip().replace('bytes=', '')
        parts = byte_range.split('-')
        start = int(parts[0]) if parts[0] else 0
        end   = int(parts[1]) if parts[1] else file_size - 1
        end   = min(end, file_size - 1)
        length = end - start + 1

        def generate_chunk():
            with open(file.storage_path, 'rb') as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk_size = min(65536, remaining)
                    data = f.read(chunk_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        from flask import Response
        resp = Response(
            generate_chunk(),
            206,
            mimetype=mime,
            direct_passthrough=True,
        )
        resp.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
        resp.headers['Accept-Ranges'] = 'bytes'
        resp.headers['Content-Length'] = str(length)
        return resp

    return send_file(file.storage_path, mimetype=mime)


# ── 文件级权限管理 ────────────────────────────────────────────────────────────

@files_bp.route('/<int:fid>/permissions', methods=['GET'])
@require_auth
def get_file_permissions(fid):
    user = get_current_user()
    file = File.query.get_or_404(fid)
    if file.uploader_id != user.user_id and not user.has_role('admin'):
        return jsonify(msg='无权查看此文件的授权列表'), 403
    return jsonify(permissions=[p.to_dict() for p in file.permissions]), 200


@files_bp.route('/<int:fid>/permissions', methods=['POST'])
@require_auth
def add_file_permission(fid):
    from models import User as UserModel
    user = get_current_user()
    file = File.query.get_or_404(fid)
    if file.uploader_id != user.user_id and not user.has_role('admin'):
        return jsonify(msg='无权修改此文件的授权'), 403

    data = request.get_json() or {}
    target_uid = data.get('user_id')
    perm_type  = data.get('permission_type', 'read')

    if perm_type not in ('read', 'download'):
        return jsonify(msg='permission_type 必须为 read 或 download'), 400

    target_user = UserModel.query.get(target_uid)
    if not target_user:
        return jsonify(msg='目标用户不存在'), 404

    expire_at = None
    if data.get('expire_at'):
        try:
            expire_at = datetime.fromisoformat(data['expire_at'])
        except ValueError:
            return jsonify(msg='expire_at 格式错误'), 400

    fp = FilePermission.query.filter_by(file_id=fid, user_id=target_uid).first()
    if fp:
        fp.permission_type = perm_type
        fp.expire_at = expire_at
        fp.granted_at = datetime.utcnow()
    else:
        fp = FilePermission(
            file_id=fid,
            user_id=target_uid,
            permission_type=perm_type,
            expire_at=expire_at,
        )
        db.session.add(fp)
    db.session.commit()
    return jsonify(msg='授权已设置', permission=fp.to_dict()), 200


@files_bp.route('/<int:fid>/permissions/<int:fpid>', methods=['DELETE'])
@require_auth
def remove_file_permission(fid, fpid):
    user = get_current_user()
    file = File.query.get_or_404(fid)
    if file.uploader_id != user.user_id and not user.has_role('admin'):
        return jsonify(msg='无权操作'), 403
    fp = FilePermission.query.filter_by(fp_id=fpid, file_id=fid).first_or_404()
    db.session.delete(fp)
    db.session.commit()
    return jsonify(msg='授权已撤销'), 200
