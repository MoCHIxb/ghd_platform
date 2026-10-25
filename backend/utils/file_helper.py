import os
import re
import uuid

from config import Config

# 原始文件名里可能夹带空字节、换行等控制字符，也可能被旧客户端提交成完整路径，
# 这些必须在入库和写盘之前清理干净。
# 一并清除双向控制符（U+202A~U+202E、U+2066~U+2069、U+200E/200F），否则可以
# 构造出「界面显示为 报告.jpg、实际扩展名是别的」这类视觉欺骗文件名。
_CONTROL_CHARS = re.compile(
    r'[\x00-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]'
)
_VALID_EXT = re.compile(r'^[a-z0-9]{1,10}$')
MAX_NAME_LENGTH = 200


def sanitize_original_name(raw_filename):
    """把浏览器提交的原始文件名拆成「可展示的原始名」和「小写扩展名」。

    这里刻意不使用 werkzeug.secure_filename：它会先把全部非 ASCII 字符丢掉，
    再 strip 掉首尾的点，于是 '升旗照片.jpg' 会被压成 'jpg'——中文名彻底消失，
    连扩展名都解析不出来。而本项目落盘的文件名一律是 UUID，原始名只用于界面
    展示和下载时的 Content-Disposition，因此只要清掉控制字符和路径成分，就可以
    安全地保留中文。

    返回 (original_name, ext)；无法解析出合法扩展名时 ext 为空字符串。
    """
    name = _CONTROL_CHARS.sub(' ', str(raw_filename or ''))
    # 兼容 "C:\Users\x\照片.jpg" 这类完整路径，同时杜绝 ../ 目录穿越
    name = name.replace('\\', '/').rsplit('/', 1)[-1]
    # 折叠多余空白，避免换行被替换后留下 "照片 . jpg" 这类怪名字
    name = ' '.join(name.split())
    if not name:
        return '', ''

    stem, separator, ext = name.rpartition('.')
    ext = ext.lower().strip()
    stem = stem.strip()
    if not separator or not stem or not _VALID_EXT.match(ext):
        # 没有扩展名，或扩展名不合法（例如 '活动方案.第二版'）：整体视作文件名
        stem, ext = name, ''
    if len(stem) > MAX_NAME_LENGTH:
        stem = stem[:MAX_NAME_LENGTH].rstrip()
    return (f'{stem}.{ext}' if ext else stem), ext


def allowed_file(filename: str) -> bool:
    """检查文件扩展名是否在允许列表中"""
    _, ext = sanitize_original_name(filename)
    return bool(ext) and ext in Config.allowed_extensions()


def get_file_type(ext: str) -> str:
    """根据扩展名判断文件类型。"""
    ext = (ext or '').lower()
    if ext in Config.ALLOWED_AUDIO:
        return 'audio'
    if ext in Config.ALLOWED_VIDEO:
        return 'video'
    if ext in Config.ALLOWED_IMAGE:
        return 'image'
    if ext in Config.ALLOWED_DOCUMENT:
        return 'document'
    return 'unknown'


def save_uploaded_file(file_storage, upload_folder: str) -> dict:
    """
    将 werkzeug FileStorage 保存到 upload_folder，使用 UUID 命名。
    返回 dict: {filename, original_name, file_ext, file_type, file_size, storage_path}
    """
    original_name, ext = sanitize_original_name(file_storage.filename)
    unique_name = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    os.makedirs(upload_folder, exist_ok=True)
    storage_path = os.path.join(upload_folder, unique_name)
    file_storage.save(storage_path)
    file_size = os.path.getsize(storage_path)
    return {
        'filename':      unique_name,
        'original_name': original_name or '未命名文件',
        'file_ext':      ext,
        'file_type':     get_file_type(ext),
        'file_size':     file_size,
        'storage_path':  storage_path,
    }


def delete_file_from_disk(storage_path: str) -> bool:
    """删除磁盘文件，成功返回 True"""
    try:
        if storage_path and os.path.exists(storage_path):
            os.remove(storage_path)
            return True
    except OSError:
        pass
    return False


def format_file_size(size_bytes: int) -> str:
    """将字节数格式化为可读字符串"""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
