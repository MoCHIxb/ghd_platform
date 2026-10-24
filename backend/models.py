from datetime import datetime
from extensions import db


# ── 多对多关联中间表 ───────────────────────────────────────────────────────────

user_role_table = db.Table(
    'user_role',
    db.Column('user_id', db.Integer, db.ForeignKey('user.user_id', ondelete='CASCADE'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('role.role_id', ondelete='CASCADE'), primary_key=True),
    db.Column('assigned_at', db.DateTime, default=datetime.utcnow),
)

role_permission_table = db.Table(
    'role_permission',
    db.Column('role_id', db.Integer, db.ForeignKey('role.role_id', ondelete='CASCADE'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permission.permission_id', ondelete='CASCADE'), primary_key=True),
)

file_category_table = db.Table(
    'file_category',
    db.Column('file_id', db.Integer, db.ForeignKey('file.file_id', ondelete='CASCADE'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('category.category_id', ondelete='CASCADE'), primary_key=True),
)

file_tag_table = db.Table(
    'file_tag',
    db.Column('file_id', db.Integer, db.ForeignKey('file.file_id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.tag_id', ondelete='CASCADE'), primary_key=True),
)


# ── 实体表 ───────────────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = 'user'

    user_id      = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username     = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email        = db.Column(db.String(100), unique=True, nullable=False)
    phone        = db.Column(db.String(20))
    avatar_url   = db.Column(db.String(255))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    last_login   = db.Column(db.DateTime)
    status       = db.Column(db.SmallInteger, default=1)   # 0=禁用 1=正常
    real_name    = db.Column(db.String(50))
    student_no   = db.Column(db.String(30), unique=True)
    department_id = db.Column(db.Integer, db.ForeignKey('department.department_id', ondelete='SET NULL'))

    roles            = db.relationship('Role', secondary=user_role_table, back_populates='users', lazy='select')
    files            = db.relationship('File', back_populates='uploader', lazy='dynamic')
    file_permissions = db.relationship('FilePermission', back_populates='user', lazy='dynamic')
    shares           = db.relationship('Share', back_populates='sharer', lazy='dynamic')
    access_logs      = db.relationship('AccessLog', back_populates='user', lazy='dynamic')
    department       = db.relationship('Department', back_populates='members')

    def has_role(self, role_name: str) -> bool:
        names = {r.role_name for r in self.roles}
        # 队长兼容通用管理接口中的管理员权限判断。
        if role_name == 'admin' and 'captain' in names:
            return True
        return role_name in names

    def to_dict(self):
        return {
            'user_id':    self.user_id,
            'username':   self.username,
            'email':      self.email,
            'phone':      self.phone,
            'avatar_url': self.avatar_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'status':     self.status,
            'roles':      [r.role_name for r in self.roles],
            'real_name':  self.real_name,
            'student_no': self.student_no,
            'department_id': self.department_id,
            'department': self.department.department_name if self.department else None,
        }


class Role(db.Model):
    __tablename__ = 'role'

    role_id     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    role_name   = db.Column(db.String(30), unique=True, nullable=False)
    description = db.Column(db.String(100))

    users       = db.relationship('User', secondary=user_role_table, back_populates='roles')
    permissions = db.relationship('Permission', secondary=role_permission_table, back_populates='roles')

    def to_dict(self):
        return {'role_id': self.role_id, 'role_name': self.role_name, 'description': self.description}


class Permission(db.Model):
    __tablename__ = 'permission'

    permission_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    permission_name = db.Column(db.String(50), unique=True, nullable=False)
    resource_type   = db.Column(db.String(30), nullable=False)
    action          = db.Column(db.String(20), nullable=False)
    description     = db.Column(db.String(100))

    roles = db.relationship('Role', secondary=role_permission_table, back_populates='permissions')


class Department(db.Model):
    """国护队内设部门。"""
    __tablename__ = 'department'

    department_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    department_name = db.Column(db.String(30), unique=True, nullable=False)
    description = db.Column(db.String(255))
    sort_order = db.Column(db.Integer, default=0)

    members = db.relationship('User', back_populates='department')

    def to_dict(self):
        return {
            'department_id': self.department_id,
            'department_name': self.department_name,
            'description': self.description,
            'member_count': len(self.members),
        }


class File(db.Model):
    __tablename__ = 'file'

    file_id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    filename      = db.Column(db.String(255), nullable=False)          # UUID存储名
    original_name = db.Column(db.String(255), nullable=False)          # 原始文件名
    file_type     = db.Column(db.String(20), nullable=False)           # audio/video/image/document
    file_ext      = db.Column(db.String(10), nullable=False)
    file_size     = db.Column(db.BigInteger, nullable=False)
    storage_path  = db.Column(db.String(500), nullable=False)
    cover_url     = db.Column(db.String(500))
    description   = db.Column(db.Text)
    uploader_id   = db.Column(db.Integer, db.ForeignKey('user.user_id', ondelete='CASCADE'), nullable=False)
    upload_time   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    visibility    = db.Column(db.SmallInteger, default=1)  # 0=私有 1=公开 2=授权可见
    status        = db.Column(db.SmallInteger, default=1)  # 0=已删除 1=正常
    download_count = db.Column(db.Integer, default=0)
    view_count    = db.Column(db.Integer, default=0)

    uploader    = db.relationship('User', back_populates='files')
    categories  = db.relationship('Category', secondary=file_category_table, back_populates='files')
    tags        = db.relationship('Tag', secondary=file_tag_table, back_populates='files')
    permissions = db.relationship('FilePermission', back_populates='file', cascade='all, delete-orphan')
    shares      = db.relationship('Share', back_populates='file', cascade='all, delete-orphan')
    access_logs = db.relationship('AccessLog', back_populates='file', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'file_id':       self.file_id,
            'original_name': self.original_name,
            'file_type':     self.file_type,
            'file_ext':      self.file_ext,
            'file_size':     self.file_size,
            'cover_url':     self.cover_url,
            'description':   self.description,
            'uploader_id':   self.uploader_id,
            'uploader_name': self.uploader.username if self.uploader else None,
            'upload_time':   self.upload_time.isoformat() if self.upload_time else None,
            'updated_at':    self.updated_at.isoformat() if self.updated_at else None,
            'visibility':    self.visibility,
            'status':        self.status,
            'download_count': self.download_count,
            'view_count':    self.view_count,
            'categories':    [{'id': c.category_id, 'name': c.category_name} for c in self.categories],
            'tags':          [{'id': t.tag_id, 'name': t.tag_name} for t in self.tags],
        }


class Category(db.Model):
    __tablename__ = 'category'

    category_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    category_name = db.Column(db.String(50), nullable=False)
    parent_id     = db.Column(db.Integer, db.ForeignKey('category.category_id', ondelete='SET NULL'), nullable=True)
    sort_order    = db.Column(db.Integer, default=0)

    children = db.relationship('Category', backref=db.backref('parent', remote_side='Category.category_id'), lazy='select')
    files    = db.relationship('File', secondary=file_category_table, back_populates='categories')

    def to_dict(self, include_children=False):
        d = {
            'category_id':   self.category_id,
            'category_name': self.category_name,
            'parent_id':     self.parent_id,
            'sort_order':    self.sort_order,
        }
        if include_children:
            d['children'] = [c.to_dict(include_children=True)
                             for c in sorted(self.children, key=lambda x: x.sort_order)]
        return d


class Tag(db.Model):
    __tablename__ = 'tag'

    tag_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tag_name = db.Column(db.String(30), unique=True, nullable=False)

    files = db.relationship('File', secondary=file_tag_table, back_populates='tags')

    def to_dict(self):
        return {'tag_id': self.tag_id, 'tag_name': self.tag_name}


class FilePermission(db.Model):
    __tablename__ = 'file_permission'
    __table_args__ = (db.UniqueConstraint('file_id', 'user_id', name='uq_file_user'),)

    fp_id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    file_id         = db.Column(db.Integer, db.ForeignKey('file.file_id', ondelete='CASCADE'), nullable=False)
    user_id         = db.Column(db.Integer, db.ForeignKey('user.user_id', ondelete='CASCADE'), nullable=False)
    permission_type = db.Column(db.String(20), nullable=False)  # read / download
    granted_at      = db.Column(db.DateTime, default=datetime.utcnow)
    expire_at       = db.Column(db.DateTime, nullable=True)     # NULL = 永久

    file = db.relationship('File', back_populates='permissions')
    user = db.relationship('User', back_populates='file_permissions')

    def is_valid(self) -> bool:
        if self.expire_at is None:
            return True
        return datetime.utcnow() < self.expire_at

    def to_dict(self):
        return {
            'fp_id':           self.fp_id,
            'file_id':         self.file_id,
            'user_id':         self.user_id,
            'username':        self.user.username if self.user else None,
            'permission_type': self.permission_type,
            'granted_at':      self.granted_at.isoformat() if self.granted_at else None,
            'expire_at':       self.expire_at.isoformat() if self.expire_at else None,
        }


class Share(db.Model):
    __tablename__ = 'share'

    share_id     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    file_id      = db.Column(db.Integer, db.ForeignKey('file.file_id', ondelete='CASCADE'), nullable=False)
    sharer_id    = db.Column(db.Integer, db.ForeignKey('user.user_id', ondelete='CASCADE'), nullable=False)
    share_code   = db.Column(db.String(10), unique=True, nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    expire_at    = db.Column(db.DateTime, nullable=True)    # NULL = 永久
    access_limit = db.Column(db.Integer, default=0)         # 0 = 不限
    access_count = db.Column(db.Integer, default=0)
    status       = db.Column(db.SmallInteger, default=1)    # 0=已吊销 1=有效

    file   = db.relationship('File', back_populates='shares')
    sharer = db.relationship('User', back_populates='shares')

    def is_valid(self) -> bool:
        if self.status != 1:
            return False
        if self.expire_at and datetime.utcnow() > self.expire_at:
            return False
        if self.access_limit > 0 and self.access_count >= self.access_limit:
            return False
        return True

    def to_dict(self):
        return {
            'share_id':     self.share_id,
            'file_id':      self.file_id,
            'file_name':    self.file.original_name if self.file else None,
            'file_type':    self.file.file_type if self.file else None,
            'sharer_id':    self.sharer_id,
            'sharer_name':  self.sharer.username if self.sharer else None,
            'share_code':   self.share_code,
            'created_at':   self.created_at.isoformat() if self.created_at else None,
            'expire_at':    self.expire_at.isoformat() if self.expire_at else None,
            'access_limit': self.access_limit,
            'access_count': self.access_count,
            'status':       self.status,
        }


class AccessLog(db.Model):
    __tablename__ = 'access_log'

    log_id      = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.user_id', ondelete='SET NULL'), nullable=True)
    file_id     = db.Column(db.Integer, db.ForeignKey('file.file_id', ondelete='CASCADE'), nullable=False)
    action      = db.Column(db.String(20), nullable=False)  # view/download/share/upload
    access_time = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address  = db.Column(db.String(45))
    user_agent  = db.Column(db.String(200))

    user = db.relationship('User', back_populates='access_logs')
    file = db.relationship('File', back_populates='access_logs')

    def to_dict(self):
        return {
            'log_id':      self.log_id,
            'user_id':     self.user_id,
            'username':    self.user.username if self.user else '匿名用户',
            'file_id':     self.file_id,
            'file_name':   self.file.original_name if self.file else None,
            'action':      self.action,
            'access_time': self.access_time.isoformat() if self.access_time else None,
            'ip_address':  self.ip_address,
            'user_agent':  self.user_agent,
        }


# ── 国旗护卫队业务实体 ────────────────────────────────────────────────────────

class ClubActivity(db.Model):
    __tablename__ = 'club_activity'

    activity_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(120), nullable=False)
    activity_type = db.Column(db.String(20), nullable=False)  # 升旗 / 出旗 / 训练 / 其他
    description = db.Column(db.Text)
    location = db.Column(db.String(120))
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='筹备中')
    created_by = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    lead_instructor_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    summary = db.Column(db.Text)
    cover_image = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by])
    lead_instructor = db.relationship('User', foreign_keys=[lead_instructor_id])
    participants = db.relationship('ActivityParticipant', back_populates='activity', cascade='all, delete-orphan')
    media_submissions = db.relationship('ActivityMedia', back_populates='activity', cascade='all, delete-orphan')

    def to_dict(self, include_participants=False):
        data = {
            'activity_id': self.activity_id, 'title': self.title,
            'activity_type': self.activity_type, 'description': self.description,
            'location': self.location,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'status': self.status, 'created_by': self.created_by,
            'lead_instructor_id': self.lead_instructor_id,
            'lead_instructor_name': (self.lead_instructor.real_name or self.lead_instructor.username) if self.lead_instructor else None,
            'summary': self.summary, 'participant_count': len(self.participants),
            'media_count': len(self.media_submissions),
            'cover_url': f'/api/club/covers/activity/{self.cover_image}' if self.cover_image else None,
        }
        if include_participants:
            data['participants'] = [p.to_dict() for p in self.participants]
        return data


class ActivityParticipant(db.Model):
    __tablename__ = 'activity_participant'
    __table_args__ = (db.UniqueConstraint('activity_id', 'user_id', name='uq_activity_user'),)

    participant_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('club_activity.activity_id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.user_id', ondelete='CASCADE'), nullable=False)
    attendance_status = db.Column(db.String(20), default='待签到')
    score = db.Column(db.Numeric(5, 2))
    performance_comment = db.Column(db.String(500))
    checked_at = db.Column(db.DateTime)

    activity = db.relationship('ClubActivity', back_populates='participants')
    user = db.relationship('User')

    def to_dict(self):
        return {
            'participant_id': self.participant_id, 'user_id': self.user_id,
            'name': (self.user.real_name or self.user.username) if self.user else None,
            'attendance_status': self.attendance_status,
            'score': float(self.score) if self.score is not None else None,
            'performance_comment': self.performance_comment,
            'checked_at': self.checked_at.isoformat() if self.checked_at else None,
        }


class ActivityMedia(db.Model):
    __tablename__ = 'activity_media'

    media_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('club_activity.activity_id', ondelete='CASCADE'), nullable=False)
    file_id = db.Column(db.Integer, db.ForeignKey('file.file_id', ondelete='CASCADE'), nullable=False)
    submitter_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    review_status = db.Column(db.String(20), default='待审阅')
    review_comment = db.Column(db.String(500))
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.user_id'))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)

    activity = db.relationship('ClubActivity', back_populates='media_submissions')
    file = db.relationship('File')
    submitter = db.relationship('User', foreign_keys=[submitter_id])
    reviewer = db.relationship('User', foreign_keys=[reviewer_id])

    def to_dict(self):
        return {
            'media_id': self.media_id, 'activity_id': self.activity_id,
            'activity_title': self.activity.title if self.activity else None,
            'file': self.file.to_dict() if self.file else None,
            'submitter_name': (self.submitter.real_name or self.submitter.username) if self.submitter else None,
            'review_status': self.review_status, 'review_comment': self.review_comment,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
        }


class EquipmentCategory(db.Model):
    __tablename__ = 'equipment_category'
    category_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    category_name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255))
    parent_id = db.Column(db.Integer, db.ForeignKey('equipment_category.category_id', ondelete='RESTRICT'))
    sort_order = db.Column(db.Integer, default=0)
    __table_args__ = (db.UniqueConstraint('category_name', 'parent_id', name='uq_equipment_category_parent'),)

    children = db.relationship('EquipmentCategory', backref=db.backref('parent', remote_side='EquipmentCategory.category_id'), lazy='select')
    equipment = db.relationship('Equipment', back_populates='category')

    def full_name(self):
        names, node = [], self
        while node:
            names.append(node.category_name)
            node = node.parent
        return ' / '.join(reversed(names))

    def to_dict(self, include_children=False):
        data = {'category_id': self.category_id, 'category_name': self.category_name,
                'description': self.description, 'parent_id': self.parent_id,
                'sort_order': self.sort_order, 'full_name': self.full_name(),
                'equipment_count': len(self.equipment)}
        if include_children:
            data['children'] = [c.to_dict(include_children=True)
                                for c in sorted(self.children, key=lambda x: (x.sort_order, x.category_id))]
        return data


class Equipment(db.Model):
    __tablename__ = 'equipment'
    equipment_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    asset_code = db.Column(db.String(40), unique=True, nullable=False)
    equipment_name = db.Column(db.String(100), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('equipment_category.category_id'), nullable=False)
    total_quantity = db.Column(db.Integer, nullable=False, default=1)
    available_quantity = db.Column(db.Integer, nullable=False, default=1)
    storage_location = db.Column(db.String(120))
    status = db.Column(db.String(20), default='正常')
    notes = db.Column(db.String(500))
    cover_image = db.Column(db.String(255))

    category = db.relationship('EquipmentCategory', back_populates='equipment')
    usage_records = db.relationship('EquipmentUsage', back_populates='equipment')

    def to_dict(self):
        return {
            'equipment_id': self.equipment_id, 'asset_code': self.asset_code,
            'equipment_name': self.equipment_name,
            'category': self.category.full_name() if self.category else None,
            'category_id': self.category_id, 'total_quantity': self.total_quantity,
            'available_quantity': self.available_quantity,
            'occupied_quantity': self.total_quantity - self.available_quantity,
            'storage_location': self.storage_location, 'status': self.status,
            'notes': self.notes, 'is_occupied': self.available_quantity == 0,
            'cover_url': f'/api/club/covers/equipment/{self.cover_image}' if self.cover_image else None,
        }


class EquipmentUsage(db.Model):
    __tablename__ = 'equipment_usage'
    usage_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.equipment_id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey('club_activity.activity_id'))
    quantity = db.Column(db.Integer, nullable=False, default=1)
    borrowed_at = db.Column(db.DateTime, default=datetime.utcnow)
    expected_return_at = db.Column(db.DateTime)
    returned_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='使用中')
    notes = db.Column(db.String(500))

    equipment = db.relationship('Equipment', back_populates='usage_records')
    user = db.relationship('User')
    activity = db.relationship('ClubActivity')

    def to_dict(self):
        return {
            'usage_id': self.usage_id, 'equipment_id': self.equipment_id,
            'equipment_name': self.equipment.equipment_name if self.equipment else None,
            'user_id': self.user_id, 'user_name': (self.user.real_name or self.user.username) if self.user else None,
            'activity_id': self.activity_id, 'quantity': self.quantity,
            'borrowed_at': self.borrowed_at.isoformat() if self.borrowed_at else None,
            'expected_return_at': self.expected_return_at.isoformat() if self.expected_return_at else None,
            'returned_at': self.returned_at.isoformat() if self.returned_at else None,
            'status': self.status, 'notes': self.notes,
        }


class SocialAccount(db.Model):
    __tablename__ = 'social_account'
    account_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    platform = db.Column(db.String(50), nullable=False)
    account_name = db.Column(db.String(100), nullable=False)
    link_url = db.Column(db.String(500), nullable=False)
    icon = db.Column(db.String(50))
    status = db.Column(db.SmallInteger, default=1)

    def to_dict(self):
        return {'account_id': self.account_id, 'platform': self.platform,
                'account_name': self.account_name, 'link_url': self.link_url,
                'icon': self.icon, 'status': self.status}


class ClubArchive(db.Model):
    __tablename__ = 'club_archive'
    archive_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(150), nullable=False)
    archive_type = db.Column(db.String(30), nullable=False)
    file_id = db.Column(db.Integer, db.ForeignKey('file.file_id', ondelete='CASCADE'), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    description = db.Column(db.String(500))
    archived_at = db.Column(db.DateTime, default=datetime.utcnow)

    file = db.relationship('File')
    owner = db.relationship('User')

    def to_dict(self):
        return {
            'archive_id': self.archive_id, 'title': self.title,
            'archive_type': self.archive_type, 'description': self.description,
            'file': self.file.to_dict() if self.file else None,
            'owner_name': (self.owner.real_name or self.owner.username) if self.owner else None,
            'archived_at': self.archived_at.isoformat() if self.archived_at else None,
        }
