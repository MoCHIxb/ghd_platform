"""
init_db.py  —  一键初始化数据库
用法:
    cd backend
    python init_db.py
"""
import sys
import os

# 将 backend 目录加入 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bcrypt
from sqlalchemy import inspect, text
from app import create_app
from extensions import db
from models import (User, Role, Permission, Category, Department,
                    EquipmentCategory, Equipment, SocialAccount)


ROLES = [
    {'role_name': 'member', 'description': '普通社员，可参与活动、查看档案和领用设备'},
    {'role_name': 'minister', 'description': '部长，管理本部门业务'},
    {'role_name': 'captain', 'description': '队长，拥有全队管理权限'},
]

PERMISSIONS = [
    ('file:read',       'file',     'read',        '查看文件列表和详情'),
    ('file:upload',     'file',     'upload',       '上传文件'),
    ('file:download',   'file',     'download',     '下载文件'),
    ('file:delete_own', 'file',     'delete_own',   '删除自己上传的文件'),
    ('file:delete_any', 'file',     'delete_any',   '删除任意文件（管理员）'),
    ('file:edit_own',   'file',     'edit_own',     '编辑自己的文件信息'),
    ('file:edit_any',   'file',     'edit_any',     '编辑任意文件信息（管理员）'),
    ('category:read',   'category', 'read',         '查看分类'),
    ('category:write',  'category', 'write',        '管理分类（管理员）'),
    ('user:manage',     'user',     'manage',       '管理用户账户（管理员）'),
    ('log:read_own',    'log',      'read_own',     '查看自己的访问记录'),
    ('log:read_any',    'log',      'read_any',     '查看所有访问记录（管理员）'),
]

# 管理员专属权限名称
ADMIN_ONLY = {'file:delete_any', 'file:edit_any', 'category:write', 'user:manage', 'log:read_any'}

DEPARTMENTS = [
    ('综合办公室', '负责组织协调、文件归档、宣传媒体与素材审阅', 1),
    ('教官部', '负责升旗、出旗及日常训练活动的组织实施', 2),
    ('后勤部', '负责队服、礼宾枪、音响等设备物资保障', 3),
]

ROOT_CATEGORIES = [
    ('活动素材', 1), ('制度文件', 2), ('会议资料', 3), ('宣传材料', 4), ('其他', 5),
]
SUB_CATEGORIES = {
    '活动素材': [('升旗', 1), ('出旗', 2), ('训练', 3)],
    '宣传材料': [('照片', 1), ('视频', 2), ('推文素材', 3)],
}

ADMIN_PASSWORD = 'Admin@123'


def upgrade_schema():
    """为已初始化的上一版数据库补充本次新增字段，避免要求删库重建。"""
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    upgrades = {
        'club_activity': [('cover_image', 'VARCHAR(255) NULL')],
        'equipment': [
            ('cover_image', 'VARCHAR(255) NULL'),
            ('created_at', 'DATETIME NULL'),
            ('updated_at', 'DATETIME NULL'),
        ],
        'equipment_category': [
            ('parent_id', 'INT NULL'),
            ('sort_order', 'INT NOT NULL DEFAULT 0'),
            ('created_at', 'DATETIME NULL'),
            ('updated_at', 'DATETIME NULL'),
        ],
    }
    for table_name, columns in upgrades.items():
        if table_name not in tables:
            continue
        existing = {column['name'] for column in inspector.get_columns(table_name)}
        for column_name, definition in columns:
            if column_name not in existing:
                db.session.execute(text(
                    f'ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {definition}'
                ))
                print(f'  升级字段: {table_name}.{column_name}')
    db.session.commit()


def init():
    app = create_app()
    with app.app_context():
        print('创建数据表...')
        db.create_all()
        upgrade_schema()

        # 角色
        role_objects = {}
        for rd in ROLES:
            r = Role.query.filter_by(role_name=rd['role_name']).first()
            if not r:
                r = Role(**rd)
                db.session.add(r)
                db.session.flush()
                print(f'  创建角色: {r.role_name}')
            role_objects[r.role_name] = r

        # 权限
        perm_objects = {}
        for pname, rtype, act, desc in PERMISSIONS:
            p = Permission.query.filter_by(permission_name=pname).first()
            if not p:
                p = Permission(permission_name=pname, resource_type=rtype, action=act, description=desc)
                db.session.add(p)
                db.session.flush()
                print(f'  创建权限: {pname}')
            perm_objects[pname] = p

        # 角色-权限绑定
        admin_role = role_objects['captain']
        user_role  = role_objects['member']
        minister_role = role_objects['minister']
        for pname, p in perm_objects.items():
            if p not in admin_role.permissions:
                admin_role.permissions.append(p)
            if pname not in ADMIN_ONLY and p not in user_role.permissions:
                user_role.permissions.append(p)
            if p not in minister_role.permissions:
                minister_role.permissions.append(p)

        # 部门
        department_objects = {}
        for name, description, order in DEPARTMENTS:
            row = Department.query.filter_by(department_name=name).first()
            if not row:
                row = Department(department_name=name, description=description, sort_order=order)
                db.session.add(row)
                db.session.flush()
                print(f'  创建部门: {name}')
            department_objects[name] = row

        # 管理员账号
        if not User.query.filter_by(username='captain').first():
            pw_hash = bcrypt.hashpw(ADMIN_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            admin = User(username='captain', real_name='示例队长', password_hash=pw_hash,
                         email='captain@ghd.local', status=1,
                         department=department_objects['综合办公室'])
            admin.roles.append(admin_role)
            db.session.add(admin)
            print(f'  创建队长账号: captain / {ADMIN_PASSWORD}')

        # 初始分类
        cat_map = {}
        for name, order in ROOT_CATEGORIES:
            c = Category.query.filter_by(category_name=name, parent_id=None).first()
            if not c:
                c = Category(category_name=name, sort_order=order)
                db.session.add(c)
                db.session.flush()
                print(f'  创建分类: {name}')
            cat_map[name] = c

        for parent_name, children in SUB_CATEGORIES.items():
            parent = cat_map.get(parent_name)
            if not parent:
                continue
            for name, order in children:
                if not Category.query.filter_by(category_name=name, parent_id=parent.category_id).first():
                    c = Category(category_name=name, parent_id=parent.category_id, sort_order=order)
                    db.session.add(c)
                    print(f'  创建子分类: {parent_name} > {name}')

        # 后勤基础分类与示例设备
        equipment_categories = {}
        equipment_category_tree = {
            '仪仗装备': [('礼宾枪', '训练及仪式用礼宾枪'), ('指挥器材', '指挥刀、口令辅助器材')],
            '服装服饰': [('礼服', '春秋礼服及冬礼服'), ('帽靴配饰', '大檐帽、礼宾靴、绶带等')],
            '宣传器材': [('摄影设备', '相机、镜头与三脚架'), ('音响设备', '音箱、麦克风及扩音器')],
        }
        for order, (name, children) in enumerate(equipment_category_tree.items(), 1):
            row = EquipmentCategory.query.filter_by(category_name=name, parent_id=None).first()
            if not row:
                row = EquipmentCategory(category_name=name, description=f'{name}分类', sort_order=order)
                db.session.add(row)
                db.session.flush()
            equipment_categories[name] = row
            for child_order, (child_name, desc) in enumerate(children, 1):
                child = EquipmentCategory.query.filter_by(category_name=child_name, parent_id=row.category_id).first()
                if not child:
                    child = EquipmentCategory(category_name=child_name, description=desc,
                                              parent_id=row.category_id, sort_order=child_order)
                    db.session.add(child)
                    db.session.flush()
                equipment_categories[child_name] = child
        if not Equipment.query.first():
            db.session.add_all([
                Equipment(asset_code='YZZB-001', equipment_name='礼宾枪', category=equipment_categories['礼宾枪'], total_quantity=24, available_quantity=24, storage_location='器材室 A 区'),
                Equipment(asset_code='XCCM-001', equipment_name='便携音响', category=equipment_categories['音响设备'], total_quantity=2, available_quantity=2, storage_location='器材室 B 区'),
            ])

        if not SocialAccount.query.first():
            db.session.add_all([
                SocialAccount(platform='微信公众号', account_name='校学生国旗护卫队', link_url='https://weixin.qq.com/', icon='微信'),
                SocialAccount(platform='哔哩哔哩', account_name='校学生国旗护卫队', link_url='https://www.bilibili.com/', icon='视频'),
            ])

        db.session.commit()
        print('\n初始化完成！')
        print(f'队长账号: captain  密码: {ADMIN_PASSWORD}')
        print('请在生产环境登录后立即修改默认密码。')


if __name__ == '__main__':
    init()
